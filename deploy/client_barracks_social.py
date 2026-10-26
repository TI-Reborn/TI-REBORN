"""Place native clan and alliance windows inside the A2 social column."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client_equipment_batch import Code

BASE = 0x400000
SIZE = 0x1800
NAMES = ('window_clans', 'window_clans_switch', 'window_alliance_switch')


def payload(origin: int, layout_state: int) -> bytes:
    from .client_barracks_a2 import HEADER, _calculate, _fields, _global, taller_column
    from .client_barracks_warehouse import COLUMN_TOP
    from .client_equipment_batch import Code

    c = Code(BASE+origin)
    c.emit('9c60 89c7')
    c.base()
    c.emit('83bb'); c.word(layout_state); c.emit('01')
    c.branch('0f85', 'done')
    _global(c, HEADER, 'done')
    c.emit('8b704c 807e4900'); c.branch('0f84', 'done')
    for index, name in enumerate(NAMES):
        c.emit('8b4768 8d93'); c.word(origin+0x1700+index*0x40)
        c.emit('b9'); c.word(len(name))
        c.call(0xc2be00)
        c.emit('85c0'); c.branch('0f85', f'window_{index}')
    c.branch('e9', 'done')

    def place(path: tuple[int, ...], rect: tuple) -> None:
        skip = f'skip_{len(c.data)}'
        c.emit('89f8')
        for child in path:
            c.emit('8b502c 85d2'); c.branch('0f84', skip)
            c.emit('817a08'); c.word(child); c.branch('0f8e', skip)
            c.emit('8b5204 8b82'); c.word(child*4)
            c.emit('85c0'); c.branch('0f84', skip)
        _fields(c, tuple(taller_column(value) for value in rect))
        c.label(skip)

    for index in range(len(NAMES)):
        c.label(f'window_{index}')
        c.emit('817e3840060000'); c.branch('0f8c', f'compact_{index}')
        for width, inset in ((554, 38), (430, 0)):
            if width == 430:
                c.label(f'compact_{index}')
            relative_x = 198 if index == 0 else 0
            panel_width = width-198 if index == 0 else 190 if index == 1 else width
            place((), (('w', 1, -width-12+inset+relative_x),
                       COLUMN_TOP+(6 if inset else 0), panel_width, ('h', 1, -198)))
            c.emit('8b5630 015730 8b5634 015734')
            if index == 0:
                place((1,), (panel_width-32, 8, 24, 24))
                place((2,), (8, 20, panel_width-16, 16))
                place((3,), (8, 40, panel_width-16, ('h', 1, -246)))
            elif index == 1:
                for child in range(2, 10):
                    place((child,), (8, 64+(child-2)*32, 174, 25))
            else:
                for child in range(1, 9):
                    place((child,), (12, 110, width-24, 25))
                place((9,), (12, 184, width-24, 62))
                place((10,), (12, 148, width-24, 16))
                place((11,), (12, 300, width-24, ('h', 1, -506)))
                place((12,), (12, 282, width-24, 16))
            c.branch('e9', 'done')
    c.label('done'); c.emit('619dc3')
    result = bytearray(c.finish(SIZE))
    if len(c.data) > 0x1700:
        raise ValueError('Social layout overlaps its window names')
    for index, name in enumerate(NAMES):
        raw = name.encode('utf-16le')+b'\0\0'
        start = 0x1700+index*0x40
        result[start:start+len(raw)] = raw
    return bytes(result)
