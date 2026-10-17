"""Opt-in emulator FA/v1 warehouse UI snapshot; never an item operation.

The selected character and city are derived by the authenticated server.
Counts are item rows, not weight or quantities. Accessible includes retained
legacy/overflow or other native projected rows; used may exceed capacity for
grandfathered storage. Old clients receive no FA packets.
"""
from dataclasses import dataclass
import struct

OPT_IN = b'\xfa\x01\x00'
CLEAR = b'\xfa\x01\x02'
MAX_COUNT = 0x7fffffff


@dataclass(frozen=True)
class Snapshot:
    character_id: int
    town: int
    kind: int
    capacity: int
    used: int
    accessible: int


def _validate(value):
    if not isinstance(value, Snapshot):
        raise ValueError('Warehouse capacity snapshot required')
    for name in ('character_id', 'town', 'kind', 'capacity', 'used', 'accessible'):
        if type(getattr(value, name)) is not int:
            raise ValueError('Warehouse capacity fields must be integers')
    if not 1 <= value.character_id <= MAX_COUNT or not 1 <= value.town <= MAX_COUNT:
        raise ValueError('Invalid warehouse capacity identity')
    if value.kind not in (0, 1, 2) or not 1 <= value.capacity <= 65535:
        raise ValueError('Invalid warehouse capacity scope')
    if not 0 <= value.used <= value.accessible <= MAX_COUNT:
        raise ValueError('Invalid warehouse capacity counts')
    return value


def encode_snapshot(value):
    value = _validate(value)
    return b'\xfa\x01\x01' + struct.pack('<IIBIII', value.character_id,
        value.town, value.kind, value.capacity, value.used, value.accessible)


def encode_opt_in():
    return OPT_IN


def encode_clear():
    return CLEAR


def decode(packet):
    if type(packet) is not bytes:
        raise ValueError('Warehouse capacity packet must be bytes')
    if packet == OPT_IN:
        return 'opt_in'
    if packet == CLEAR:
        return 'clear'
    if len(packet) != 24 or packet[:3] != b'\xfa\x01\x01':
        raise ValueError('Invalid warehouse capacity packet')
    return _validate(Snapshot(*struct.unpack('<IIBIII', packet[3:])))
