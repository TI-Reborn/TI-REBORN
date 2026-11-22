"""Warehouse transfer 6B and native clan deposit C2/02."""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError

CLAN_DEPOSIT = b'\xc2\x02'


@dataclass(frozen=True)
class WarehouseTransfer:
    warehouse_type: int
    actor_id: int | None
    first_items: tuple[tuple[int, int], ...]
    second_items: tuple[tuple[int, int], ...]


def encode_warehouse_transfer(request: WarehouseTransfer) -> bytes:
    if request.actor_id is None:
        raise PacketError('WarehouseTransfer6B requires a mercenary')
    w=Writer().u8(0x6b).u8(request.warehouse_type).u32(request.actor_id)
    for items in (request.first_items,request.second_items):
        w.u16(len(items))
        for instance_id,count in items:
            w.u32(instance_id).u32(count)
    if len(w.data)>65533:raise PacketError('Transfer exceeds transport frame')
    return w.build()


def decode_warehouse_transfer(packet: bytes) -> WarehouseTransfer:
    if len(packet)>65533:raise PacketError('Transfer exceeds transport frame')
    r=Reader(packet)
    clan_deposit = packet.startswith(CLAN_DEPOSIT)
    if clan_deposit:
        # Native 0x99f0a0 writes a zero actor for personal-to-clan warehouse donations.
        r.read(len(CLAN_DEPOSIT))
        actor, kind = r.u32(), r.u32()
        if (kind == 1 and actor != 0) or (kind == 2 and actor == 0) or kind not in (1, 2):
            raise PacketError('Invalid clan deposit source')
    else:
        if r.u8()!=0x6b:raise PacketError('Expected WarehouseTransfer6B')
        kind,actor=r.u8(),r.u32()
    arrays=[]
    for _ in range(2):
        arrays.append(tuple((r.u32(),r.u32()) for _ in range(r.u16())))
    r.finish()
    if clan_deposit:
        outgoing, incoming = arrays
        if outgoing or not incoming:
            raise PacketError('Expected clan deposit items only')
        return WarehouseTransfer(kind, actor or None, incoming, ())
    return WarehouseTransfer(kind,actor,*arrays)
