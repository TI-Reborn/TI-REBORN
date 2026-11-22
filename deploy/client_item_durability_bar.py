"""Draw a high-contrast vertical bar from the item's actual durability words."""
from __future__ import annotations

import hashlib

import pefile

from .client_barracks_a2 import MODE
from .client_barracks_equipment import ART_STATE, BASE
from .client_barracks_skin import native_colour
from .client_equipment_batch import Code

SOURCE_SHA = '66fed4cea284df0d2fc04766650c89856f196dd4840e26c38d165eae19000741'
RESPONSIVE_PREVIEW_SHA = '9b6bfdaa7aa9b46b8735bda68f225185553a96123eca6b7a535938ded5240f52'
PUBLISHED_SHA = 'a84239f87e34b8886812d7324ae56c14794260543ed6b6d78c3e3d71bc4e49cf'
HOOK = 0xa78027
RESUME = 0xa7813f
ENTRY = 0xcbc540
BACKPACK_BAR_WIDTH, BACKPACK_BAR_INSET = 5, 2
COLOURS = {name: native_colour(argb) for name, argb in (
    ('green', 0xff58e987), ('yellow', 0xffffdc55), ('orange', 0xffff9e46), ('red', 0xffff626c),
)}


def draw_code() -> bytes:
    c = Code(ENTRY)
    c.emit('9c60'); c.base()
    c.emit('80bb'); c.word(MODE); c.emit('00'); c.branch('0f85', 'original')
    # Keep the common item's existing weapon/armour and catalogue filters.
    c.emit('8b06 80bcf88b06000000'); c.branch('0f85', 'done')
    c.emit('0fb784f818010000 83f801'); c.branch('0f84', 'durable')
    c.emit('83f809'); c.branch('0f85', 'done')
    c.label('durable')
    c.emit('0fb785b8fdffff 0fb7bdbafdffff 83ff01'); c.branch('0f86', 'done')
    c.emit('39f8 0f47c7 6bc864')
    for minimum, name, branch in ((70, 'green', '0f83'), (40, 'yellow', '0f83'),
                                  (30, 'orange', '0f87')):
        c.emit(f'6bd7{minimum:02x} 39d1'); c.branch(branch, name)
    for name in ('red', 'orange', 'yellow', 'green'):
        c.label(name)
        c.emit('be'); c.word(COLOURS[name]); c.branch('e9', 'bounds')
    c.label('bounds')
    c.emit('8b93'); c.word(ART_STATE); c.emit('85d2'); c.branch('0f84', 'stock_bounds')
    c.emit('8b8b'); c.word(ART_STATE + 0x10)
    c.emit('83fa01'); c.branch('0f84', 'warehouse_bounds')
    c.emit('83fa02'); c.branch('0f84', 'equipment_bounds')
    # The illustration bounds shift with its size. Anchor to the cell instead.
    c.emit('8b8b'); c.word(ART_STATE + 4)
    c.emit(f'83f9{BACKPACK_BAR_INSET + BACKPACK_BAR_WIDTH + 1:02x}')
    c.branch('0f8c', 'done')
    c.emit('d1f9 f7d9 038b'); c.word(ART_STATE + 0x30)
    c.emit(f'83c1{BACKPACK_BAR_INSET:02x}')
    c.emit('8b93'); c.word(ART_STATE + 0x34)
    c.emit('8b9b'); c.word(ART_STATE + 8)
    c.emit(f'50 89d8 d1f8 29c2 42 83eb02 58 6a{BACKPACK_BAR_WIDTH:02x}')
    c.branch('e9', 'draw')
    c.label('equipment_bounds')
    # The equipment overlay reserves footer space. Recover the frame size instead.
    c.emit('8b93'); c.word(ART_STATE + 0x24)
    c.emit('4a 8b9b'); c.word(ART_STATE + 8); c.branch('e9', 'standard_width')
    c.label('warehouse_bounds')
    c.emit('8b93'); c.word(ART_STATE + 0x14)
    c.emit('8b9b'); c.word(ART_STATE + 0x1c)
    c.emit('29d3'); c.branch('e9', 'standard_width')
    c.label('stock_bounds')
    c.emit('8b8d68fdffff 83e91e 8b9564fdffff 83ea10 bb20000000')
    c.label('standard_width')
    c.emit('6a06')
    c.label('draw')
    c.emit('83fb06'); c.branch('0f8c', 'discard_width')
    # Local frame: fill height, colour, x, y, track height and width.
    c.emit('53 52 51 56 0fafc3 31d2 f7f7 ba02000000 39d0 0f42c2 50 89e5')
    for inset, colour in ((0, 0xff101519), (1, 0xff37424b)):
        c.emit('ff7510 6a00 68'); c.word(native_colour(colour))
        c.emit('6802010000 8b4d14')
        c.emit('8b4508 8b550c')
        if inset:
            c.emit('40 83e902')
        c.call(0x4f2888)
    c.emit('ff7500 6a00 ff7504 6802010000 8b4d14 83e902')
    c.emit('8b4508 40 8b550c 035510 2b5500')
    c.call(0x4f2888)
    c.emit('89ec 83c414')
    c.label('discard_width')
    c.emit('83c404')
    c.label('done')
    c.emit('619d'); c.jump(RESUME)
    c.label('original')
    # Replay the overwritten stock durability comparison before its original JBE.
    c.emit('619d 6683bdb8fdffff00'); c.jump(HOOK + 8)
    return c.finish(0x200)


def patch(source: bytes) -> bytes:
    """Use the original or the redesigned durability bar according to the launcher mode."""
    digest = hashlib.sha256(source).hexdigest()
    if digest not in (SOURCE_SHA, RESPONSIVE_PREVIEW_SHA, PUBLISHED_SHA):
        raise ValueError('Expected the approved barracks candidate')
    result = bytearray(source)
    with pefile.PE(data=source, fast_load=True) as pe:
        at = pe.get_offset_from_rva(ENTRY - BASE)
        code = draw_code()
        if digest == SOURCE_SHA and any(source[at:at + len(code)]):
            raise ValueError('Durability bar code space is in use')
        result[at:at + len(code)] = code
        at = pe.get_offset_from_rva(HOOK - BASE)
        jump = Code(HOOK)
        jump.jump(ENTRY)
        result[at:at + len(jump.data)] = jump.data
    return bytes(result)
