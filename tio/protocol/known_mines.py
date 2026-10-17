"""C8/3E TANetSendKnownMinesList, original RTTI and serializer658bc8."""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError


@dataclass(frozen=True)
class KnownMine:
    x: int
    y: int
    item_id: int
    team: int


def encode_known_mines(mines):
    mines = tuple(mines)
    if len(mines) > (65533 - 6) // 16:
        raise PacketError('Known mines exceed packet size')
    w = Writer().u8(0xc8).u8(0x3e).u32(len(mines))
    for mine in mines:
        w.u32(mine.x).u32(mine.y).u32(mine.item_id).u32(mine.team)
    return w.build()


def decode_known_mines(packet):
    r = Reader(packet)
    if r.u8() != 0xc8 or r.u8() != 0x3e:
        raise PacketError('Expected known mines C8/3E')
    count = r.u32()
    if len(packet) > 65533 or len(packet) != 6 + 16 * count:
        raise PacketError('Invalid known mines count or packet size')
    mines = tuple(KnownMine(r.u32(), r.u32(), r.u32(), r.u32()) for _ in range(count))
    r.finish()
    return mines
