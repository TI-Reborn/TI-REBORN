"""Original B0 checkpoint queue ABI, verified against silver.dll x86.

Typed B018 writer 65963c/member 65928c and reader 6595f0/member 659240
use u32 count, then u32 identity/u32 role/i32 order/one-byte readiness.
83558c requires a negative-order own row to close an existing queue window.
IDs are ordinary little-endian u32 values; there is no XOR transformation.
"""
from dataclasses import dataclass
import struct

from .binary import PacketError, Reader, uint

MAX_ROWS = 512


@dataclass(frozen=True)
class QueueMember:
    player_id: int
    role: int
    order: int
    ready: bool = False


def _validate(member):
    if not isinstance(member, QueueMember):
        raise PacketError('Expected mine queue member')
    uint(member.player_id, 32)
    if not member.player_id or type(member.role) is not int or member.role not in (1, 2, 3):
        raise PacketError('Invalid mine queue identity or role')
    if type(member.order) is not int or not -1 <= member.order <= 0x7fffffff:
        raise PacketError('Invalid mine queue order')
    if type(member.ready) is not bool:
        raise PacketError('Invalid mine queue readiness')
    return member


def queue_change(members=()):
    members = tuple(map(_validate, members))
    if len(members) > MAX_ROWS or len({m.player_id for m in members}) != len(members):
        raise PacketError('Too many or duplicate mine queue members')
    return b'\xb0\x18' + struct.pack('<I', len(members)) + b''.join(
        struct.pack('<IIiB', m.player_id, m.role, m.order, m.ready)
        for m in members)


def decode_queue_change(packet):
    r = Reader(packet)
    if r.read(2) != b'\xb0\x18':
        raise PacketError('Expected mine queue change B0/18')
    count = r.u32()
    if count > MAX_ROWS:
        raise PacketError('Too many mine queue members')
    result = []
    for _ in range(count):
        player, role = r.u32(), r.u32()
        order = struct.unpack('<i', r.read(4))[0]
        ready = r.u8()
        if ready not in (0, 1):
            raise PacketError('Invalid mine queue readiness')
        result.append(_validate(QueueMember(player, role, order, bool(ready))))
    r.finish()
    if len({m.player_id for m in result}) != len(result):
        raise PacketError('Duplicate mine queue members')
    return tuple(result)


def cancel_notice(player_id):
    uint(player_id, 32)
    if not player_id:
        raise PacketError('Invalid mine queue identity')
    return b'\xb0\x1b' + struct.pack('<I', player_id)


def decode_request(packet):
    """Return (join|cancel|list, role|None), without swallowing ratings B028."""
    r = Reader(packet)
    if r.u8() != 0xb0:
        raise PacketError('Expected checkpoint request B0')
    sub = r.u8()
    if sub == 0x14:
        role = r.u8()
        if role not in (1, 2, 3):
            raise PacketError('Invalid checkpoint role')
        result = ('join', role)
    elif sub == 0x19:
        result = ('cancel', None)
    elif sub in (0x1c, 0x2c):
        result = ('list', None)
    else:
        raise PacketError('Unsupported checkpoint queue request')
    r.finish()
    return result
