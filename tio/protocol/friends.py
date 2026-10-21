"""Original net3_friends: A1 answer, A2 remove, A3 invite, A6 list; 9F/A0 replies."""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError

def read_name(r):
    name=bytearray()
    while (v:=r.u8())!=0:
        name.append(v)
        if len(name)>32:raise PacketError('Friend name too long')
    if not name or any(c<32 for c in name):raise PacketError('Invalid friend name')
    return bytes(name)

def decode_request(packet):
    r=Reader(packet);op=r.u8()
    if op in (0xa2,0xa3):value=read_name(r)
    elif op==0xa1:
        value=r.u8()
        if value not in (0,1):raise PacketError('Invalid friendship answer')
    elif op==0xa6:value=None
    else:raise PacketError('Unexpected friends request')
    r.finish();return op,value

def encode_invite(name):
    packet=b'\xa0'+name+b'\0';r=Reader(packet[1:]);read_name(r);r.finish();return packet

@dataclass(frozen=True)
class Friend:
    identity:int
    name:bytes
    online:bool=False
    level:int=1
    rank:int=0
    status:int=0
    crest:int=0

def encode_list(rows):
    rows=tuple(rows)
    if len(rows)>100:raise PacketError('Too many friends')
    w=Writer().u8(0x9f).u16(len(rows))
    for p in rows:
        encode_invite(p.name)
        w.u32(p.identity);w.data.extend(p.name+b'\0')
        w.u8(int(p.online)).u8(p.level).u32(p.rank).u8(p.status).u32(p.crest)
    return w.build()

def decode_list(packet):
    r=Reader(packet)
    if r.u8()!=0x9f:raise PacketError('Expected friends list')
    count=r.u16()
    if count>100:raise PacketError('Too many friends')
    rows=[]
    for _ in range(count):rows.append(Friend(r.u32(),read_name(r),bool(r.u8()),r.u8(),r.u32(),r.u8(),r.u32()))
    r.finish();return tuple(rows)
