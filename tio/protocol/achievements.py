"""B501 query, B502 list and B503 award; original readers 9637BC/963AC8."""
import struct
from .binary import Reader, Writer, PacketError


def decode_request(packet):
    r=Reader(packet)
    if r.read(2)!=b'\xb5\x01':raise PacketError('Expected B5 01')
    mode=r.u8(); name=bytearray()
    while (v:=r.u8())!=0:
        name.append(v)
        if len(name)>128:raise PacketError('Achievement name too long')
    r.finish()
    if not name:raise PacketError('Character name required')
    return mode,name.decode('cp1251')


def _prizes(w,prizes):
    w.u8(len(prizes))
    for p in prizes:
        kind=p['kind'];w.u8(kind)
        if kind==0:w.u32(p['item_id']).u32(p['count']).u8(p['enhancement'])
        elif kind==1:w.data.extend(struct.pack('<f',p['value']))
        elif kind in (2,3):w.u32(p['value'])
        else:raise PacketError('Unknown achievement prize')


def encode_list(mode,name,records,*,private=True):
    if not name or '\0' in name:raise PacketError('Invalid achievement name')
    w=Writer().u8(0xb5).u8(2).u8(mode)
    w.data.extend(name.encode('cp1251')+b'\0');w.u32(len(records))
    for r in records:
        w.u32(r['id']).u8(r['level']).u32(r['earned'])
        if private:
            w.u32(r['counter']).u32(r['goal']);_prizes(w,r['prizes'])
    return w.build()


def encode_awards(records):
    w=Writer().u8(0xb5).u8(3).u16(len(records))
    for r in records:
        w.u8(0).u32(r['id']).u8(r['level']);_prizes(w,r['prizes'])
    return w.build()
