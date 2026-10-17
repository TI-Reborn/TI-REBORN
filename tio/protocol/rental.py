"""Original B40E/B40F/B410, silver.dll 8eb510/8ebca8/8eb4b0."""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError


@dataclass(frozen=True)
class RentalOffer:
    lot_id: int
    item_id: int
    enhancement: int
    hours: int
    credits: int
    gold: int


def encode_rental_catalog(offers):
    w = Writer().u8(0xb4).u8(15).u32(len(offers))
    for o in offers:
        w.u32(o.lot_id).u32(o.item_id).u8(o.enhancement).u16(o.hours).u32(o.credits).u32(o.gold)
    if len(w.data) > 65533:
        raise PacketError('Rental catalog exceeds transport limit')
    return w.build()


def decode_rental_request(packet):
    r = Reader(packet)
    if r.u8() != 0xb4:
        raise PacketError('Expected rental request B4')
    action = r.u8()
    if action == 14:
        fields = ()
    elif action == 16:
        fields = (r.u32(), r.u16(), r.u32(), r.u8())  # lot, hours, recipient, currency
    else:
        raise PacketError('Unsupported rental request')
    r.finish()
    return action, fields
