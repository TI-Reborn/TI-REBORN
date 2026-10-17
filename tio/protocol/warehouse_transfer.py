"""C2S6B original992294: two ordered arrays of instance/count pairs.

The direction of each array is deliberately unnamed until caller semantics
are verified. This codec does not authorize or perform inventory mutations.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError


@dataclass(frozen=True)
class WarehouseTransfer:
    warehouse_type: int
    actor_id: int
    first_items: tuple[tuple[int, int], ...]
    second_items: tuple[tuple[int, int], ...]


def encode_warehouse_transfer(request):
    w=Writer().u8(0x6b).u8(request.warehouse_type).u32(request.actor_id)
    for items in (request.first_items,request.second_items):
        w.u16(len(items))
        for instance_id,count in items:
            w.u32(instance_id).u32(count)
    if len(w.data)>65533:raise PacketError('Transfer exceeds transport frame')
    return w.build()


def decode_warehouse_transfer(packet):
    if len(packet)>65533:raise PacketError('Transfer exceeds transport frame')
    r=Reader(packet)
    if r.u8()!=0x6b:raise PacketError('Expected WarehouseTransfer6B')
    kind,actor=r.u8(),r.u32()
    arrays=[]
    for _ in range(2):
        arrays.append(tuple((r.u32(),r.u32()) for _ in range(r.u16())))
    r.finish()
    return WarehouseTransfer(kind,actor,*arrays)
