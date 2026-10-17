"""Ordinary shop purchase request75, original builder9919c8.

Caller9762b7 parses quantity from UI text;976301 multiplies it for totals.
Offer ID comes from shop record+30; price credits from+40 (suffix cr).
"""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError


@dataclass(frozen=True)
class ShopPurchase:
    owner_id: int
    category: int
    offer_id: int
    quantity: int


def encode_shop_purchase(request):
    return (Writer().u8(0x75).u32(request.owner_id).u8(request.category)
            .u32(request.offer_id).u32(request.quantity).build())


def decode_shop_purchase(packet):
    r=Reader(packet)
    if r.u8()!=0x75:raise PacketError('Expected shop purchase75')
    result=ShopPurchase(r.u32(),r.u8(),r.u32(),r.u32())
    r.finish()
    return result
