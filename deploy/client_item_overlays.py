"""Item overlays (durability, upgrade, counts, ammo) inside A2 item cells.

The native item renderer places every overlay at a fixed offset from the
picture centre, sized for its 64x32 tile. A2 draws square 72 px tiles and
wide equipment slots, so those offsets landed inside the picture. Before the
native draw, A2 records the cell's box; each overlay coordinate is then
measured from that box. Outside A2 item scopes the native offsets remain.
"""
from __future__ import annotations

import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client_equipment_batch import Code

BASE = 0x400000
SIZE = 0xc00
THUNK = 0x40
# The box routine comes first; coordinate thunks follow it.
BOX_SIZE = 0x200
# Box fields after the item-render scope state (scope, width, height, HD).
LEFT, TOP, RIGHT, BOTTOM = 0x10, 0x14, 0x18, 0x1c
CENTRE_X, CENTRE_Y = 0x30, 0x34
HORIZONTAL = (LEFT, RIGHT, CENTRE_X)
# The 64x32 'itm_broken' wear images stay their size, centred in the cell.
WEAR_WIDTH, WEAR_HEIGHT = 64, 32
SQUARE = 72
# Equipment slots keep their caption row at the bottom (client_barracks_skin).
SLOT_INSET, SLOT_CAPTION = 4, 20
# Overlay text sits this far above the bottom edge (one native text line).
TEXT_LINE = 15
DURABILITY_HEIGHT = 28

# (site, original bytes, register, box edge, offset). Every original is
# 'mov reg,[ebp-0x298 (x) / ebp-0x29c (y)]' plus an optional 'add/sub imm8'.
SITES = (
    # Durability scale: two branches, bottom-left of the cell.
    (0xa77d28, '8b8568fdffff83e81e', 'eax', LEFT, 1),
    (0xa77d4a, '8b8564fdffff83e80e', 'eax', BOTTOM, -DURABILITY_HEIGHT-1),
    (0xa780d7, '8b8568fdffff83e81e', 'eax', LEFT, 1),
    (0xa780f9, '8b8564fdffff83e80e', 'eax', BOTTOM, -DURABILITY_HEIGHT-1),
    # Upgrade level '+N': top-left.
    (0xa783f0, '8b8564fdffff83e812', 'eax', TOP, -1),
    (0xa78439, '8b8d68fdffff83e91d', 'ecx', LEFT, 3),
    (0xa78485, '8b8564fdffff83e812', 'eax', TOP, -1),
    (0xa784cf, '8b8d68fdffff83e91d', 'ecx', LEFT, 3),
    # Right-aligned top texts: special level, stack count, armour value.
    (0xa78555, '8b8564fdffff83e812', 'eax', TOP, -1),
    (0xa7857e, '8b8d68fdffff83c11e', 'ecx', RIGHT, -2),
    (0xa7827a, '8b9568fdffff83c21e', 'edx', RIGHT, -2),
    (0xa7828b, '8b8564fdffff83e812', 'eax', TOP, -1),
    (0xa787a3, '8b9568fdffff83c21e', 'edx', RIGHT, -2),
    (0xa787b4, '8b8564fdffff83e812', 'eax', TOP, -1),
    # Weapon ammunition ('30/2') moves from mid-right to bottom-right.
    (0xa787d5, '8b8564fdffff', 'eax', BOTTOM, -TEXT_LINE),
    # Signed value line, bottom-right.
    (0xa77fb3, '8b8564fdffff83c002', 'eax', BOTTOM, -TEXT_LINE),
    (0xa77fcf, '8b8d68fdffff83c11e', 'ecx', RIGHT, -2),
    # Special mark ('SE'), bottom-left beside the durability scale.
    (0xa78954, '8b8568fdffff83e81a', 'eax', LEFT, 7),
    (0xa78963, '8b8564fdffff83c004', 'eax', BOTTOM, -TEXT_LINE),
    # Wear images (broken / 25 %) in both durability branches.
    (0xa77c15, '8b8568fdffff83e820', 'eax', CENTRE_X, -WEAR_WIDTH//2),
    (0xa77c37, '8b8564fdffff83e810', 'eax', CENTRE_Y, -WEAR_HEIGHT//2),
    (0xa77c86, '8b8568fdffff83e820', 'eax', CENTRE_X, -WEAR_WIDTH//2),
    (0xa77ca8, '8b8564fdffff83e810', 'eax', CENTRE_Y, -WEAR_HEIGHT//2),
    (0xa77dff, '8b8568fdffff83e820', 'eax', CENTRE_X, -WEAR_WIDTH//2),
    (0xa77e21, '8b8564fdffff83e810', 'eax', CENTRE_Y, -WEAR_HEIGHT//2),
    (0xa77e70, '8b8568fdffff83e820', 'eax', CENTRE_X, -WEAR_WIDTH//2),
    (0xa77e92, '8b8564fdffff83e810', 'eax', CENTRE_Y, -WEAR_HEIGHT//2),
)
# Equipment slot frame (x, y, width, height) for the upgrade frame below.
FRAME_X, FRAME_Y, FRAME_W, FRAME_H = 0x20, 0x24, 0x28, 0x2c
# ARGB for 0x67527c. Native: translucent 0x70ffff00 around 64x35.
UPGRADE_FRAME = 0xffffd23c
GRID_SCOPE, SLOT_SCOPE = 1, 2
# Warehouse grid (TGUIInventoryList item closure): the 'unusable' shade and
# the +20 upgrade frame already start at the tile corner; only their 64x32
# size changes. (site, original, replacement inside the A2 warehouse.)
GRID_FRAMES = (
    (0x99d3da, '6a206a006840404060', f'6a{SQUARE:02x}6a006840404060'),
    (0x99d3f5, 'b93e000000', 'b9'+struct.pack('<I', SQUARE).hex()),
    (0x99d48e, '6a236a006800ffff70', f'6a{SQUARE:02x}6a0068'+struct.pack('<I', UPGRADE_FRAME).hex()),
    (0x99d4a6, 'b940000000', 'b9'+struct.pack('<I', SQUARE).hex()),
)
# Equipment slot upgrade frame: the whole slot instead of the art corner.
SLOT_FRAME = (0xa4e715, '0fb7833a050000506a006800ffff706a000fb78b380500008bd783ea028bc64840', 0xa4e736)
_LOAD = {'eax': '8b83', 'ecx': '8b8b', 'edx': '8b93'}
_ADD = {'eax': '05', 'ecx': '81c1', 'edx': '81c2'}


def thunk_code(address: int, state: int, index: int) -> bytes:
    """One overlay coordinate: box-relative in A2 scopes, native otherwise."""
    from .client_equipment_batch import Code

    site, original, register, edge, offset = SITES[index]
    resume = site+len(bytes.fromhex(original))
    c = Code(address)
    c.emit('9c53'); c.base()
    c.emit('83bb'); c.word(state); c.emit('00'); c.branch('0f84', 'native')
    c.emit(_LOAD[register]); c.word(state+edge)
    c.emit(_ADD[register]); c.word(offset)
    c.emit('5b9d'); c.jump(resume)
    c.label('native'); c.emit('5b9d'); c.emit(original); c.jump(resume)
    return c.finish(THUNK)


def box_code(address: int, state: int) -> bytes:
    """Record the cell box from the native draw position (EAX=x, EDX=y).

    Warehouse (scope 1): 72 px tiles centred at (x+4, y+20). Equipment slots
    (2) and backpack cells (3) receive the native 64x32 centre of the cell's
    top-left corner, i.e. (left+32, top+16), with the cell size in the scope
    state. Slots keep their caption row; backpack tiles are squares of the
    cell height less 4, as the HD art is drawn.
    """
    from .client_equipment_batch import Code

    c = Code(address)
    c.emit('9c60'); c.base()
    c.emit('8b8b'); c.word(state); c.emit('85c9'); c.branch('0f84', 'done')
    c.emit('83f901'); c.branch('0f85', 'cell')
    c.emit('be'); c.word(SQUARE)
    c.emit('83c004 83c214'); c.branch('e9', 'square')
    c.label('cell')
    # EAX/EDX: the cell's left/top edges.
    c.emit('83e820 83ea10')
    c.emit('83f902'); c.branch('0f85', 'bag')
    c.emit('8d4801 898b'); c.word(state+FRAME_X)
    c.emit('8d4a01 898b'); c.word(state+FRAME_Y)
    c.emit('8b8b'); c.word(state+4); c.emit('83e902 898b'); c.word(state+FRAME_W)
    c.emit('8b8b'); c.word(state+8); c.emit('83e902 898b'); c.word(state+FRAME_H)
    c.emit('8d48'+f'{SLOT_INSET:02x}'+' 898b'); c.word(state+LEFT)
    c.emit('0383'); c.word(state+4); c.emit('83e8'+f'{SLOT_INSET:02x}'+' 8983'); c.word(state+RIGHT)
    c.emit('8d4a03 898b'); c.word(state+TOP)
    c.emit('0393'); c.word(state+8); c.emit('83ea'+f'{SLOT_CAPTION:02x}'+' 8993'); c.word(state+BOTTOM)
    c.branch('e9', 'centre')
    c.label('bag')
    # Centre of the cell, then a square of the height less 4 (at most 72).
    c.emit('8bb3'); c.word(state+4); c.emit('d1fe 01f0')
    c.emit('8bb3'); c.word(state+8); c.emit('d1fe 01f2')
    c.emit('8bb3'); c.word(state+8); c.emit('83ee04 83fe48'); c.branch('0f8e', 'square')
    c.emit('be'); c.word(SQUARE)
    c.label('square')
    c.emit('d1fe 89c1 29f1 898b'); c.word(state+LEFT)
    c.emit('01f0 8983'); c.word(state+RIGHT)
    c.emit('89d1 29f1 898b'); c.word(state+TOP)
    c.emit('01f2 8993'); c.word(state+BOTTOM)
    c.label('centre')
    for low, high, centre in ((LEFT, RIGHT, CENTRE_X), (TOP, BOTTOM, CENTRE_Y)):
        c.emit('8b83'); c.word(state+low); c.emit('0383'); c.word(state+high)
        c.emit('d1f8 8983'); c.word(state+centre)
    c.label('done'); c.emit('619dc3')
    return c.finish(BOX_SIZE)


def grid_frame_code(address: int, state: int, index: int) -> bytes:
    """Square shade/upgrade frame inside the A2 warehouse; native elsewhere."""
    from .client_equipment_batch import Code

    site, original, replacement = GRID_FRAMES[index]
    resume = site+len(bytes.fromhex(original))
    c = Code(address)
    c.emit('9c53'); c.base()
    c.emit('83bb'); c.word(state); c.emit(f'{GRID_SCOPE:02x}'); c.branch('0f85', 'native')
    c.emit('5b9d'); c.emit(replacement); c.jump(resume)
    c.label('native'); c.emit('5b9d'); c.emit(original); c.jump(resume)
    return c.finish(THUNK)


def slot_frame_code(address: int, state: int) -> bytes:
    """Upgrade frame around the whole equipment slot, with the native call."""
    from .client_equipment_batch import Code

    site, original, call = SLOT_FRAME
    c = Code(address)
    c.emit('53'); c.base()
    c.emit('83bb'); c.word(state); c.emit(f'{SLOT_SCOPE:02x}'); c.branch('0f85', 'native')
    # EAX keeps the module base while EBX returns to the slot's own value.
    c.emit('89d8 5b')
    c.emit('ffb0'); c.word(state+FRAME_H); c.emit('6a00 68'); c.word(UPGRADE_FRAME); c.emit('6a00')
    c.emit('8b88'); c.word(state+FRAME_W)
    c.emit('8b90'); c.word(state+FRAME_Y)
    c.emit('8b80'); c.word(state+FRAME_X)
    c.jump(call)
    c.label('native'); c.emit('5b'); c.emit(original); c.jump(call)
    return c.finish(0x80)


GRID_FRAME_AT = BOX_SIZE+len(SITES)*THUNK
SLOT_FRAME_AT = GRID_FRAME_AT+len(GRID_FRAMES)*THUNK


def payload(origin: int, state: int) -> bytes:
    result = bytearray(SIZE)
    result[0:BOX_SIZE] = box_code(BASE+origin, state)
    for index in range(len(SITES)):
        at = BOX_SIZE+index*THUNK
        result[at:at+THUNK] = thunk_code(BASE+origin+at, state, index)
    for index in range(len(GRID_FRAMES)):
        at = GRID_FRAME_AT+index*THUNK
        result[at:at+THUNK] = grid_frame_code(BASE+origin+at, state, index)
    result[SLOT_FRAME_AT:SLOT_FRAME_AT+0x80] = slot_frame_code(BASE+origin+SLOT_FRAME_AT, state)
    return bytes(result)


def box_entry(origin: int) -> int:
    return BASE+origin


def edits(origin: int) -> tuple[tuple[int, bytes, bytes], ...]:
    result = []
    targets = [(site, original, BOX_SIZE+index*THUNK) for index, (site, original, *_) in enumerate(SITES)]
    targets += [(site, original, GRID_FRAME_AT+index*THUNK) for index, (site, original, _) in enumerate(GRID_FRAMES)]
    targets.append((SLOT_FRAME[0], SLOT_FRAME[1], SLOT_FRAME_AT))
    for site, original, offset in targets:
        old = bytes.fromhex(original)
        new = b'\xe9'+struct.pack('<i', BASE+origin+offset-site-5)
        result.append((site, old, new.ljust(len(old), b'\x90')))
    return tuple(result)
