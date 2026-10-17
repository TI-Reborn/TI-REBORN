"""S2C C8/39 RECV_AssetCount: reader65802c, consumer7d4c28."""
from dataclasses import dataclass
import struct
from .binary import Reader, Writer, PacketError, uint


@dataclass(frozen=True)
class AssetCount:
    credits: int
    gold: int
    slug: int = 0
    gold_slug: int = 0
    spectra_crystals: int = 0
    spectra_bonds: int = 0
    spectra_stock: int = 0
    unknown_u32_08: int = 0
    unknown_u32_09: int = 0
    access_level: int = 0
    optional_raw: tuple[int, int] | None = None


def encode_asset_count(value):
    w = Writer().u8(0xc8).u8(0x39)
    for name in tuple(AssetCount.__dataclass_fields__)[:10]:
        w.u32(getattr(value, name))
    w.u8(int(value.optional_raw is not None))
    if value.optional_raw is not None:
        first, second = value.optional_raw
        w.data.extend(struct.pack('<Q', uint(first, 64)))
        w.u32(second)
    return w.build()


def decode_asset_count(data):
    r = Reader(data)
    if r.u8() != 0xc8 or r.u8() != 0x39:
        raise PacketError('Expected AssetCount C8/39')
    fields = [r.u32() for _ in range(10)]
    flag = r.u8()
    if flag not in (0, 1):
        raise PacketError('Noncanonical optional flag')
    optional = (struct.unpack('<Q', r.read(8))[0], r.u32()) if flag else None
    r.finish()
    return AssetCount(*fields, optional)
