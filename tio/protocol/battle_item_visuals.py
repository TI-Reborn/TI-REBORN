"""F7/v1: explicit emulator-only recipient-visible item cell snapshot.

This is an extension, not a reconstructed original protocol. No actor, owner,
instance, hidden area centre or client-selected duration travels in it.
"""
from .binary import Reader, Writer, PacketError

OPCODE = 0xf7
VERSION = 1
SMOKE, FLARE, RECON, FIRE, LIGHT = 1, 2, 3, 4, 5
MAX_CELLS = 4096


def encode_item_visuals(cells):
    cells = tuple(cells)
    if len(cells) > MAX_CELLS or len(set((x, y) for x, y, _ in cells)) != len(cells):
        raise PacketError('Invalid item visual cell count or duplicate cell')
    writer = Writer().u8(OPCODE).u8(VERSION).u16(len(cells))
    for x, y, kind in cells:
        if type(x) is not int or type(y) is not int or not 0 <= x < 255 or not 0 <= y < 255 or type(kind) is not int or kind not in (SMOKE, FLARE, RECON, FIRE, LIGHT):
            raise PacketError('Invalid item visual cell')
        writer.u8(x).u8(y).u8(kind)
    return writer.build()


def decode_item_visuals(packet):
    reader = Reader(packet)
    if reader.u8() != OPCODE or reader.u8() != VERSION:
        raise PacketError('Unsupported item visual snapshot')
    count = reader.u16()
    if count > MAX_CELLS: raise PacketError('Item visual snapshot exceeds limit')
    cells = tuple((reader.u8(), reader.u8(), reader.u8()) for _ in range(count))
    reader.finish()
    encode_item_visuals(cells)
    return cells
