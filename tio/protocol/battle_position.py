"""Open battle container46; original writer95E114 (actor u32,x/y u8)."""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError

@dataclass(frozen=True)
class BattlePositionRequest:
    actor_id:int
    x:int
    y:int

def encode_position_request(request):
    return Writer().u8(0x46).u32(request.actor_id).u8(request.x).u8(request.y).build()

def decode_position_request(packet):
    r=Reader(packet)
    if r.u8()!=0x46:raise PacketError('Expected actor position request46')
    request=BattlePositionRequest(r.u32(),r.u8(),r.u8())
    r.finish()
    return request
