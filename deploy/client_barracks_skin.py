"""Native drawing of the owner's A2 panels, captions and backpack cell frames.

Geometry and item rules remain owned by the layout and native controls. This
module emits presentation code only; it never changes files or live processes.
"""
from __future__ import annotations

import math
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client_equipment_batch import Code

BASE = 0x400000
SIZE = 0x10000
# Run table of the holographic deck, after the slot captions.
PLATFORM = 0xd000
Expr = int | tuple[str, int, int]
CAPTIONS = ('ЭКИПИРОВКА', 'РЮКЗАК — К БОЮ', 'Голова', 'Тело', 'Ноги',
            'Основное оружие', 'Второе оружие', 'Спецслот', 'СКЛАД', '/', '★')


def native_colour(argb: int) -> int:
    """TI uses packed ABGR colours for its immediate GUI primitives."""
    return (argb & 0xff00ff00) | ((argb & 0xff) << 16) | ((argb >> 16) & 0xff)


def caption_literal(text: str) -> bytes:
    """Silver retains the string; TI's font callback reads a byte-count length."""
    raw = text.encode('utf-16le')
    return struct.pack('<HHiI',1200,2,-1,len(raw)) + raw + b'\0\0'


def _value(c: Code, value: Expr, register: str) -> None:
    from .client_barracks_a2 import _calculate

    _calculate(c, value)
    if register != 'edx':
        c.emit({'eax': '89d0', 'ecx': '89d1'}[register])


def _rectangle(c: Code, rect: tuple[Expr, ...], colour: int) -> None:
    x, y, width, height = rect
    _value(c, height, 'edx'); c.emit('52 6a00 68'); c.word(native_colour(colour))
    c.emit('6802010000')
    _value(c, width, 'ecx')
    _value(c, x, 'eax'); c.emit('0345fc')
    _value(c, y, 'edx'); c.emit('0355f8')
    c.call(0x4f2888)


def _text(c: Code, origin: int, index: int, x: Expr, y: Expr,
          colour: int = 0xffece5b8) -> None:
    c.emit('68'); c.word(native_colour(colour))
    # Font enum 5 refers to a legacy font absent from the published adapter.
    # Native Nice (3) and Font1 (0) both have the current Cyrillic atlases.
    c.emit('6a'+('03' if index in (0,1,8) else '00')+' 6a00')
    _value(c, y, 'ecx'); c.emit('034df8')
    _value(c, x, 'edx'); c.emit('0355fc 8d83')
    c.word(origin+0xe000+index*0x100+12)
    c.call(0x67571c)


def _panel(c: Code, x: Expr, width: Expr, *, stage: bool = False, top: int=112) -> None:
    from .client_barracks_a2 import _relative

    height: Expr = ('h', 1, -top-12)
    _rectangle(c, (x, top, width, height), 0xff3a4148)
    _rectangle(c, (_relative(x, 1), top+1, _relative(width, -2), ('h',1,-top-14)),
               0xff161a1e if stage else 0xff1a1f24)
    if not stage:
        _rectangle(c, (x, top, width, 1), 0xffc87a22)


def _brackets(c: Code, x: Expr, width: int, top: int) -> None:
    """Amber corner brackets: the squad terminal frames its readouts."""
    from .client_barracks_a2 import _relative

    arm, thick = 16, 2
    bottom: Expr = ('h', 1, -12-thick)
    for corner in (x, _relative(x, width-arm)):
        _rectangle(c, (corner, top, arm, thick), 0xffe8891f)
        _rectangle(c, (corner, bottom, arm, thick), 0xffe8891f)
    for edge in (x, _relative(x, width-thick)):
        _rectangle(c, (edge, top, thick, arm), 0xffe8891f)
        _rectangle(c, (edge, ('h', 1, -12-arm), thick, arm), 0xffe8891f)


def _warehouse_frame(c: Code, right: int) -> None:
    from .client_barracks_a2 import _relative
    from .client_barracks_warehouse import BAR, COLUMN_TOP, FOOTER_HEIGHT, COUNTER_HEIGHT, plan

    x: Expr = ('w', 1, -right-12)
    _rectangle(c, (x, COLUMN_TOP+BAR+3, right, 1), 0xff3a4148)
    divider = ('h', 1, -12-FOOTER_HEIGHT-COUNTER_HEIGHT-2)
    _rectangle(c, (x, divider, right, 1), 0x80c87a22)
    _rectangle(c, (x, divider, 64, 2), 0xffe8891f)
    # The native tag selector ('Метка') reads as a drop-down beside the tabs.
    tag_x, _, tag_width, _ = plan(right)['tag_frame']
    frame = _relative(x, tag_x)
    _rectangle(c, (frame, COLUMN_TOP, tag_width, BAR), 0xff3a4148)
    _rectangle(c, (_relative(frame, 1), COLUMN_TOP+1, tag_width-2, BAR-2), 0xff161a1e)
    for row, width in enumerate((9, 7, 5, 3, 1)):
        _rectangle(c, (_relative(frame, tag_width-20+row), COLUMN_TOP+11+row, width, 1), 0xffc9b77a)


def platform_runs() -> tuple[tuple[int, int, int, int, int], ...]:
    """Holographic deck under the soldier: segmented rings, ticks and a core.

    Each run is (dx, dy, width, height, ARGB) around the deck centre.
    """
    runs: list[tuple[int, int, int, int, int]] = []

    def ring(rx: int, ry: int, colour: int, gaps: int, gap_degrees: float) -> None:
        for dy in range(-ry, ry+1):
            outer = rx*math.sqrt(max(0.0, 1-(dy/ry)**2))
            inner = rx*math.sqrt(max(0.0, 1-((abs(dy)+1)/ry)**2)) if abs(dy) < ry else 0.0
            start, stop = round(inner), round(outer)
            width = max(1, stop-start)
            for sign in (-1, 1):
                x = start if sign > 0 else -start-width
                angle = math.degrees(math.atan2(dy*rx/ry, (start+width/2)*sign)) % 360
                if gaps and (angle % (360/gaps)) < gap_degrees:
                    continue
                runs.append((x, dy, width, 1, colour))

    for dy in range(-10, 11):
        span = round(110*math.sqrt(max(0.0, 1-(dy/11)**2)))
        runs.append((-span, dy, 2*span, 1, 0x22e8891f))
    ring(212, 25, 0x90c87a22, 12, 7)
    ring(160, 19, 0xe0e8891f, 4, 10)
    ring(108, 12, 0x80f0b060, 0, 0)
    for dx in (-236, 228):
        runs.append((dx, 0, 8, 1, 0xa0e8891f))
    for dy in (-31, 30):
        runs.append((-1, dy, 3, 1, 0xa0e8891f))
    runs.append((-34, -1, 68, 2, 0xd0f0b060))
    return tuple(runs)


def _platform(c: Code, centre: int, table: int, count: int) -> None:
    """Draw the precomputed run table in a loop; ESI/EDI stay intact."""
    _value(c, ('w', 2, centre), 'edx'); c.emit('8955ec')
    _value(c, ('h', 1, -104), 'edx'); c.emit('8955e8')
    c.emit('56 57 8db3'); c.word(table); c.emit('bf'); c.word(count)
    loop = f'platform_{len(c.data)}'
    c.label(loop)
    c.emit('0fb74606 50 6a00 ff7608 6802010000 0fb74e04')
    c.emit('0fbf06 0345ec 0345fc 0fbf5602 0355e8 0355f8')
    c.call(0x4f2888)
    c.emit('83c60c 4f'); c.branch('0f85', loop)
    c.emit('5f 5e')


def _design(c: Code, origin: int, left: int, right: int) -> None:
    from .client_barracks_a2 import TABLE, bag_cells, equipment_slots
    from .client_barracks_warehouse import COLUMN_TOP

    _panel(c, 12, left)
    _panel(c, left+26, ('w',1,-left-right-50), stage=True)
    _panel(c, ('w',1,-right-12), right, top=COLUMN_TOP)
    # Warehouse chrome only while the warehouse page is the visible tab.
    skip = f'warehouse_frame_{right}'
    c.emit('8b83'); c.word(TABLE-BASE); c.emit('85c0'); c.branch('0f84', skip)
    c.emit('80784900'); c.branch('0f84', skip)
    _warehouse_frame(c, right)
    c.label(skip)
    for x, width in ((12, left), (('w',1,-right-12), right)):
        _brackets(c, x, width, 112)
    _text(c,origin,0,30,130)
    _text(c,origin,1,30,428 if left==430 else 340)
    device=equipment_slots(left)[5]
    _rectangle(c,(12+device.x,112+device.y,device.width,device.height),0xff233e50)
    _rectangle(c,(13+device.x,113+device.y,device.width-2,device.height-2),0xff13202a)
    _text(c,origin,7,left-98,112+device.y+device.height-18,0xff78a6c0)
    for cell in bag_cells(left):
        _rectangle(c,(12+cell.x,112+cell.y,cell.width,cell.height),0xff30383c)
        _rectangle(c,(13+cell.x,113+cell.y,cell.width-2,cell.height-2),0xff14191d)
    # The soldier stands on a holographic deck; HP lives on the roster card.
    _platform(c,(left-right)//2,origin+PLATFORM,len(platform_runs()))


def payload(origin: int, layout_state: int) -> bytes:
    from .client_equipment_batch import Code

    c=Code(BASE+origin)
    c.emit('55 89e5 81ec00010000 9c60'); c.base()
    c.emit('83bb'); c.word(layout_state); c.emit('01')
    c.branch('0f85','done')
    c.emit('8b44241c 8b93'); c.word(0xac4bdc-BASE)
    c.emit('85d2'); c.branch('0f84','done')
    c.emit('8b724c 85f6'); c.branch('0f84','done')
    c.emit('8b484c 39f1'); c.branch('0f85','done')
    # A root render-area before all content panels is the single skin owner.
    c.emit('8b562c 85d2'); c.branch('0f84','done')
    c.emit('837a0803'); c.branch('0f8e','done')
    c.emit('8b5204 39420c'); c.branch('0f85','done')
    c.emit('89f0'); c.call(0xa4211c); c.emit('8945fc')
    c.emit('89f0'); c.call(0xa42140); c.emit('8945f8')
    c.emit('817e3840060000'); c.branch('0f8c','compact')
    c.emit('8345fc26 8345f806')
    _design(c,origin,430,554); c.branch('e9','done')
    c.label('compact'); _design(c,origin,330,430)
    c.label('done'); c.emit('619d 89ec5d'); c.jump(0xa4d724)
    result=bytearray(SIZE); result[:0xc000]=c.finish(0xc000)
    for index,caption in enumerate(CAPTIONS):
        at=0xe000+index*0x100
        raw=caption_literal(caption)
        result[at:at+len(raw)]=raw
    result[0xc000:0xd000] = _slot_captions(origin,layout_state)
    table = b''.join(struct.pack('<hhHHI', dx, dy, width, height, native_colour(colour))
                     for dx, dy, width, height, colour in platform_runs())
    if len(table) > 0x1000:
        raise ValueError('Platform runs exceed their table')
    result[PLATFORM:PLATFORM+len(table)] = table
    return bytes(result)


def _slot_captions(origin: int, layout_state: int) -> bytes:
    from .client_equipment_batch import Code

    c=Code(BASE+origin+0xc000)
    c.emit('55 89e5 83ec08 9c60 89c6');c.base()
    c.emit('83bb');c.word(layout_state);c.emit('01');c.branch('0f85','done')
    c.emit('8b464c 3b83');c.word(0xad10a0-BASE);c.branch('0f85','done')
    c.emit('8b402c 85c0');c.branch('0f84','done')
    c.emit('8b4004 85c0');c.branch('0f84','done')
    for index,caption in ((8,2),(10,3),(12,4),(14,5),(16,6)):
        c.emit('39b0');c.word(index*4);c.branch('0f84',f'caption_{caption}')
    c.branch('e9','done')
    for caption in (2,3,4,5,6):
        c.label(f'caption_{caption}')
        c.emit('89f0');c.call(0xa4211c);c.emit('8945fc')
        c.emit('89f0');c.call(0xa42140);c.emit('8945f8')
        _text(c,origin,caption,('w',1,-(100 if caption>=5 else 42)),('h',1,-18),0xff92a889)
        c.branch('e9','done')
    c.label('done');c.emit('619d 89ec5dc3')
    return c.finish(0x1000)


def edits(origin: int) -> tuple[tuple[int, bytes, bytes], ...]:
    return ((0xa2c210,struct.pack('<I',0xa4d724),struct.pack('<I',BASE+origin)),)
