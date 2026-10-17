"""Native ti.exe6DC54C request3E and6F5CFF state3F."""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError

@dataclass(frozen=True)
class DoorRequest:
    actor_id: int
    opened: bool
    x: int
    y: int

def encode_door_request(request):
    return Writer().u8(0x3e).u32(request.actor_id).u8(int(request.opened)).u8(request.x).u8(request.y).build()

def decode_door_request(packet):
    r=Reader(packet)
    if r.u8()!=0x3e:raise PacketError('Expected door request3E')
    actor,opened,x,y=r.u32(),r.u8(),r.u8(),r.u8()
    r.finish()
    if opened not in (0,1):raise PacketError('Invalid door state')
    return DoorRequest(actor,bool(opened),x,y)

def encode_door_state(request):
    return Writer().u8(0x3f).u32(request.actor_id).u8(request.x).u8(request.y).u8(int(request.opened)).build()
