"""A2 tabs and portrait arrows retain the existing native input handlers."""
from __future__ import annotations

import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client_equipment_batch import Code

BASE = 0x400000
SIZE = 0x8000
TITLES = ('Информация', 'Инвентарь', 'Почта', 'Клан', 'Альянс')
BUTTONS = ((0, 4), (1, 5), (3, 7), (5, 8), (6, 9))
ARROWS = (
    (0x8aa23f, '8d4317b920000000', '8d83cd000000b920000000'),
    (0x8aa267, '8bc383e817', '8bc32dcd000000'),
    (0x8aa2af, '8d4317b920000000', '8d83cd000000b920000000'),
    (0x8aa381, '8bc383e81783e820', '8bc32dcd00000083e820'),
)
FOOTER = (
    (0x9a8d38,'83c34b68dbefb1ff',55),
    (0x9a8e03,'83c35a6a02',60),
    (0x9a8ef3,'83c3416a02',55),
    (0x9a8fe3,'83c34b6a02',55),
    (0x9a90d9,'83c34b6a02',55),
    (0x9a91cf,'83c34b6a02',55),
)


def _footer(origin: int, layout_state: int, index: int) -> bytes:
    from .client_equipment_batch import Code

    site, original, pitch=FOOTER[index]
    c=Code(BASE+origin+0x400+index*0x100)
    c.emit('9c5053');c.base()
    c.emit('83bb');c.word(layout_state);c.emit('01');c.branch('0f85','stock')
    c.emit('8b4714 8b404c 3b83');c.word(0xad10a4-BASE)
    c.branch('0f85','stock')
    c.emit('817838ae010000');c.branch('0f85','stock')
    c.emit('5b589d');c.emit(original[:4]+f'{pitch:02x}'+original[6:])
    c.jump(site+len(bytes.fromhex(original)))
    c.label('stock');c.emit('5b589d');c.emit(original)
    c.jump(site+len(bytes.fromhex(original)))
    return c.finish(0x100)


def _arrows(origin: int, layout_state: int, index: int) -> bytes:
    from .client_equipment_batch import Code

    site, old, new = ARROWS[index]
    c = Code(BASE+origin+index*0x100)
    c.emit('9c5053'); c.base()
    c.emit('83bb'); c.word(layout_state); c.emit('01')
    c.branch('0f85', 'stock')
    c.emit('8b470c 8b404c 3b83'); c.word(0xad10a0-BASE)
    c.branch('0f85', 'stock')
    c.emit('5b589d'); c.emit(new); c.jump(site+len(bytes.fromhex(old)))
    c.label('stock'); c.emit('5b589d'); c.emit(old)
    c.jump(site+len(bytes.fromhex(old)))
    return c.finish(0x100)


def _icon(c: Code, row: int) -> None:
    """Crop the existing HD symbol from its atlas, leaving its old frame."""
    # Those eager resources belong to the published density adapter, which
    # also owns device reset. No texture allocation or new asset is required.
    c.emit('8b83'); c.word(0x848000+row*0x80+0x34)
    c.emit('85c0'); c.branch('0f84', f'no_icon_{row}')
    c.emit('6a40 6a36 8b5638 83ea20 d1fa 0355fc 52')
    c.emit('8b55f8 83c208 52 6a20 6a1b 6aff 6a00')
    c.emit('ba38000000 b904000000 bf10067400 ffd7')
    c.label(f'no_icon_{row}')


def _tabs(origin: int, layout_state: int) -> bytes:
    from .client_barracks_skin import _rectangle, native_colour
    from .client_equipment_batch import Code

    c = Code(BASE+origin+0x2000)
    c.emit('55 89e5 83ec40 9c60 89c6'); c.base()
    c.emit('83bb'); c.word(layout_state); c.emit('01')
    c.branch('0f85', 'stock')
    c.emit('8b464c 3b83'); c.word(0xad1094-BASE)
    c.branch('0f85', 'stock')
    c.emit('8b402c 85c0'); c.branch('0f84', 'stock')
    c.emit('8b4004 85c0'); c.branch('0f84', 'stock')
    for index, (child, _) in enumerate(BUTTONS):
        c.emit('39b0'); c.word(child*4)
        c.branch('0f84', f'tab_{index}')
    c.branch('e9', 'stock')
    for index, _ in enumerate(BUTTONS):
        c.label(f'tab_{index}')
        c.emit('c745f4'); c.word(index); c.branch('e9', 'paint')
    c.label('paint')
    c.emit('807e4900'); c.branch('0f84', 'done')
    c.emit('89f0'); c.call(0xa4211c); c.emit('8945fc')
    c.emit('89f0'); c.call(0xa42140); c.emit('8945f8')
    _rectangle(c, (0, 0, ('w',1,0), 64), 0xff6d5632)
    c.emit('80bec902000000'); c.branch('0f85', 'active')
    c.emit('80be8002000000'); c.branch('0f84', 'inactive')
    c.label('active')
    _rectangle(c, (0, 0, ('w',1,0), 64), 0xffe8891f)
    c.label('inactive')
    for y in range(2, 62):
        fraction=(y-2)/59
        channels=tuple(round(a+(b-a)*fraction) for a,b in
                       ((0x20,0x16),(0x26,0x1a),(0x2c,0x1e)))
        colour=0xff000000+(channels[0]<<16)+(channels[1]<<8)+channels[2]
        _rectangle(c, (2, y, ('w',1,-4), 1), colour)
    for index, (_, row) in enumerate(BUTTONS):
        c.emit('837df4'+f'{index:02x}'); c.branch('0f85', f'next_{index}')
        _icon(c, row)
        c.emit('68'); c.word(native_colour(0xffc9b77a)); c.emit('6a00 6a00')
        c.emit('8b5638 81ea'); c.word(len(TITLES[index])*7)
        c.emit('d1fa 0355fc 8b4df8 83c12e 8d83')
        c.word(origin+0x6000+index*0x100+12)
        c.call(0x67571c)
        c.branch('e9', 'done')
        c.label(f'next_{index}')
    c.label('done'); c.emit('619d 89ec5dc3')
    c.label('stock'); c.emit('619d 89ec5d'); c.jump(0xa45400)
    return c.finish(0x4000)


def _warehouse_caption(origin: int, layout_state: int) -> bytes:
    from .client_equipment_batch import Code

    c=Code(BASE+origin+0x1000)
    c.emit('9c60'); c.base()
    c.emit('83bb'); c.word(layout_state); c.emit('01')
    c.branch('0f85','stock')
    c.emit('8bb3'); c.word(0xad10a4-BASE)
    c.emit('85f6'); c.branch('0f84','stock')
    c.emit('807e4900'); c.branch('0f84','stock')
    c.emit('89f0'); c.call(0xa4211c)
    c.emit('05a0000000 89442414 89f0'); c.call(0xa42140)
    c.emit('83c00e 89442418')
    c.label('stock'); c.emit('619d'); c.jump(0x67571c)
    return c.finish(0x400)


def payload(origin: int, layout_state: int) -> bytes:
    from .client_barracks_skin import caption_literal
    from .client_equipment_batch import Code

    result = bytearray(SIZE)
    for index in range(len(ARROWS)):
        offset=index*0x100
        result[offset:offset+0x100] = _arrows(origin, layout_state, index)
    for index in range(len(FOOTER)):
        offset=0x400+index*0x100
        result[offset:offset+0x100] = _footer(origin, layout_state, index)
    result[0x2000:0x6000] = _tabs(origin, layout_state)
    result[0x1000:0x1400] = _warehouse_caption(origin, layout_state)
    counter = Code(BASE+origin+0x1400)
    counter.emit('9c53'); counter.base()
    counter.emit('83bb'); counter.word(layout_state); counter.emit('01')
    counter.branch('0f85', 'stock')
    counter.emit('b8c8000000')
    counter.label('stock'); counter.emit('5b9d 8945ec85c0')
    counter.jump(0xc2071c)
    result[0x1400:0x1500] = counter.finish(0x100)
    for index, title in enumerate(TITLES):
        literal=caption_literal(title)
        offset=0x6000+index*0x100
        result[offset:offset+len(literal)] = literal
    return bytes(result)


def edits(origin: int) -> tuple[tuple[int, bytes, bytes], ...]:
    result = []
    for index, (site, original, _) in enumerate(ARROWS):
        before = bytes.fromhex(original)
        after = b'\xe9'+struct.pack('<i', BASE+origin+index*0x100-site-5)
        result.append((site, before, after.ljust(len(before), b'\x90')))
    result.append((0xa2ed3c, struct.pack('<I', 0xa45400),
                   struct.pack('<I', BASE+origin+0x2000)))
    site=0xc2087e
    result.append((site,b'\xe8'+struct.pack('<i',0x67571c-site-5),
                   b'\xe8'+struct.pack('<i',BASE+origin+0x1000-site-5)))
    site = 0xc20717
    result.append((site, bytes.fromhex('8945ec85c0'),
                   b'\xe9'+struct.pack('<i',BASE+origin+0x1400-site-5)))
    for index,(site,original,_) in enumerate(FOOTER):
        old=bytes.fromhex(original)
        new=b'\xe9'+struct.pack('<i',BASE+origin+0x400+index*0x100-site-5)
        result.append((site,old,new.ljust(len(old),b'\x90')))
    return tuple(result)
