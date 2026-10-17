"""Original main-room requests recovered from silver.dll a089f0/a08a50/a08ae4.

These are distinct from the BA group lobby commands. Team-arrow callers
8200f9/8201b4 supply characterID and member.team -/+1 respectively.
"""
from .binary import Reader, Writer, PacketError
from dataclasses import dataclass


@dataclass(frozen=True)
class WagerRoomRecord:
    """TANetBattleServerListItem fields from original RTTI619044."""
    identity: int
    creator_name: bytes
    creator_level: int
    mode: int
    capacity: int
    members: int
    status: int
    soldiers: int
    map_size: int
    level_delta: int
    crest_id: int
    stake: int


def encode_room_list(rooms):
    rooms = tuple(rooms)
    w = Writer().u8(0xc8).u8(0x2c).u32(len(rooms))
    for r in rooms:
        if not isinstance(r.creator_name,bytes) or len(r.creator_name)>255 or b'\0' in r.creator_name:
            raise PacketError('Invalid wager creator name')
        w.u32(r.identity).u16(len(r.creator_name)); w.data.extend(r.creator_name)
        w.u8(r.creator_level).u32(r.mode).u8(r.capacity).u8(r.members).u32(r.status)
        w.u8(r.soldiers).u8(r.map_size).u8(r.level_delta).u32(r.crest_id).u32(r.stake).u8(0)
    if len(w.data)>65533: raise PacketError('Wager list exceeds transport frame')
    return w.build()


def decode_room_list(packet):
    r = Reader(packet)
    if r.read(2) != b'\xc8\x2c': raise PacketError('Expected typed battle list C82C')
    count = r.u32()
    if count > (len(packet)-6)//29: raise PacketError('Impossible wager list count')
    rooms = []
    for _ in range(count):
        identity = r.u32(); size = r.u16()
        if size>255: raise PacketError('Creator name too long')
        name = r.read(size)
        if b'\0' in name: raise PacketError('Invalid creator name')
        rooms.append(WagerRoomRecord(identity,name,r.u8(),r.u32(),r.u8(),r.u8(),r.u32(),r.u8(),r.u8(),r.u8(),r.u32(),r.u32()))
        if r.u8() != 0: raise PacketError('Assault extension is not a wager record')
    r.finish(); return tuple(rooms)


def _identity(packet, opcode):
    r = Reader(packet)
    if r.u8() != opcode: raise PacketError('Unexpected wager-room request')
    value = r.u32()
    if value == 0 or value == 0xffffffff: raise PacketError('Invalid wager-room identity')
    return r, value


def decode_join(packet):
    r, identity = _identity(packet, 0x29); r.finish(); return identity


def decode_kick(packet):
    r, identity = _identity(packet, 0x2b); r.finish(); return identity


def decode_transfer(packet):
    r, identity = _identity(packet, 0x2d); side = r.u8(); r.finish()
    if side not in (0, 1): raise PacketError('Unknown wager team')
    return identity, side


def encode_join(identity):
    packet = Writer().u8(0x29).u32(identity).build(); decode_join(packet); return packet


def encode_kick(identity):
    packet = Writer().u8(0x2b).u32(identity).build(); decode_kick(packet); return packet


def encode_transfer(identity, side):
    packet = Writer().u8(0x2d).u32(identity).u8(side).build(); decode_transfer(packet); return packet
