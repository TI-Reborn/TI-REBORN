"""Original AE private-store builders860a0c..860e50/readers860ed8..861160.

Unit prices are native little-endian f32 credits per unit (ammo per bullet).
All counts are bounded before iterating; UTF16 strings are zero terminated.
"""
import math
import struct
from .binary import Reader,Writer,PacketError


def text(r,maximum=100):
    data=bytearray()
    for _ in range(maximum+1):
        unit=r.read(2)
        if unit==b'\0\0':
            try:return data.decode('utf-16le')
            except UnicodeError as e:raise PacketError('Invalid market text') from e
        data.extend(unit)
    raise PacketError('Market text too long')


def put_text(w,value):
    if '\0' in value:raise PacketError('Invalid market text')
    w.data.extend(value.encode('utf-16le')+b'\0\0');return w


def price(r):
    value=struct.unpack('<f',r.read(4))[0]
    if not math.isfinite(value) or not 0<value<=0xffffffff:raise PacketError('Invalid market unit price')
    cents=round(value*100)
    if not cents:raise PacketError('Market unit price below one hundredth')
    return cents


def put_price(w,cents):w.data.extend(struct.pack('<f',cents/100));return w


def count(r):
    n=r.u32()
    if n>100:raise PacketError('Too many private-market entries')
    return n


def decode(packet):
    r=Reader(packet)
    if r.u8()!=0xae:raise PacketError('Expected private market AE')
    op=r.u8()
    if op==1:
        result=(r.u8(),r.u32())
        if result[0] not in (0,1):raise PacketError('Invalid private store type')
    elif op==3:result=(r.u32(),)
    elif op in (6,7):
        trader=r.u32();n=count(r)
        result=(trader,tuple(tuple(r.u32() for _ in range(3 if op==7 else 2)) for _ in range(n)))
    elif op==8:
        package=r.u8()
        if package not in (0,1):raise PacketError('Invalid private package flag')
        n=count(r);result=(bool(package),tuple((r.u32(),r.u32(),price(r)) for _ in range(n)))
    elif op==9:
        rows=[]
        for _ in range(count(r)):
            template,units,cents=r.u32(),r.u32(),price(r);enhance,filtered=r.u8(),r.u8()
            if filtered not in (0,1) or enhance>27:raise PacketError('Invalid purchase enhancement filter')
            rows.append((template,units,cents,enhance if filtered else None))
        result=(tuple(rows),)
    elif op==10:result=(text(r),)
    else:raise PacketError('Unsupported private market operation')
    r.finish();return op,result


def encode_traders(rows):
    rows=tuple(rows);w=Writer().u8(0xae).u8(2).u32(len(rows))
    for row in rows:
        w.u8(row['kind']).u32(row['id']);put_text(w,row['name']);put_text(w,row['signature'])
        # Native row+10 is a conditional word; no extra extension for value 1.
        w.u32(1)
    return w.build()


def encode_goods(shop,*,buying=False,identity=None):
    w=Writer().u8(0xae).u8(5 if buying else 4).u32(shop['id'] if identity is None else identity)
    entries=shop['orders'] if buying else shop['sales'];w.u32(len(entries))
    if buying:
        for pos,template,units,cents,enhance,held in entries:
            w.u32(template).u32(pos).u32(units);put_price(w,cents)
            w.u8(enhance or 0).u8(int(enhance is not None)).u8(0)
    else:
        for pos,item,cents in entries:
            w.u32(item.template_id).u32(item.instance_id if identity is not None else pos).u32(item.count);put_price(w,cents)
            w.u8(item.unknown_bytes_03[0]).u16(item.unknown_words[0]).u16(item.unknown_words[1]).u8(item.unknown_bytes_03[2])
    return w.build()
