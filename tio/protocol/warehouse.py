"""WarehouseList6A, original63f60c/63ead4.

Items without optional marker names or gift metadata are supported here.
Segment numbering semantics and transfer requests are not established yet.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError


@dataclass(frozen=True)
class WarehouseItem:
    instance_id: int
    template_id: int
    count: int
    durability: int
    max_durability: int
    calculated_max_durability: int
    enhance_level: int = 0
    damage_enhance_level: int = 0
    special_enhance: bool = False
    marked: bool = False
    rented: bool = False
    mark_time_left: int | None = None


def encode_warehouse_list(warehouse_type, segment_count, segment, items):
    items = tuple(items)
    w = Writer().u8(0x6a).u32(warehouse_type).u16(segment_count).u16(segment).u32(len(items))
    for item in items:
        w.u32(item.instance_id).u32(item.template_id).u32(item.count)
        w.u16(item.durability).u16(item.max_durability).u16(item.calculated_max_durability)
        w.u8(item.enhance_level).u8(item.damage_enhance_level)
        for flag in (item.special_enhance, item.marked, item.rented):
            if type(flag) is not bool:
                raise PacketError('Expected warehouse item boolean')
            w.u8(int(flag))
        w.u8(0)  # optional marker name absent
        w.u8(int(item.mark_time_left is not None))
        if item.mark_time_left is not None:
            w.u32(item.mark_time_left)
        w.u8(0)  # optional gift info absent
    if len(w.data) > 65533:
        raise PacketError('Warehouse segment exceeds transport frame')
    return w.build()


def decode_warehouse_list(packet):
    if len(packet) > 65533:
        raise PacketError('Warehouse segment exceeds transport frame')
    r = Reader(packet)
    if r.u8() != 0x6a:
        raise PacketError('Expected WarehouseList6A')
    kind, total, segment, count = r.u32(), r.u16(), r.u16(), r.u32()
    items = []
    for _ in range(count):
        values = [r.u32(), r.u32(), r.u32(), r.u16(), r.u16(), r.u16(), r.u8(), r.u8()]
        flags = [r.u8(), r.u8(), r.u8()]
        if any(flag not in (0, 1) for flag in flags):
            raise PacketError('Invalid warehouse boolean')
        if r.u8() != 0:
            raise PacketError('Warehouse marker name is not supported yet')
        present = r.u8()
        if present not in (0, 1):
            raise PacketError('Invalid optional time flag')
        time_left = r.u32() if present else None
        if r.u8() != 0:
            raise PacketError('Warehouse gift metadata is not supported yet')
        items.append(WarehouseItem(*values, *(bool(flag) for flag in flags), time_left))
    r.finish()
    return kind, total, segment, tuple(items)


def warehouse_item_from_inventory(item):
    """Project ItemList fields identified by original RTTI611ff0/613bc0.

    Item type, slot, battery and trimmed enhancement are not in WarehouseList;
    the persistent original ItemRecord remains authoritative for withdrawal.
    """
    if item.equipped or item.slot:
        raise PacketError('Warehouse item must be unequipped')
    if len(item.unknown_bytes_02) != 4 or len(item.unknown_bytes_03) != 3 or len(item.unknown_words) != 3:
        raise PacketError('Invalid inventory item field widths')
    marked, rented = item.unknown_bytes_02[2:]
    enhance, damage, special = item.unknown_bytes_03
    if any(flag not in (0, 1) for flag in (marked, rented, special)):
        raise PacketError('Invalid inventory boolean')
    return WarehouseItem(item.instance_id, item.template_id, item.count,
                         *item.unknown_words, enhance, damage,
                         bool(special), bool(marked), bool(rented), item.optional_u32)


def encode_warehouse_snapshot(kind,items, *, segment_size=200):
    """Zero-based segments; original992646 clears0,992900 finishes count-1."""
    if type(segment_size) is not int or not 1 <= segment_size <= 1000:
        raise PacketError('Invalid warehouse segment size')
    items=tuple(warehouse_item_from_inventory(item) for item in items)
    chunks=tuple(items[i:i+segment_size] for i in range(0,len(items),segment_size)) or ((),)
    return tuple(encode_warehouse_list(kind,len(chunks),index,chunk) for index,chunk in enumerate(chunks))


def encode_private_warehouse_snapshot(items, *, segment_size=200):
    return encode_warehouse_snapshot(0,items,segment_size=segment_size)
