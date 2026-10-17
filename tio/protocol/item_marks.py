"""S2C native30/6A mark metadata, readers63bd38/63e978 ->629860 UTF16 NUL.

The optional name/remaining-seconds branches are outgoing projections only;
stored inventories retain the existing codec. There is no invented mark opcode.
RTTI6122bf: +31=fmarked,+33=frent,+38=markerOwnerName,+40=markTimeLeft.
"""
import struct
from .binary import Reader,PacketError
from .item_list import decode_item_list,encode_item_list
from .warehouse import decode_warehouse_list,encode_warehouse_list


def _branch(name,remaining):
    if not isinstance(name,str) or not 1<=len(name)<=100 or any(ord(c)<32 for c in name):raise PacketError('Invalid mark owner name')
    if type(remaining) is not int or not 0<=remaining<=0xffffffff:raise PacketError('Invalid remaining mark seconds')
    try:encoded=name.encode('utf-16le')
    except UnicodeError as e:raise PacketError('Invalid mark owner UTF16') from e
    return b'\x01'+encoded+b'\0\0'+b'\x01'+struct.pack('<I',remaining)


def project(packet, metadata):
    if packet[:1]==b'\x6a':return project_warehouse(packet,metadata)
    owner,items,flag=decode_item_list(packet);out=bytearray(packet[:10])
    for item in items:
        raw=encode_item_list(0,(item,))[10:]
        mark=metadata.get(item.instance_id)
        if mark is None:out.extend(raw);continue
        name,remaining=mark
        if not item.unknown_bytes_02[2] or item.unknown_bytes_02[3] or item.optional_u32 is not None:
            raise PacketError('Mark projection requires a genuine nonrental mark')
        out.extend(raw[:29]+_branch(name,remaining)+raw[31:])
    if len(out)>65533:raise PacketError('Projected ItemList exceeds frame size')
    return bytes(out)


def project_warehouse(packet,metadata):
    kind,total,segment,items=decode_warehouse_list(packet);out=bytearray(packet[:13])
    for item in items:
        raw=encode_warehouse_list(kind,total,segment,(item,))[13:];mark=metadata.get(item.instance_id)
        if mark is None:out.extend(raw);continue
        if not item.marked or item.rented or item.mark_time_left is not None:raise PacketError('Mark projection requires a genuine nonrental warehouse mark')
        out.extend(raw[:23]+_branch(*mark)+raw[25:])
    if len(out)>65533:raise PacketError('Projected WarehouseList exceeds frame size')
    return bytes(out)


def metadata(packet):
    """Focused verifier of actual projected branches; returns id -> (name,seconds)."""
    r=Reader(packet)
    opcode=r.u8()
    if opcode==0x30:r.u32();r.u8();header,minimum,rest,tail=10,35,25,3
    elif opcode==0x6a:r.u32();r.u16();r.u16();header,minimum,rest,tail=13,26,19,0
    else:raise PacketError('Expected ItemList30 or WarehouseList6A')
    count=r.u32();result={}
    if count>(len(packet)-header)//minimum:raise PacketError('Invalid item count')
    for _ in range(count):
        identity=r.u32();r.read(rest);flag=r.u8();name=None
        if flag not in (0,1):raise PacketError('Invalid optional name')
        if flag:
            data=bytearray()
            while (unit:=r.read(2))!=b'\0\0':
                data.extend(unit)
                if len(data)>400:raise PacketError('Mark owner name is too long')
            try:name=bytes(data).decode('utf-16le')
            except UnicodeDecodeError as e:raise PacketError('Invalid mark owner UTF16') from e
        present=r.u8()
        if present not in (0,1):raise PacketError('Invalid optional remaining time')
        seconds=r.u32() if present else None
        if name is not None:result[identity]=(name,seconds)
        r.read(tail)
        if r.u8():raise PacketError('Unsupported nested item')
    r.finish();return result
