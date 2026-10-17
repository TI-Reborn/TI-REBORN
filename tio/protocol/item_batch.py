"""Original6B batch envelope. Mode/group action meanings remain unrecovered."""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError

@dataclass(frozen=True)
class ItemBatch:
    mode:int
    identity:int
    first:tuple[tuple[int,int],...]
    second:tuple[tuple[int,int],...]

def encode_item_batch(batch):
    w=Writer().u8(0x6b).u8(batch.mode).u32(batch.identity)
    for group in (batch.first,batch.second):
        w.u16(len(group))
        for instance,count in group:w.u32(instance).u32(count)
    if len(w.data)>65533:raise PacketError('Item batch exceeds transport frame')
    return w.build()

def decode_item_batch(packet):
    if len(packet)>65533:raise PacketError('Item batch exceeds transport frame')
    r=Reader(packet)
    if r.u8()!=0x6b:raise PacketError('Expected item batch6B')
    mode,identity=r.u8(),r.u32()
    groups=[]
    for _ in range(2):
        count=r.u16()
        if count>(len(r.data)-r.offset)//8:raise PacketError('Truncated item batch')
        groups.append(tuple((r.u32(),r.u32()) for _ in range(count)))
    r.finish()
    return ItemBatch(mode,identity,*groups)
