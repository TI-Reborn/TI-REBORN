"""Sale: quote B806/B807 (8a0fe4/8a15a0), commit23 (99034c)."""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError


@dataclass(frozen=True)
class ShopSale:
    owner_id: int
    instance_id: int
    quantity: int


def encode_sale_request(value, *, quote=False):
    w = Writer()
    if quote:
        w.u8(0xb8).u8(6)
    else:
        w.u8(0x23)
    return w.u32(value.owner_id).u32(value.instance_id).u32(value.quantity).build()


def decode_sale_request(data, *, quote=False):
    r = Reader(data)
    expected = b'\xb8\x06' if quote else b'\x23'
    if r.read(len(expected)) != expected:
        raise PacketError('Expected sale request')
    result = ShopSale(r.u32(), r.u32(), r.u32())
    r.finish()
    return result


def encode_sale_quote(discarded_id, credits):
    # First u32 is discarded by the current client's reader; echo recipient.
    return Writer().u8(0xb8).u8(7).u32(discarded_id).u32(credits).build()
