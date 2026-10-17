"""Bounded TLS probes and two owned-account hosted protocol validation.

No account provisioning, direct login, insecure TLS callback, or production
fault injection. Gameplay requires an existing ignored ownership fixture.
Wire observations retain counters only, never passwords, packets or TLS keys.
This is automated protocol validation; it does not launch graphical clients.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import socket
import ssl
import struct
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def login_preface(session_port):
    require(type(session_port) is int and 1024 <= session_port <= 65535,
            'Invalid advertised loopback session port')
    return b'TIOT\x01\x00' + struct.pack('!H', session_port)


class WireAudit:
    """Incrementally inspect this socket's encrypted TCP bytes in memory.

    Memory is bounded by one TLS record plus one secret-pattern overlap. This
    cannot see other processes or their traffic. Only aggregate metadata is
    exposed; temporary byte buffers disappear when the verifier exits.
    """
    def __init__(self, patterns=(), limit=16 * 1024 * 1024):
        self.patterns = tuple(p for p in patterns if len(p) >= 8)
        self.limit = limit
        self.directions = {key: dict(bytes=0, records=Counter(), pending=bytearray(), tail=b'',
                                    secret_found=False, valid=True) for key in ('sent', 'received')}

    def add_pattern(self, value):
        require(len(value) >= 8, 'Secret scan pattern too short')
        self.patterns += (bytes(value),)

    def feed(self, direction, data):
        state = self.directions[direction]
        state['bytes'] += len(data)
        require(state['bytes'] <= self.limit, 'Bounded TLS wire observation limit exceeded')
        joined = state['tail'] + data
        state['secret_found'] |= any(pattern in joined for pattern in self.patterns)
        overlap = max(map(len, self.patterns), default=1) - 1
        state['tail'] = joined[-overlap:] if overlap else b''
        state['pending'].extend(data)
        while len(state['pending']) >= 5:
            kind, major, minor, size = struct.unpack('!BBBH', state['pending'][:5])
            if kind not in (20, 21, 22, 23) or major != 3 or minor > 4 or size > 18432:
                state['valid'] = False
                raise AssertionError('External socket contains a non-TLS record')
            if len(state['pending']) < size + 5:
                break
            state['records'][str(kind)] += 1
            del state['pending'][:size + 5]

    def metadata(self):
        return {key: dict(bytes=state['bytes'], tls_record_counts=dict(state['records']),
                          valid_tls_record_stream=state['valid'],
                          incomplete_record_bytes=len(state['pending']),
                          plaintext_secret_found=state['secret_found'])
                for key, state in self.directions.items()}


class AuditedTlsSocket:
    """Socket-compatible TLS stream with ordinary chain/name verification.

    SSL MemoryBIO exposes only ciphertext to the underlying TCP socket. There
    is no plaintext fallback. Application writes start after a verified TLS
    handshake; the audited wire is the exact stream sent/received by TCP.
    """
    def __init__(self, address, hostname, context, *, patterns=(), timeout=15):
        require(context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED,
                'TLS verification must remain enabled')
        require(context.minimum_version >= ssl.TLSVersion.TLSv1_2, 'TLS minimum must be 1.2')
        self.raw = socket.create_connection(address, timeout=timeout)
        self.incoming, self.outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        self.tls = context.wrap_bio(self.incoming, self.outgoing, server_side=False, server_hostname=hostname)
        self.audit = WireAudit(patterns)
        self.closed = False
        self.capture_next_write = False
        self.sent_application_bytes = 0
        self.channel = dict(remote=list(address), certificate_name=hostname,
                            application_sent_before_verified_tls=False)
        try:
            deadline = time.monotonic() + timeout
            while True:
                require(time.monotonic() < deadline, 'TLS handshake deadline exceeded')
                try:
                    self.tls.do_handshake()
                    self._flush()
                    break
                except ssl.SSLWantReadError:
                    self._flush()
                    self._read_wire()
                except ssl.SSLWantWriteError:
                    self._flush()
            require(self.tls.version() in ('TLSv1.2', 'TLSv1.3'), 'Unsupported negotiated TLS version')
            cert = self.tls.getpeercert()
            self.channel.update(tls_version=self.tls.version(), cipher=self.tls.cipher(),
                certificate_sha256=hashlib.sha256(self.tls.getpeercert(binary_form=True)).hexdigest(),
                certificate_not_after=cert.get('notAfter'), certificate_san=cert.get('subjectAltName', ()),
                local_ip=self.raw.getsockname()[0], verified_chain_and_name=True)
        except BaseException:
            self.close()
            raise

    def _flush(self):
        while self.outgoing.pending:
            data = self.outgoing.read()
            self.audit.feed('sent', data)
            self.raw.sendall(data)

    def _read_wire(self):
        data = self.raw.recv(65535)
        if data:
            self.audit.feed('received', data)
            self.incoming.write(data)
        else:
            self.incoming.write_eof()
        return bool(data)

    def sendall(self, data):
        if self.capture_next_write:
            # Compare the exact legacy credential frame to external ciphertext,
            # as well as UTF8/UTF16 credentials. Never retain it in the report.
            self.audit.add_pattern(data)
            self.capture_next_write = False
        offset = 0
        while offset < len(data):
            try:
                offset += self.tls.write(data[offset:])
                self._flush()
            except ssl.SSLWantWriteError:
                self._flush()
            except ssl.SSLWantReadError:
                self._flush()
                self._read_wire()
        self.sent_application_bytes += len(data)

    def recv(self, size):
        while True:
            try:
                return self.tls.read(size)
            except ssl.SSLWantReadError:
                self._flush()
                if not self._read_wire():
                    try:
                        return self.tls.read(size)
                    except (ssl.SSLZeroReturnError, ssl.SSLEOFError):
                        return b''
            except ssl.SSLWantWriteError:
                self._flush()
            except (ssl.SSLZeroReturnError, ssl.SSLEOFError):
                return b''

    def close(self):
        if not self.closed:
            self.closed = True
            self.raw.close()

    def metadata(self):
        return dict(**self.channel, application_bytes_sent=self.sent_application_bytes,
                    wire=self.audit.metadata())


def tls_context(*, cafile=None, version=None):
    context = ssl.create_default_context(cafile=str(cafile) if cafile else None)
    # Do not honor SSLKEYLOGFILE: verification must not export traffic keys.
    context.keylog_filename = None
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if version:
        context.minimum_version = context.maximum_version = {
            '1.2': ssl.TLSVersion.TLSv1_2, '1.3': ssl.TLSVersion.TLSv1_3}[version]
    return context


def read_exact(connection, size):
    result = bytearray()
    while len(result) < size:
        part = connection.recv(size - len(result))
        if not part:
            raise EOFError('TLS channel ended before challenge')
        result.extend(part)
    return bytes(result)


class TlsNetworkQA:
    def __init__(self, fixture, host, hostname, login_port, session_port, context, *, local_session_port=28513):
        from test_multi_account import MultiAccountTests
        from types import SimpleNamespace
        self.fixture, self.host, self.hostname = fixture, host, hostname
        self.login_port, self.session_port = login_port, session_port
        self.local_session_port, self.context = local_session_port, context
        self.connections, self.peers, self.received = [], {}, {}
        self.case = MultiAccountTests()
        self.case.config = SimpleNamespace(game_port=login_port, session_port=session_port)
        self.case.clients = self.connections
        self.case.ping = self.ping

    def connect(self, port, *, label):
        patterns = [value.encode(encoding) for value in self.fixture.names[:2] + self.fixture.passwords[:2]
                    for encoding in ('utf-8', 'utf-16-le')]
        connection = AuditedTlsSocket((self.host, port), self.hostname, self.context, patterns=patterns)
        connection.channel['channel'] = label
        self.connections.append(connection)
        return connection

    def begin(self, index):
        from test_server_deployment import Peer
        from tio.protocol.transport import (decode_initial_challenge, expected_reply_fields,
            InitialReply, encode_initial_reply, decode_initial_completion)
        from tio.protocol.login import BasicLoginRequest, encode_basic_login_request, transform_auth_value
        from tio.protocol.server_list import ServerListRequest, encode_server_list_request, decode_server_list
        from tio.protocol.server_login import ServerLoginRequest, encode_server_login_request
        connection = self.connect(self.login_port, label='login')
        connection.sendall(login_preface(self.local_session_port))
        peer = Peer(connection)
        fields = expected_reply_fields(decode_initial_challenge(peer.receive()))
        peer.send(encode_initial_reply(InitialReply(*fields, 0, bytes(3))))
        token = decode_initial_completion(peer.receive()).unknown_u32_01
        request = encode_basic_login_request(BasicLoginRequest(self.fixture.names[index].encode(),
            self.fixture.passwords[index].encode(), transform_auth_value(token)))
        connection.capture_next_write = True
        peer.send(request)
        require(peer.receive() == b'\x04\0', 'TLS account login failed')
        peer.send(encode_server_list_request(ServerListRequest(0, 0, b'')))
        entries = decode_server_list(peer.receive()).entries
        require(len(entries) == 1, 'Expected exactly one shared backend entry')
        entry = entries[0]
        require(entry.address_octets == socket.inet_aton('127.0.0.1') and
                entry.unknown_u16_01 == self.local_session_port, 'TLS login did not advertise its own loopback route')
        require(entry.unknown_u16_02 <= 2, 'Other players online; refuse hosted QA matchmaking')
        peer.send(encode_server_login_request(ServerLoginRequest(1, bytes(8))))
        require(peer.receive() == b'\x08\0', 'TLS handoff preparation failed')
        connection.close()
        return fields[1], token

    def handoff(self, key, *, denied=False, direct_port=None):
        from test_server_deployment import Peer
        from tio.protocol.mode1 import Mode1Reply, encode_mode1_reply, derive_mode1_key
        if direct_port is None:
            connection = self.connect(self.session_port, label='mode1')
        else:
            # This explicit negative probe sends only a single rejected one-time
            # handoff, never a username/password or direct login request.
            connection = socket.create_connection((self.host, direct_port), timeout=10)
        try:
            raw = read_exact(connection, 11)
            peer = Peer(connection, derive_mode1_key(raw[3:]))
            peer.send(encode_mode1_reply(Mode1Reply(*key)))
            if denied:
                try:
                    packet = peer.receive()
                except (EOFError, ConnectionResetError, ssl.SSLEOFError):
                    return None
                raise AssertionError('Invalid mixed/replayed TLS handoff was accepted')
            require(peer.receive() == b'\x0b\0', 'TLS mode1 handoff failed')
            return peer
        finally:
            if direct_port is not None or denied:
                connection.close()

    def record_peer(self, index, peer):
        self.received[index] = []
        original = peer.receive
        def receive():
            packet = original()
            self.received[index].append(packet)
            return packet
        peer.receive = receive
        self.peers[index] = peer
        self.case.enter(peer, self.fixture.names[index])
        return peer

    def enter(self, index):
        return self.record_peer(index, self.handoff(self.begin(index)))

    def ping(self, peer):
        peer.send(b'\x70')
        require(peer.until(b'\x9e', max_packets=4096) == b'\x9e', 'Missing TLS keepalive')

    def command(self, index, packet):
        start = len(self.received[index])
        self.peers[index].send(packet)
        self.ping(self.peers[index])
        return self.received[index][start:]

    def close(self):
        for connection in self.connections:
            connection.close()


PREFLIGHT = r'''
import json,sqlite3,sys
names=json.load(sys.stdin)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account IN (?,?)',names).fetchone()
 rows=[]
 for name in names:
  assert db.execute('SELECT count(*) FROM characters WHERE account=?',(name,)).fetchone()[0]==1
  assert db.execute('SELECT human FROM owned_pets WHERE account=? AND pet_id=1',(name,)).fetchone()[0]==1
  rows.append(dict(account=name,credits=db.execute('SELECT credits FROM wallets WHERE account=?',(name,)).fetchone()[0],
   town=(db.execute('SELECT town_id FROM character_locations WHERE account=?',(name,)).fetchone() or (3,))[0]))
 assert len({r['town'] for r in rows})==1,'Own QA characters must start in the same town'
 print(json.dumps(rows))
'''


def gameplay(args, report):
    from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, OWNERSHIP
    from tio.protocol.item_list import decode_item_list
    from tio.protocol.asset_count import decode_asset_count
    from tio.protocol.city_catalogs import decode_item_shop
    from tio.protocol.shop_purchase import ShopPurchase, encode_shop_purchase
    from tio.protocol.battle_soldier import decode_battle_soldier
    from tio.protocol.battle_move import BattleMove, encode_move_request, decode_battle_move
    from tio.protocol.battle_turn import encode_end_turn
    fixture = FreshSurroundingsQA.load_private(args.fixture)
    require(fixture.host == args.host, 'Fixture ownership target differs from TLS endpoint')
    names = fixture.names[:2]
    require(len(names) == 2, 'Two independently owned accounts are required')
    fixture.remote(OWNERSHIP + '\nprint(json.dumps(dict(owned=True)))', fixture.ownership_payload())
    initial = fixture.remote(PREFLIGHT, names)
    report.update(accounts=names, ownership_checked=True, initial=initial, accounts_created=0,
                  remote_database_writes_by_tool=0)
    network = TlsNetworkQA(fixture, args.host, args.server_name, args.login_port, args.session_port,
                           tls_context(cafile=args.ca_file), local_session_port=args.loopback_session_port)
    battle_started = False
    try:
        first_key = network.begin(0)
        if args.direct_session_port:
            network.handoff(first_key, denied=True, direct_port=args.direct_session_port)
            report['checks'].append('one TLS-login token rejected by direct mode1; no password sent to direct transport')
        keys = [first_key, network.begin(1)]
        require(keys[0] != keys[1], 'Same-NAT accounts received the same handoff token')
        network.handoff((keys[0][0], keys[1][1]), denied=True)
        for index in (1, 0):
            network.record_peer(index, network.handoff(keys[index]))
        network.handoff(keys[0], denied=True)
        report['checks'].append('two same-origin accounts, reversed TLS handoffs, mixed-token rejection and one-time replay rejection')
        for index in (0, 1):
            replies = network.command(index, b'\xc7\1')
            listing = next(p for p in reversed(replies) if p.startswith(b'\xc7\2'))
            require(all(name.encode() + b'\0' in listing for name in names), 'TLS accounts do not share presence')
        text = 'TLS QA ' + datetime.now(timezone.utc).strftime('%H%M%S')
        network.command(0, b'\x21\0' + text.encode('utf-16-le') + b'\0\0')
        reply = network.peers[1].until(b'\x22', max_packets=4096)
        require(text.encode('utf-16-le') in reply,
                'TLS city chat did not reach the second account')
        report['checks'].append('shared presence and city chat delivered between TLS accounts')
        def inventory(index, owner=1):
            replies = network.command(index, b'\x2f' + struct.pack('<HI', 1, owner))
            return decode_item_list(next(p for p in reversed(replies) if p.startswith(b'\x30')))[1]
        before, other_before = inventory(0), inventory(1)
        replies = network.command(0, b'\x73\0')
        category, offers = decode_item_shop(next(p for p in replies if p.startswith(b'\x74')))
        offer = next(o for o in offers if o.item_id == 3)
        require(0 < offer.unknown_u32_03 <= 100 and initial[0]['credits'] >= offer.unknown_u32_03,
                'Expected a bounded affordable QA purchase')
        replies = network.command(0, encode_shop_purchase(ShopPurchase(1, category, offer.unknown_u32_01, 1)))
        purchased = decode_item_list(next(p for p in replies if p.startswith(b'\x30')))[1]
        wallets = [decode_asset_count(p) for p in replies if p.startswith(b'\xc8\x39')]
        require(wallets and wallets[0].credits == initial[0]['credits'] - offer.unknown_u32_03,
                'TLS purchase did not debit the advertised price')
        quantity = lambda items: sum(i.count for i in items if i.template_id == offer.item_id)
        require(quantity(purchased) == quantity(before) + offer.unknown_u32_02,
                'TLS purchase did not deliver the advertised pack')
        require(inventory(1) == other_before, 'Second QA inventory changed after first account purchase')
        report['purchase'] = dict(item=offer.item_id, charged_credits=offer.unknown_u32_03,
                                  units=offer.unknown_u32_02, second_account_isolated=True)
        report['checks'].append('bounded native purchase, correct wallet debit and isolated second account inventory')
        battle_started = True
        for index in (0, 1):
            network.command(index, b'\xba\x03\0\1')
        grounds, own_ids = [], []
        for index in (0, 1):
            if b'\x41' not in network.received[index]:
                network.peers[index].until(b'\x41', max_packets=4096)
            packets = network.received[index]
            grounds.append(next(p for p in reversed(packets) if p.startswith(b'\x35')))
            own = [decode_battle_soldier(p, human_equipment=True) for p in packets
                   if p.startswith(b'\x3b') and int.from_bytes(p[5:9], 'little') == 1]
            require(len(own) == 1, 'Each TLS account must own exactly one native soldier')
            own_ids.append(own[0].soldier_id)
            network.command(index, b'\x36')
        require(grounds[0] == grounds[1] and own_ids[0] != own_ids[1], 'TLS accounts did not share the authoritative scene')
        snapshot = fixture.snapshot(names)
        require(snapshot['bots'] == 0 and {a['account'] for a in snapshot['actors']} == set(names),
                'Hosted battle includes unrelated accounts or bots')
        require(snapshot['ground_sha256'] == hashlib.sha256(grounds[0]).hexdigest(), 'Wire scene differs from authoritative checkpoint')
        for _ in range(6):
            actor = next(a for a in snapshot['actors'] if a['account'] == names[0])
            if snapshot['turn'] == actor['owner']:
                break
            current = next(a for a in snapshot['actors'] if a['owner'] == snapshot['turn'])
            network.command(names.index(current['account']), encode_end_turn())
            snapshot = fixture.snapshot(names)
        require(snapshot['turn'] == actor['owner'] and actor['ap'] > 0, 'No bounded legal QA turn')
        blocked = {tuple(cell) for cell in snapshot['blocked']}
        occupied = {(a['x'], a['y']) for a in snapshot['actors']}
        target = next((cell for cell in ((actor['x']-1, actor['y']), (actor['x']+1, actor['y']),
                       (actor['x'], actor['y']-1), (actor['x'], actor['y']+1))
                       if 0 <= cell[0] < snapshot['width'] and 0 <= cell[1] < snapshot['height']
                       and cell not in blocked | occupied), None)
        require(target is not None, 'No legal adjacent QA movement cell')
        replies = network.command(0, encode_move_request(BattleMove(actor['id'], (target,))))
        require(any(decode_battle_move(p).actor_id == actor['id'] and decode_battle_move(p).path[-1] == target
                    for p in replies if p.startswith(b'\x3d')), 'TLS legal movement reply missing')
        after_move = fixture.snapshot(names)
        moved = next(a for a in after_move['actors'] if a['id'] == actor['id'])
        require((moved['x'], moved['y']) == target and moved['ap'] < actor['ap'], 'TLS movement did not update authoritative position/AP')
        network.command(0, b'\x21\3' + text.encode('utf-16-le') + b'\0\0')
        reply = network.peers[1].until(b'\x22', max_packets=4096)
        require(text.encode('utf-16-le') in reply, 'TLS battle chat missing')
        before_resume = fixture.snapshot(names)
        network.peers[0].sock.close()
        time.sleep(.8)
        network.ping(network.peers[1])
        network.enter(0)
        if b'\x41' not in network.received[0]:
            network.peers[0].until(b'\x41', max_packets=4096)
        replay = next(p for p in reversed(network.received[0]) if p.startswith(b'\x35'))
        require(replay == grounds[0], 'TLS reconnect changed the scene')
        network.command(0, b'\x36')
        after_resume = fixture.snapshot(names)
        require(after_resume['match'] == before_resume['match'] and
                after_resume['actors'] == before_resume['actors'], 'TLS reconnect changed authoritative battle state')
        require(inventory(0, own_ids[0]) == purchased and inventory(1, own_ids[1]) == other_before,
                'TLS reconnect changed purchased inventories')
        report['battle'] = dict(match=snapshot['match'], humans=2, bots=0, actors=own_ids,
            shared_ground_sha256=hashlib.sha256(grounds[0]).hexdigest(), legal_move=list(target),
            ap_before=actor['ap'], ap_after=moved['ap'], reconnect_same_state=True)
        report['checks'].append('shared two-human battle, authoritative movement/AP, battle chat and same-state TLS reconnect')
        report['passed'] = True
    finally:
        if battle_started:
            for index in tuple(network.peers):
                try:
                    network.command(index, b'\x2a\1')
                except (OSError, EOFError, AssertionError, ValueError):
                    pass
        network.close()
        report['tls_channels'] = [connection.metadata() for connection in network.connections]
        report['same_origin_local_ip'] = len({c.channel.get('local_ip') for c in network.connections}) == 1
        report['secrets_persisted'] = False
        require(all(not direction['plaintext_secret_found'] and direction['valid_tls_record_stream']
                    for channel in report['tls_channels'] for direction in channel['wire'].values()),
                'External TLS wire audit failed')


def probe(args, report):
    channels = []
    for version in ('1.2', '1.3'):
        for port, label in ((args.login_port, 'login'), (args.session_port, 'mode1')):
            connection = AuditedTlsSocket((args.host, port), args.server_name,
                                          tls_context(cafile=args.ca_file, version=version))
            try:
                if label == 'login':
                    connection.sendall(login_preface(args.loopback_session_port))
                    from test_server_deployment import Peer
                    from tio.protocol.transport import decode_initial_challenge
                    decode_initial_challenge(Peer(connection).receive())
                else:
                    read_exact(connection, 11)
                channels.append(dict(**connection.metadata(), channel=label))
            finally:
                connection.close()
    report.update(passed=True, tls_channels=channels, accounts_created=0,
                  credentials_used=False, checks=['TLS1.2 and TLS1.3 negotiate with valid chain/name on both native channels'])


def self_test(cert_dir):
    """Local fixture TLS only. CA/cert/key must be generated test material."""
    require(cert_dir is not None, '--self-test requires --test-cert-dir')
    cert_dir = Path(cert_dir)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.minimum_version = ssl.TLSVersion.TLSv1_2
    server_context.load_cert_chain(str(cert_dir / 'valid-chain.pem'), str(cert_dir / 'valid-key.pem'))
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    listener.settimeout(5)
    errors = []
    def echo():
        for _ in range(4):
            try:
                raw, _ = listener.accept()
                with raw:
                    try:
                        with server_context.wrap_socket(raw, server_side=True) as secure:
                            data = secure.recv(4096)
                            if data:
                                secure.sendall(data)
                    except ssl.SSLError:
                        pass  # Wrong-name/unknown-issuer clients deliberately abort.
            except BaseException as error:
                errors.append(type(error).__name__)
    worker = threading.Thread(target=echo)
    worker.start()
    reports = []
    try:
        for version in ('1.2', '1.3'):
            connection = AuditedTlsSocket(listener.getsockname(), 'localhost',
                tls_context(cafile=cert_dir / 'ca.pem', version=version), patterns=(b'qa-fixture-password-123',))
            connection.sendall(b'qa-fixture-password-123')
            require(read_exact(connection, 23) == b'qa-fixture-password-123', 'TLS fixture echo failed')
            reports.append(connection.metadata())
            connection.close()
        for hostname, cafile in (('wrong.invalid', cert_dir / 'ca.pem'), ('localhost', None)):
            try:
                connection = AuditedTlsSocket(listener.getsockname(), hostname, tls_context(cafile=cafile))
            except ssl.SSLCertVerificationError:
                continue
            connection.close()
            raise AssertionError('Invalid certificate was accepted')
    finally:
        worker.join(8)
        listener.close()
    require(not worker.is_alive() and not errors, 'TLS fixture server failed')
    require(all(not d['plaintext_secret_found'] and d['valid_tls_record_stream']
                for r in reports for d in r['wire'].values()), 'TLS ciphertext scan failed')
    rejected_certificates = []
    for certificate, private_key in (('wrongsan-chain.pem', 'wrongsan-key.pem'),
                                    ('expired-chain.pem', 'expired-key.pem'),
                                    ('valid.pem', 'valid-key.pem')):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cert_dir / certificate), str(cert_dir / private_key))
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        server.listen()
        server.settimeout(5)
        def rejected_server(context=context, server=server):
            with server.accept()[0] as raw:
                try:
                    with context.wrap_socket(raw, server_side=True):
                        pass
                except ssl.SSLError:
                    pass
        worker = threading.Thread(target=rejected_server)
        worker.start()
        try:
            try:
                connection = AuditedTlsSocket(server.getsockname(), 'localhost',
                                             tls_context(cafile=cert_dir / 'ca.pem'))
            except ssl.SSLCertVerificationError:
                rejected_certificates.append(certificate)
            else:
                connection.close()
                raise AssertionError('Invalid certificate fixture was accepted')
        finally:
            worker.join(8)
            server.close()
        require(not worker.is_alive(), 'Rejected-certificate fixture thread hung')
    # Fragmentation must not conceal a cleartext secret or malformed record.
    audit = WireAudit((b'private-password',))
    record = b'\x17\x03\x03' + struct.pack('!H', 16) + b'private-password'
    for byte in record:
        audit.feed('sent', bytes((byte,)))
    require(audit.metadata()['sent']['plaintext_secret_found'], 'Fragmented secret was missed')
    try:
        WireAudit().feed('sent', b'plain-game-login')
    except AssertionError:
        pass
    else:
        raise AssertionError('Plaintext wire stream was accepted')
    for port in (0, 1023, 65536):
        try:
            login_preface(port)
        except AssertionError:
            continue
        raise AssertionError('Invalid loopback port accepted')
    print(json.dumps(dict(offline_self_test='passed', remote_contacted=False,
        graphical_clients_started=0, accounts_created=0, verified_tls_versions=['1.2', '1.3'],
        wrong_name_rejected=True, unknown_issuer_rejected=True, fragmented_secret_scan=True,
        rejected_certificate_fixtures=rejected_certificates)))


def local_gameplay_self_test(cert_dir):
    """Run the entire hosted verifier against a temporary real local backend.

    Only ownership lookup and read-only database pathname are adapted. Both
    TLS channels, native codec, shared arena, purchases and reconnect are real.
    No hosted network, existing save, graphical client or installed game used.
    """
    from test_multi_account import MultiAccountTests
    from server.config import TLSConfig
    from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, SNAPSHOT
    from types import SimpleNamespace
    from unittest.mock import patch
    cert_dir = Path(cert_dir)
    case = MultiAccountTests()
    case.setUp()
    ports = []
    sockets = [socket.socket() for _ in range(2)]
    for connection in sockets:
        connection.bind(('127.0.0.1', 0))
        ports.append(connection.getsockname()[1])
    for connection in sockets:
        connection.close()
    case.config = replace(case.config, tls=TLSConfig(True, *ports,
        cert_dir / 'valid-chain.pem', cert_dir / 'valid-key.pem'))
    names = ['qstlsfixturea', 'qstlsfixtureb']
    password = 'local-test-password-123'
    for name in names:
        case.accounts.create(name, password, character=name)
    def run_readonly(code, payload):
        output = io.StringIO()
        source = code.replace('/var/lib/tio-server/reservation.sqlite3', case.config.database.as_posix())
        with patch.object(sys, 'stdin', io.StringIO(json.dumps(payload))), redirect_stdout(output):
            exec(compile(source, '<local read-only QA fixture>', 'exec'), {})
        return json.loads(output.getvalue())
    fixture = SimpleNamespace(host='127.0.0.1', names=names, passwords=[password, password],
        ownership_payload=lambda: {}, snapshot=lambda selected: run_readonly(SNAPSHOT, selected),
        remote=lambda code, payload: run_readonly(PREFLIGHT, payload) if code == PREFLIGHT else dict(owned=True))
    args = SimpleNamespace(host='127.0.0.1', server_name='localhost', login_port=ports[0],
        session_port=ports[1], direct_session_port=case.config.session_port,
        loopback_session_port=31003, ca_file=cert_dir / 'ca.pem', fixture=Path('unused-local-fixture'))
    report = dict(passed=False, checks=[], kind='local real TLS/native protocol fixture; no graphical clients')
    try:
        case.start()
        # Initialize these new fixture characters through actual TLS gameplay.
        bootstrap = TlsNetworkQA(fixture, args.host, args.server_name, args.login_port,
            args.session_port, tls_context(cafile=args.ca_file), local_session_port=args.loopback_session_port)
        try:
            for index in (0, 1):
                bootstrap.enter(index)
        finally:
            bootstrap.close()
        deadline = time.monotonic() + 5
        while case.server.multi.active_accounts:
            require(time.monotonic() < deadline, 'Local bootstrap did not release accounts')
            time.sleep(.02)
        with patch.object(FreshSurroundingsQA, 'load_private', return_value=fixture):
            gameplay(args, report)
        require(report['passed'], 'Local gameplay verifier failed')
    finally:
        case.doCleanups()
    output = ROOT / 'reports/game-tls/local-protocol-verification.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(local_gameplay_self_test='passed', remote_contacted=False,
        graphical_clients_started=0, report=str(output), authoritative_humans=2,
        tls_channels=len(report['tls_channels']), checks=len(report['checks']))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='185.184.42.88')
    parser.add_argument('--server-name', default='ti-reborn.com')
    parser.add_argument('--login-port', type=int, default=29512)
    parser.add_argument('--session-port', type=int, default=29513)
    parser.add_argument('--loopback-session-port', type=int, default=28513)
    parser.add_argument('--direct-session-port', type=int, help='Explicit one-token negative probe; no direct login/password')
    parser.add_argument('--ca-file', type=Path, help='Additional trusted CA file; does not disable verification')
    parser.add_argument('--fixture', type=Path, help='Existing ignored owned QA credentials; never provisioned')
    parser.add_argument('--gameplay', action='store_true', help='Mutate only the two proven-owned QA accounts via TLS gameplay')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/game-tls/hosted-protocol-verification.json')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--local-gameplay-self-test', action='store_true')
    parser.add_argument('--test-cert-dir', type=Path)
    args = parser.parse_args()
    for port in (args.login_port, args.session_port, args.loopback_session_port, args.direct_session_port):
        if port is not None and not 1024 <= port <= 65535:
            parser.error('Ports must be in 1024..65535')
    if args.self_test:
        self_test(args.test_cert_dir)
        return 0
    if args.local_gameplay_self_test:
        local_gameplay_self_test(args.test_cert_dir)
        return 0
    if args.gameplay and not args.fixture:
        parser.error('--gameplay requires the existing --fixture')
    if args.direct_session_port and not args.gameplay:
        parser.error('Mixed-handoff probe requires the owned-account gameplay run')
    report = dict(passed=False, kind='verified game TLS; automated protocol clients, no graphical game clients',
                  observed_utc=datetime.now(timezone.utc).isoformat(), checks=[],
                  limitations=['one origin only; clients from different public IPs require separate validation',
                    'wire counters cover only verifier sockets; native launcher wire requires separate capture',
                    'no production overload/fault injection, certificate rotation, Windows revocation or graphical UI validation'])
    try:
        gameplay(args, report) if args.gameplay else probe(args, report)
    except BaseException as error:
        # Native protocol/credential fixture exceptions can contain secrets.
        report['error_type'] = type(error).__name__
        report['passed'] = False
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'], report=str(args.output), credentials_printed=False,
                         graphical_clients_started=0, accounts_created=0)))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
