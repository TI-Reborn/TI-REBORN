"""Classic clan rating wire ABI, original Silver 6e70e0 / 6e6ef0.

Selector0 is ordinary influence, selector1 is TrueSkill; kind0/1/2 are
positions1..100/101..200/201..300 (nativeGUI842558/842588/8425b8).
The fifth numeric field is the active weekly assault place (1..20, else0),
proven by original row+0x220 and6e7a48 badge rendering. Its legacy Python name
is retained for callers. The sixth numeric field remains explicitly unknown.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError


def _cstring(w, value):
    if not isinstance(value, bytes) or b'\0' in value or len(value) > 255:
        raise PacketError('Expected at most 255 non-NUL encoded bytes')
    w.data.extend(value + b'\0')


@dataclass(frozen=True)
class ClanRating:
    id: int
    name: bytes
    leader: bytes
    members: int
    capacity: int
    level: int
    influence: int
    rating: int = 0
    crest_id: int = 0
    alliance_crest_id: int = 0
    unknown_u32_3: int = 0
    unknown_u32_4: int = 0


def decode_request(data: bytes) -> tuple[int, int]:
    r = Reader(data)
    if r.u8() != 0x82:
        raise PacketError('Expected clan rating request 82')
    result = r.u8(), r.u8()
    if result[0] not in (0,1,2) or result[1] not in (0,1):
        raise PacketError('Unsupported clan rating page or selector')
    r.finish()
    return result


def encode_request(kind: int, selector: int) -> bytes:
    result = Writer().u8(0x82).u8(kind).u8(selector).build()
    decode_request(result)
    return result


def encode_ratings(kind: int, selector: int, rows) -> bytes:
    rows = tuple(rows)
    encode_request(kind, selector)
    w = Writer().u8(0x83).u8(kind).u8(selector).u32(len(rows))
    for row in rows:
        if isinstance(row, dict):
            row = ClanRating(**row)
        w.u32(row.id)
        _cstring(w, row.name)
        _cstring(w, row.leader)
        w.u16(row.members).u16(row.capacity).u8(row.level)
        for value in (row.crest_id, row.influence, row.rating,
                      row.alliance_crest_id, row.unknown_u32_3, row.unknown_u32_4):
            w.u32(value)
    return w.build()
