"""81 from original8c0730; callers8b5550/8b5cc9 establish field order.

Third u32 is zero in both known UI callers; its wider meaning is unknown.
"""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError

@dataclass(frozen=True)
class AbilityCast:
    ability_id:int
    actor_id:int
    unknown_u32:int
    x:int
    y:int

def encode_ability_cast(request):
    return Writer().u8(0x81).u32(request.ability_id).u32(request.actor_id).u32(request.unknown_u32).u8(request.x).u8(request.y).build()

def decode_ability_cast(packet):
    r=Reader(packet)
    if r.u8()!=0x81:raise PacketError('Expected ability cast81')
    result=AbilityCast(r.u32(),r.u32(),r.u32(),r.u8(),r.u8());r.finish()
    return result
