"""Verify party packets with two disposable, ranking-excluded hosted accounts.

Run explicitly from a configured operator workstation. This changes only owned
QA fixtures and does not claim verification with graphical game clients.
"""
from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import secrets
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

from tio.protocol.binary import Reader
from tio.protocol.friends import read_name
from tio.protocol.ranked import SEARCH_CANCELLED_PACKET, SEARCH_STARTED_PACKET
from tools.clan_icons_hosted_20261018 import Clients
from tools.verify_game_operations_hosted import CREATE, CLEANUP, remote
from tools.verify_premium_effects_hosted import Network
from tools.verify_ranked_cancel_hosted_20261018 import PREPARE


@dataclass(frozen=True)
class Member:
    identity: int
    state: int
    slots: int


def members(packets: Sequence[bytes]) -> dict[bytes, Member]:
    packet = next(packet for packet in reversed(packets) if packet[:2] == b'\xc6\x36')
    reader = Reader(packet[2:])
    reader.u32()  # Leader's viewer-relative identity.
    result = {}
    for _ in range(reader.u32()):
        identity, name = reader.u32(), read_name(reader)
        for _ in range(3):
            reader.u32()  # Level and clan/alliance crests.
        state, slots, count = reader.u8(), reader.u8(), reader.u8()
        for _ in range(count):
            for _ in range(4):
                reader.u32()
            for _ in range(3):
                reader.u16()
        result[name] = Member(identity, state, slots)
    reader.u16()  # Daily token balance.
    reader.finish()
    return result


def run() -> dict[str, object]:
    prefix = 'qt' + secrets.token_hex(4)
    names = [prefix + 'a', prefix + 'b']
    data = {'names': names, 'passwords': [secrets.token_urlsafe(24) for _ in names]}
    report = {'passed': False, 'public_tls_clients': 2, 'graphical_clients': False,
              'fixtures': names, 'checks': []}
    provision = None
    network = None
    try:
        provision = remote(CREATE, list(zip(names, data['passwords'])))
        report['ranking_excluded_from_creation'] = provision['ranking_excluded']
        remote(PREPARE, names)
        network = Network(data)
        for index in range(2):
            network.connect(index)

        def command(index: int, packet: bytes = b'\x70', *, error: bool = False) -> list[bytes]:
            return Clients.command(network, index, packet, allow_error=error)

        invitation = b'\xc6\x32' + names[1].encode() + b'\0\0\0'
        command(0, invitation)
        assert any(packet[:2] == b'\xc6\x35' for packet in command(1))
        assert not members(command(1, b'\xc6\x38'))
        command(1, b'\xc6\x37\0')
        assert not members(command(1, b'\xc6\x38'))
        report['checks'].append('invitation requires consent; decline leaves target ungrouped')

        time.sleep(2.1)
        command(0, invitation)
        command(1)
        command(1, b'\xc6\x37\1')
        first = members(command(0, b'\xc6\x38'))
        second = members(command(1, b'\xc6\x38'))
        assert set(first) == set(second) == {name.encode() for name in names}
        target = first[names[1].encode()].identity
        command(0, b'\xc6\x34' + struct.pack('<IB', target, 2))
        assert members(command(0, b'\xc6\x38'))[names[1].encode()].slots == 2
        command(0, b'\xc6\x34' + struct.pack('<IB', target, 1))
        leader = second[names[0].encode()].identity
        command(1, b'\xc6\x34' + struct.pack('<IB', leader, 2), error=True)
        assert members(command(0, b'\xc6\x38'))[names[0].encode()].slots == 1
        report['checks'].append('shared membership, viewer IDs and allocation authority')

        join = b'\xc6\x21' + bytes(2) + struct.pack('<III', 1, 1, 0) + b'\0'
        command(0, join)
        command(1, join)
        started = command(0, join)
        assert SEARCH_STARTED_PACKET in started
        assert SEARCH_STARTED_PACKET in command(1)
        assert not any(packet[:1] == b'\x41' for packet in started)
        assert SEARCH_CANCELLED_PACKET in command(1, b'\xc6\x23')
        assert all(member.state == 0 for member in members(command(0, b'\xc6\x38')).values())
        report['checks'].append('leader starts shared search; cancellation clears both ready states')

        network.peers[1].sock.close()
        time.sleep(1)
        assert set(members(command(0, b'\xc6\x38'))) == {names[0].encode()}
        assert not members(command(0, b'\xc6\x33'))
        report['checks'].append('disconnect removes member; remaining leader can leave')
        report['passed'] = True
    finally:
        if network is not None:
            network.close()
        time.sleep(1)
        try:
            if provision is not None:
                report['cleanup'] = remote(CLEANUP, {
                    'names': names, 'protected_before': provision['protected_before'],
                    'require_unchanged_players': False,
                })
        finally:
            destination = ROOT / 'reports/ranked-party-refactor-20261024'
            destination.mkdir(parents=True, exist_ok=True)
            (destination / 'hosted-protocol.json').write_text(
                json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    print(json.dumps(run()))
