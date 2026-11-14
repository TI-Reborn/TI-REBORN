"""Native InventoryUpdate34 (reader 63e4c4, item reader 63d334)."""

from .binary import PacketError, Writer
from .item_list import ItemRecord


def encode_inventory_item_update(owner: int, item: ItemRecord) -> bytes:
    """Replace one existing unmarked, unrented item in a mercenary's inventory."""
    effective, battery, marked, rented = item.unknown_bytes_02
    level, damage, special = item.unknown_bytes_03
    if marked or rented or item.optional_u32 is not None:
        raise PacketError('Marked and rented inventory updates are unsupported')
    w = Writer().u8(0x34).u8(1).u32(owner).u8(0).u32(1)
    w.u32(item.instance_id).u32(item.template_id).u32(item.count).u32(2)
    for value in (*item.unknown_bytes_01, item.equipped):
        w.u8(value)
    w.u32(item.slot)
    for value in item.unknown_words:
        w.u16(value)
    return (w.u8(effective).u8(damage).u8(special).u8(battery).u8(0).u8(0)
            .u8(0).u8(0).u8(level).u8(0).build())
