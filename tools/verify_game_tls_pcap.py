"""Inspect bounded owned-client game TLS pcap without decrypting or logging secrets.

Supports classic pcap Ethernet/Linux cooked v1/v2 and IPv4 TCP. Reassembles
TCP by sequence numbers, tolerates identical retransmissions, rejects gaps or
conflicting overlaps. Reads fixture credentials only into memory. Raw pcap must
remain in the ignored reports/game-tls/private directory; report is metadata.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_game_tls_hosted import WireAudit
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA

PRIVATE = ROOT / 'reports/game-tls/private'
MAX_BYTES = 16 * 1024 * 1024


def require(value, message):
    if not value:
        raise ValueError(message)


def pcap_packets(raw):
    require(24 <= len(raw) <= MAX_BYTES, 'Pcap must be 24 bytes..16 MiB')
    formats = {b'\xd4\xc3\xb2\xa1': '<', b'\xa1\xb2\xc3\xd4': '>',
               b'\x4d\x3c\xb2\xa1': '<', b'\xa1\xb2\x3c\x4d': '>'}
    endian = formats.get(raw[:4])
    require(endian is not None, 'Only classic pcap is supported')
    major, minor, _, _, snaplen, linktype = struct.unpack(endian + 'HHIIII', raw[4:24])
    require((major, minor) == (2, 4) and 1 <= snaplen <= MAX_BYTES and linktype in (1, 113, 276),
            'Unsupported pcap version/linktype/snaplen')
    offset = 24
    while offset < len(raw):
        require(offset + 16 <= len(raw), 'Truncated pcap packet header')
        seconds, fraction, captured, original = struct.unpack_from(endian + 'IIII', raw, offset)
        offset += 16
        require(captured <= snaplen and captured <= original and offset + captured <= len(raw),
                'Invalid/truncated pcap packet')
        require(captured == original, 'Snaplen-truncated packets cannot prove complete TLS streams')
        yield linktype, raw[offset:offset + captured], (seconds, fraction)
        offset += captured


def tcp_packet(linktype, packet):
    if linktype == 1:
        require(len(packet) >= 14, 'Short Ethernet packet')
        protocol, offset = struct.unpack_from('!H', packet, 12)[0], 14
        for _ in range(2):
            if protocol not in (0x8100, 0x88a8):
                break
            require(len(packet) >= offset + 4, 'Short VLAN header')
            protocol = struct.unpack_from('!H', packet, offset + 2)[0]
            offset += 4
    elif linktype == 113:
        require(len(packet) >= 16, 'Short Linux cooked v1 packet')
        protocol, offset = struct.unpack_from('!H', packet, 14)[0], 16
    else:
        require(len(packet) >= 20, 'Short Linux cooked v2 packet')
        protocol, offset = struct.unpack_from('!H', packet, 0)[0], 20
    if protocol != 0x0800:
        return None
    ip = packet[offset:]
    require(len(ip) >= 20 and ip[0] >> 4 == 4, 'Invalid IPv4 header')
    header = (ip[0] & 15) * 4
    total = struct.unpack_from('!H', ip, 2)[0]
    require(20 <= header <= total <= len(ip), 'Incomplete IPv4 packet')
    if ip[9] != 6:
        return None
    require(struct.unpack_from('!H', ip, 6)[0] & 0x3fff == 0, 'Fragmented IPv4 TCP capture is unsupported')
    tcp = ip[header:total]
    require(len(tcp) >= 20, 'Incomplete TCP header')
    source_port, target_port, seq = struct.unpack_from('!HHI', tcp)
    header = (tcp[12] >> 4) * 4
    require(20 <= header <= len(tcp), 'Invalid TCP data offset')
    return dict(source=socket.inet_ntoa(ip[12:16]), target=socket.inet_ntoa(ip[16:20]),
                source_port=source_port, target_port=target_port, seq=seq,
                flags=tcp[13], data=tcp[header:])


class TcpDirection:
    def __init__(self):
        self.segments = []
        self.syn_sequence = None
        self.fin = self.rst = False
        self.wire_payload_bytes = 0
        self.packet_count = 0

    def feed(self, packet):
        self.packet_count += 1
        flags = packet['flags']
        if flags & 2:
            if self.syn_sequence is None:
                self.syn_sequence = packet['seq']
            require(self.syn_sequence == packet['seq'], 'Reused TCP tuple with a different SYN sequence')
        self.fin |= bool(flags & 1)
        self.rst |= bool(flags & 4)
        data = packet['data']
        if data:
            self.wire_payload_bytes += len(data)
            require(self.wire_payload_bytes <= MAX_BYTES, 'Bounded TCP reassembly exceeded')
            self.segments.append(((packet['seq'] + bool(flags & 2)) & 0xffffffff, data))

    def reconstruct(self):
        require(self.syn_sequence is not None, 'Capture started after SYN; complete TLS proof unavailable')
        origin = (self.syn_sequence + 1) & 0xffffffff
        chunks = [((seq - origin) & 0xffffffff, data) for seq, data in self.segments]
        require(all(offset + len(data) <= MAX_BYTES for offset, data in chunks), 'TCP sequence window exceeds bounded capture')
        result = bytearray()
        overlap_bytes = 0
        for offset, data in sorted(chunks, key=lambda item: item[0]):
            require(offset <= len(result), 'TCP capture has a missing payload gap')
            overlap = min(len(result) - offset, len(data))
            require(result[offset:offset + overlap] == data[:overlap], 'TCP retransmission has conflicting payload')
            overlap_bytes += overlap
            result.extend(data[overlap:])
        return bytes(result), dict(packet_count=self.packet_count, wire_payload_bytes=self.wire_payload_bytes,
                                  reassembled_bytes=len(result), retransmitted_overlap_bytes=overlap_bytes,
                                  syn_seen=True, fin_seen=self.fin, reset_seen=self.rst)


def inspect(raw, patterns, *, client_ip, server_ip, ports=(29512, 29513), captured_ports=(29512, 29513)):
    flows, counts = {}, Counter()
    for linktype, frame, timestamp in pcap_packets(raw):
        counts['packets_total'] += 1
        packet = tcp_packet(linktype, frame)
        if packet is None:
            counts['non_ipv4_tcp_packets'] += 1
            continue
        if packet['source'] == client_ip and packet['target'] == server_ip:
            direction, client_port, server_port = 'sent', packet['source_port'], packet['target_port']
        elif packet['source'] == server_ip and packet['target'] == client_ip:
            direction, client_port, server_port = 'received', packet['target_port'], packet['source_port']
        else:
            counts['other_ip_packets'] += 1
            continue
        if server_port in (28512, 28513):
            counts['legacy_tcp_packets'] += 1
            if packet['data']:
                counts['legacy_payload_packets'] += 1
        if server_port not in ports:
            counts['other_port_packets'] += 1
            continue
        counts['selected_tcp_packets'] += 1
        key = client_port, server_port
        flow = flows.setdefault(key, {'sent': TcpDirection(), 'received': TcpDirection()})
        flow[direction].feed(packet)
    channels = []
    observed_ports = set()
    secret_found = False
    for (client_port, server_port), directions in sorted(flows.items()):
        audit = WireAudit(patterns)
        tcp = {}
        for direction, stream in directions.items():
            payload, tcp[direction] = stream.reconstruct()
            require(payload, 'TCP channel did not contain TLS payload in both directions')
            audit.feed(direction, payload)
        metadata = audit.metadata()
        require(all(value['valid_tls_record_stream'] and value['incomplete_record_bytes'] == 0
                    and value['tls_record_counts'].get('22', 0) >= 1 for value in metadata.values()),
                'TCP stream did not contain a complete TLS handshake record stream')
        secret_found |= any(value['plaintext_secret_found'] for value in metadata.values())
        observed_ports.add(server_port)
        channels.append(dict(client_port=client_port, server_port=server_port, tcp=tcp, wire=metadata))
    require(set(ports) <= observed_ports, 'Capture did not prove both external TLS channels')
    scope = set(captured_ports)
    legacy_scope = {28512, 28513} <= scope
    legacy_observed = counts['legacy_tcp_packets'] > 0
    return dict(passed=not secret_found and not legacy_observed, observed_utc=datetime.now(timezone.utc).isoformat(),
        kind='owned native-client external wire; classic pcap TCP reassembly, no decrypt/key logs',
        client_public_ip=client_ip, server_ip=server_ip, observed_tls_ports=sorted(observed_ports),
        captured_ports_declared=sorted(scope), channels=channels, capture_counts=dict(counts),
        plaintext_credentials_found=secret_found, secrets_persisted=False,
        legacy_tcp_observed=legacy_observed, no_legacy_connections_proven=legacy_scope and not legacy_observed,
        limitations=['one public client origin only; second public IP needs separate validation',
                     'TLS records cannot establish GUI/battle success or endpoint certificate verification',
                     'absence of direct connections is proved only when capture scope includes both legacy ports'])


def fixture_pcap(linktype, frames):
    raw = bytearray(b'\xd4\xc3\xb2\xa1' + struct.pack('<HHIIII', 2, 4, 0, 0, 65535, linktype))
    for frame in frames:
        raw.extend(struct.pack('<IIII', 1, 0, len(frame), len(frame)) + frame)
    return bytes(raw)


def fixture_frame(linktype, source, target, sport, dport, seq, flags, data):
    tcp = struct.pack('!HHIIBBHHH', sport, dport, seq, 0, 5 << 4, flags, 65535, 0, 0) + data
    ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(tcp), 1, 0, 64, 6, 0,
                     socket.inet_aton(source), socket.inet_aton(target)) + tcp
    if linktype == 1:
        return bytes(12) + b'\x08\0' + ip
    if linktype == 113:
        return bytes(14) + b'\x08\0' + ip
    return b'\x08\0' + bytes(18) + ip


def self_test():
    client, server = '84.251.245.239', '185.184.42.88'
    stream = b'\x16\x03\x03\x00\x04test\x17\x03\x03\x00\x06cipher'
    checks = 0
    for linktype in (1, 113, 276):
        frames = []
        for port in (29512, 29513):
            client_port = port + 10000
            for direction in (0, 1):
                src, dst, sport, dport = ((client, server, client_port, port) if direction == 0 else
                                         (server, client, port, client_port))
                frames.extend((fixture_frame(linktype, src, dst, sport, dport, 99, 2, b''),
                    fixture_frame(linktype, src, dst, sport, dport, 107, 16, stream[7:]),
                    fixture_frame(linktype, src, dst, sport, dport, 100, 16, stream[:12]),
                    fixture_frame(linktype, src, dst, sport, dport, 100, 16, stream[:12])))
        report = inspect(fixture_pcap(linktype, frames), (b'private-password',), client_ip=client, server_ip=server)
        require(report['passed'] and len(report['channels']) == 2 and
                all(c['tcp']['sent']['retransmitted_overlap_bytes'] > 0 for c in report['channels']),
                'Reassembly fixture failed')
        checks += 1
        secret_stream = b'\x16\x03\x03\x00\x10private-password'
        secret = [fixture_frame(linktype, client, server, 41001, 29512, 99, 2, b''),
                  fixture_frame(linktype, client, server, 41001, 29512, 100, 16, secret_stream),
                  fixture_frame(linktype, server, client, 29512, 41001, 99, 2, b''),
                  fixture_frame(linktype, server, client, 29512, 41001, 100, 16, secret_stream)]
        bad = inspect(fixture_pcap(linktype, secret), (b'private-password',), client_ip=client, server_ip=server, ports=(29512,))
        require(not bad['passed'] and bad['plaintext_credentials_found'], 'Cleartext credential fixture accepted')
        checks += 1
    direction = TcpDirection()
    direction.feed(dict(seq=99, flags=2, data=b''))
    direction.feed(dict(seq=101, flags=16, data=b'gap'))
    try:
        direction.reconstruct()
    except ValueError:
        checks += 1
    else:
        raise AssertionError('TCP gap accepted')
    direction = TcpDirection()
    direction.feed(dict(seq=99, flags=2, data=b''))
    direction.feed(dict(seq=100, flags=16, data=b'original'))
    direction.feed(dict(seq=100, flags=16, data=b'conflict'))
    try:
        direction.reconstruct()
    except ValueError:
        checks += 1
    else:
        raise AssertionError('Conflicting retransmission accepted')
    print(json.dumps(dict(offline_self_test='passed', checks=checks, remote_contacted=False, credentials_used=False)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pcap', type=Path)
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--client-ip', default='84.251.245.239')
    parser.add_argument('--server-ip', default='185.184.42.88')
    parser.add_argument('--captured-ports', type=int, nargs='+', default=[29512, 29513])
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/game-tls/native-wire-verification.json')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.pcap is None or args.fixture is None:
        parser.error('--pcap and --fixture are required')
    report = dict(passed=False, secrets_persisted=False)
    try:
        path = args.pcap.resolve()
        require(path.is_relative_to(PRIVATE.resolve()) and path.is_file(), 'Raw pcap must remain inside this ignored private folder')
        require((PRIVATE / '.gitignore').read_text(encoding='utf-8').strip() == '*', 'Private capture folder must be ignored')
        require(path.stat().st_size <= MAX_BYTES, 'Pcap exceeds 16 MiB bound')
        fixture = FreshSurroundingsQA.load_private(args.fixture)
        require(fixture.host == args.server_ip, 'Private fixture belongs to a different hosted server')
        patterns = tuple(value.encode(encoding) for value in fixture.names[:2] + fixture.passwords[:2]
                         for encoding in ('utf-8', 'utf-16-le'))
        raw = path.read_bytes()
        report = inspect(raw, patterns, client_ip=args.client_ip, server_ip=args.server_ip,
                         captured_ports=args.captured_ports)
        report['pcap_sha256'] = hashlib.sha256(raw).hexdigest()
        report['pcap_bytes'] = len(raw)
        report['legacy_credential_frame_scan'] = 'Unavailable from TLS ciphertext; UTF8/UTF16 login/password scanned only'
    except Exception as error:
        # Fixture/protocol exceptions may carry private arguments or payloads.
        report['error_type'] = type(error).__name__
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'], report=str(args.output), credentials_printed=False)))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
