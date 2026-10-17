"""Original city Gold shop: 76 request, 77 catalog, 78 purchase.

silver.dll: 656230/657070 writers, 656ff0/656394 readers,
991d88 consumer, 991a30 purchase builder. SC (B4) is a separate shop.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError, uint


@dataclass(frozen=True)
class PremiumItem:
    offer_id: int
    item_id: int
    pack_count: int
    gold: int
    durability: int
    currency: int = 1


def encode_premium_shop(category, revision, offers):
    w = Writer().u8(0x77).u32(category)
    w.data.extend(uint(revision, 64).to_bytes(8, 'little'))
    w.u8(0).u32(len(offers))
    for o in offers:
        w.u16(o.offer_id).u32(o.item_id).u32(o.pack_count).u32(0).u32(0)
        w.u8(o.currency).u32(o.gold)  # legacy price attribute; currency1 is credits
        w.u8(0).u8(0).u32(0).u8(0).u32(0xffffffff).u32(0).u8(0).u8(0)
    return w.build()


def decode_premium_request(packet):
    r = Reader(packet)
    if r.u8() != 0x76:
        raise PacketError('Expected Premium catalog request76')
    category = r.u32()
    r.finish()
    return category


def decode_premium_purchase(packet):
    r = Reader(packet)
    if r.u8() != 0x78:
        raise PacketError('Expected Premium purchase78')
    # Native city Buy button sends exactly one selected offer (991a30).
    if r.u32() != 1:
        raise PacketError('Select one Premium offer')
    offer, quantity, owner, category = r.u32(), r.u32(), r.u32(), r.u32()
    revision = int.from_bytes(r.read(8), 'little')
    option = r.u32()
    r.finish()
    if option:
        raise PacketError('Unsupported Premium purchase option')
    return owner, category, offer, quantity, revision
