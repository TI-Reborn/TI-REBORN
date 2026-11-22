"""Original 95965c -> 659094 C8/40, with no selected device instance on the wire."""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError


@dataclass(frozen=True)
class MineDefuse:
    actor_id: int
    x: int
    y: int


def encode_mine_defuse(value):
    if any(type(v) is not int or not 0<=v<=0xffffffff for v in (value.actor_id,value.x,value.y)):
        raise PacketError('Defuse fields must be native unsigned scalars')
    return Writer().u8(0xc8).u8(0x40).u32(value.actor_id).u32(value.x).u32(value.y).build()


def decode_mine_defuse(packet):
    r=Reader(packet)
    if (r.u8(),r.u8())!=(0xc8,0x40):raise PacketError('Expected mine defuse C8/40')
    value=MineDefuse(r.u32(),r.u32(),r.u32());r.finish();return value
