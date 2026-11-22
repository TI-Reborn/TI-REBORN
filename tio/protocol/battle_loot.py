"""Original46 open,47 container list and40 transfer (98F5CC).

47 serializer640718: actor u32, coordinates u16, count u32;
entry63FC90. Request40 sends deposits first, withdrawals second.
"""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError
from .item_list import ItemRecord


@dataclass(frozen=True)
class LootTransfer:
    actor_id:int
    x:int
    y:int
    deposits:tuple=()
    withdrawals:tuple=()
    live:bool=False
    nonce:int=0


def encode_open_container_state(x,y):
    """44 scene state: x,y,open=1,extra cell flag=0.

    ti.exe6F5D7A reads all four bytes; silver.dll961F60 reads only x/y.
    The scene selects crate state4 (animation) or2 (open), preserving its
    original tile/orientation and choosing the open frame at base_frame+1.
    """
    return Writer().u8(0x44).u8(x).u8(y).u8(1).u8(0).build()


def encode_loot_transfer(request):
    w=Writer().u8(0xf5 if request.live else 0x40)
    if request.live:w.u32(request.nonce)
    w.u32(request.actor_id).u8(request.x).u8(request.y)
    for selection in (request.deposits,request.withdrawals):
        w.u32(len(selection))
        for identity,count in selection:w.u32(identity).u32(count)
    return w.build()


def decode_loot_transfer(packet,*,allow_empty=False):
    r=Reader(packet)
    opcode = r.u8()
    if opcode not in (0x40, 0xf5):raise PacketError('Expected loot transfer40/F5')
    nonce = r.u32() if opcode == 0xf5 else 0
    if opcode == 0xf5 and not nonce:raise PacketError('Live transfer needs a nonzero nonce')
    actor,x,y=r.u32(),r.u8(),r.u8()
    selections=[]
    for _ in range(2):
        count=r.u32()
        if count>1000 or count>(len(packet)-r.offset)//8:raise PacketError('Invalid transfer count')
        values=tuple((r.u32(),r.u32()) for _ in range(count))
        if len({i for i,n in values})!=count or any(not i or not (0 if allow_empty else 1)<=n<=0x7fffffff for i,n in values):
            raise PacketError('Invalid transfer selection')
        selections.append(values)
    r.finish()
    if set(i for i,n in selections[0]) & set(i for i,n in selections[1]):raise PacketError('Item moves both ways')
    return LootTransfer(actor,x,y,*selections,live=opcode==0xf5,nonce=nonce)


def encode_container(actor,x,y,items):
    items=tuple(items)
    w=Writer().u8(0x47).u32(actor).u16(x).u16(y).u32(len(items))
    for item in items:
        w.u32(item.instance_id).u32(item.template_id).u32(item.count)
        for v in item.unknown_words:w.u16(v)
        #47 puts the real upgrade beside the effective upgrade. ItemList30
        # stores it in the trailing block instead (native9916CE/9916F4).
        w.data.extend(bytes((item.unknown_bytes_02[0],item.unknown_bytes_03[0],*item.unknown_bytes_02[1:])))
        w.u8(0) # optional marker name
        w.u8(0) # optional marker duration
    if len(w.data)>65533:raise PacketError('Container exceeds frame size')
    return w.build()


def decode_container(packet):
    r=Reader(packet)
    if r.u8()!=0x47:raise PacketError('Expected container47')
    actor,x,y,count=r.u32(),r.u16(),r.u16(),r.u32()
    if count>(len(packet)-r.offset)//25:raise PacketError('Truncated container')
    items=[]
    for _ in range(count):
        identity,template,quantity=r.u32(),r.u32(),r.u32()
        words=tuple(r.u16() for _ in range(3));flags=r.read(5)
        if any(flags[3:]) or r.read(2)!=b'\0'*2:raise PacketError('Marked/rented container items unsupported')
        items.append(ItemRecord(identity,template,b'\0\0',quantity,0,0,words,
                                bytes((flags[0],*flags[2:])),None,bytes((flags[1],0,0))))
    r.finish()
    return actor,x,y,tuple(items)
