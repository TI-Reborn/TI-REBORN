"""TI C8/2D subset confirmed by decoder64a3fc and a live client probe.

Only absent optional branches are supported. Unknown floats retain raw bits.
This updates town data; it is not evidence of entering the city UI.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError


@dataclass(frozen=True)
class TownInfoBase:
    town_id: int
    unknown_u16: int
    unknown_bytes: tuple[int, int, int, int]
    unknown_bools: tuple[int, int, int]
    unknown_float_bits: tuple[int, int, int]
    unknown_words: tuple[int, int, int]
    final_bool: int  # Enabled: native 7CFB56 writes town+4 (map visibility).


def encode_town_info(p: TownInfoBase) -> bytes:
    w = Writer().u8(0xc8).u8(0x2d).u16(p.town_id).u16(p.unknown_u16)
    groups = ((p.unknown_bytes, 4, w.u8), (p.unknown_bools, 3, w.u8),
              (p.unknown_float_bits, 3, w.u32), (p.unknown_words, 3, w.u16))
    if any(type(v) is not int or v not in (0, 1) for v in (*p.unknown_bools, p.final_bool)):
        raise PacketError('Expected boolean byte')
    for values, count, write in groups:
        if len(values) != count:
            raise PacketError('Wrong TownInfo field count')
        for value in values:
            write(value)
    w.data.extend(b'\0' * 7)  # Optional branches explicitly absent.
    return w.u8(p.final_bool).build()


def decode_town_info(data: bytes) -> TownInfoBase:
    r = Reader(data)
    if r.read(2) != b'\xc8\x2d':
        raise PacketError('Expected C8/2D')
    fields = (r.u16(), r.u16(), tuple(r.u8() for _ in range(4)),
              tuple(r.u8() for _ in range(3)), tuple(r.u32() for _ in range(3)),
              tuple(r.u16() for _ in range(3)))
    if r.read(7) != b'\0' * 7:
        raise PacketError('Optional TownInfo branches are not implemented')
    p = TownInfoBase(*fields, r.u8())
    r.finish()
    encode_town_info(p)  # Validate booleans without normalizing unknown data.
    return p


def diagnostic_town_info() -> TownInfoBase:
    """Synthetic values for source-backed zones fixture, not server rules."""
    return TownInfoBase(3, 0, (1, 3, 0, 0), (0, 0, 0), (0, 0x3f800000, 0), (0, 0, 0), 0)
