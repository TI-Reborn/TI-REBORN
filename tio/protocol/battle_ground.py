"""BattleGround35 layout from silver.dll95dd78; map value semantics unknown.

The native reader discards the first layer and named entries here, and writes
the second layer to a column-indexed grid. Other client consumers may use both.
This codec alone does not implement the battle scene initialization sequence.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError


@dataclass(frozen=True)
class GroundEntry:
    name: bytes
    unknown_u8_01: int
    unknown_u8_02: int


@dataclass(frozen=True)
class BattleGround:
    # ti.exe717eea: value 1 enables persistent explored visibility.
    # Retain the historical codec field name for existing callers/fixtures.
    unknown_u8: int
    width: int
    height: int
    first_layer: bytes
    entries: tuple[GroundEntry, ...]
    second_layer: bytes


def encode_battle_ground(ground):
    g = ground
    w = Writer().u8(0x35).u8(g.unknown_u8).u8(g.width).u8(g.height)
    if g.width == 0 or g.height == 0:
        raise PacketError('Ground dimensions must be positive for ti.exe scene reader')
    for layer in (g.first_layer, g.second_layer):
        if not isinstance(layer, bytes) or len(layer) != g.width*g.height:
            raise PacketError('Ground layer must contain width*height bytes')
    w.data.extend(g.first_layer)
    w.u16(len(g.entries))
    for entry in g.entries:
        if not isinstance(entry.name, bytes) or len(entry.name)>255 or b'\0' in entry.name:
            raise PacketError('Expected bounded NUL-free ground entry name bytes')
        w.data.extend(entry.name+b'\0')
        w.u8(entry.unknown_u8_01).u8(entry.unknown_u8_02)
    w.data.extend(g.second_layer)
    if len(w.data) > 65533:
        raise PacketError('Ground exceeds transport frame')
    return w.build()


def decode_battle_ground(packet):
    if len(packet) > 65533:
        raise PacketError('Ground exceeds transport frame')
    r = Reader(packet)
    if r.u8() != 0x35:
        raise PacketError('Expected BattleGround35')
    unknown, width, height = r.u8(), r.u8(), r.u8()
    if width == 0 or height == 0:
        raise PacketError('Ground dimensions must be positive for ti.exe scene reader')
    cells = width*height
    first = r.read(cells)
    count = r.u16()
    if count*3+cells > len(r.data)-r.offset:
        raise PacketError('Truncated ground entries/layer')
    entries = []
    for _ in range(count):
        name = bytearray()
        while (value := r.u8()) != 0:
            name.append(value)
            if len(name)>255:
                raise PacketError('Ground entry exceeds ti.exe shortstring capacity')
        entries.append(GroundEntry(bytes(name), r.u8(), r.u8()))
    second = r.read(cells)
    r.finish()
    return BattleGround(unknown, width, height, first, tuple(entries), second)
