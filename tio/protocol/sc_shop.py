"""SC B4 protocol, recovered from silver.dll 655368/655bd0/8eb8d0.

The first price pair in 05 is overwritten by the second in 8ebb55..68.
Keep both on the wire. Enhancement is independent of the item template.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError


@dataclass(frozen=True)
class SCOffer:
    lot_id: int
    item_id: int
    enhancement: int
    available: int
    base_credits: int
    base_gold: int
    credits: int
    gold: int
    discount: int
    durability: int


def encode_sc_catalog(offers):
    w = Writer().u8(0xb4).u8(5).u32(len(offers))
    for o in offers:
        w.u32(o.lot_id).u32(o.item_id).u8(o.enhancement).u16(o.available)
        w.u32(o.base_credits).u32(o.base_gold).u32(o.credits).u32(o.gold)
        w.u8(o.discount).u16(o.durability)
    if len(w.data) > 65533:
        raise PacketError('SC catalog exceeds transport limit')
    return w.build()


def decode_sc_request(packet):
    r = Reader(packet)
    if r.u8() != 0xb4:
        raise PacketError('Expected SC request B4')
    action = r.u8()
    widths = {4: 0, 6: 3, 7: 0, 9: 1, 10: 1, 11: 2, 12: 0}
    if action not in widths:
        raise PacketError('Unsupported SC request')
    fields = tuple(r.u32() for _ in range(widths[action]))
    r.finish()
    return action, fields


def encode_sc_basket(rows):
    """Rows are (SCOffer, quantity); totals have no local discounts/tax."""
    w = Writer().u8(0xb4).u8(8).u32(len(rows))
    for o, quantity in rows:
        w.u32(o.lot_id).u32(o.item_id).u8(o.enhancement).u16(o.available)
        w.u32(o.credits).u32(o.gold).u8(o.discount).u16(o.durability).u16(quantity)
    credits = sum(o.credits * n for o, n in rows)
    gold = sum(o.gold * n for o, n in rows)
    w.u32(credits).u32(credits).u8(0).u32(gold).u32(gold).u8(0)
    if len(w.data) > 65533:
        raise PacketError('SC basket exceeds transport limit')
    return w.build()
