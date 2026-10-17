"""Original Silver barter ABI: 84/86/88/8B requests, 85/87/89/8A/8C replies.

713F18,71402C,714368,71493C are the original request writers. Trade records
641B28 use the WarehouseItem subset; 642654 reads a u32 list length.
"""
from .binary import Reader, Writer, PacketError
from .warehouse import encode_warehouse_list, warehouse_item_from_inventory, WarehouseItem

CREDITS_ID = 0xffff0001
GOLD_ID = 0xffff0002
CURRENCIES = {CREDITS_ID: 'credits'}

def name(value):
    if not isinstance(value,bytes) or not 1<=len(value)<=32 or b'\0' in value:
        raise PacketError('Invalid trade recipient')
    return value

def decode_request(packet):
    r=Reader(packet);op=r.u8()
    if op==0x84:
        raw=bytearray()
        while (v:=r.u8())!=0:
            raw.append(v)
            if len(raw)>32:raise PacketError('Invalid trade recipient')
        result=(name(bytes(raw)),r.u32())
    elif op==0x86:
        flag=r.u8()
        if flag not in (0,1):raise PacketError('Invalid trade decision')
        result=(bool(flag),r.u32())
    elif op==0x88:result=(r.u32(),r.u32())
    elif op==0x8b:
        flag=r.u8()
        if flag not in (0,1):raise PacketError('Invalid trade confirmation')
        result=(bool(flag),)
    else:raise PacketError('Unsupported trade request')
    r.finish();return op,result

def invite_request(recipient,pet):return b'\x84'+name(recipient)+b'\0'+Writer().u32(pet).build()
def answer_request(accept,pet):return Writer().u8(0x86).u8(int(accept)).u32(pet).build()
def offer_request(item,count):return Writer().u8(0x88).u32(item).u32(count).build()
def confirm_request(accept=True):return Writer().u8(0x8b).u8(int(accept)).build()
def invitation(sender):return b'\x85'+name(sender)+b'\0'
def done():return b'\x8c'

def record(item):
    projected=warehouse_item_from_inventory(item) if not isinstance(item,WarehouseItem) else item
    raw=encode_warehouse_list(0,1,0,(projected,))[13:]
    # Unlike 6A, 641B28 has no separate special-enhancement boolean.
    if projected.special_enhance:raise PacketError('Special enhancement barter display is not established')
    return raw[:20]+raw[21:]

def money(identity,count):
    if identity not in CURRENCIES:raise PacketError('Invalid trade currency')
    return WarehouseItem(identity,1 if identity==CREDITS_ID else 2,count,1,1,1)

def start(items):
    values=tuple(items)
    if len(values)>255:raise PacketError('Trade inventory too large')
    return Writer().u8(0x87).u32(len(values)).build()+b''.join(record(i) for i in values)

def item_update(item,*,own):return bytes((0x89 if own else 0x8a,))+record(item)
