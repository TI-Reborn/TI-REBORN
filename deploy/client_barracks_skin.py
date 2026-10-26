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


def _design(c: Code, origin: int, left: int, right: int) -> None:
    from .client_barracks_a2 import bag_cells, equipment_slots

    _panel(c, 12, left)
    _panel(c, left+26, ('w',1,-left-right-50), stage=True)
    _panel(c, ('w',1,-right-12), right, top=186)
    _text(c,origin,0,30,130)
    _text(c,origin,1,30,428 if left==430 else 340)
    device=equipment_slots(left)[5]
    _rectangle(c,(12+device.x,112+device.y,device.width,device.height),0xff233e50)
    _rectangle(c,(13+device.x,113+device.y,device.width-2,device.height-2),0xff13202a)
    _text(c,origin,7,left-98,112+device.y+device.height-18,0xff78a6c0)
    for cell in bag_cells(left):
        _rectangle(c,(12+cell.x,112+cell.y,cell.width,cell.height),0xff30383c)
        _rectangle(c,(13+cell.x,113+cell.y,cell.width-2,cell.height-2),0xff14191d)
    # Warm elliptical platform. Native 1-pixel strips keep the panel scalable
    # without an image atlas or changes to the actor's model/materials.
    centre: Expr = ('w',2,(left-right)//2)
    for dy in range(-22,23):
        span=round(195*math.sqrt(max(0,1-(dy/23)**2)))
        _rectangle(c,(('w',2,centre[2]-span),('h',1,-106+dy),span*2,1),0x1cc87a22)
        for edge in (centre[2]-span, centre[2]+span-1):
            _rectangle(c,(('w',2,edge),('h',1,-106+dy),1,1),0x8cc87a22)
    _hp(c,origin,centre[2],str(left))


def _hp(c: Code, origin: int, centre: int, suffix: str) -> None:
    done=f'hp_done_{suffix}'
    _rectangle(c,(('w',2,centre-180),('h',1,-60),360,22),0xff14181b)
    c.emit('8b83');c.word(0xac64b4-BASE);c.emit('85c0');c.branch('0f84',done)
    c.emit('8b00 83f820');c.branch('0f83',done)
    c.emit('8b93');c.word(0xac618c-BASE);c.emit('85d2');c.branch('0f84',done)
    c.emit('8b3c82 85ff');c.branch('0f84',done)
    c.emit('897df4 0fb78f08600000 85c9');c.branch('0f84',done)
    c.emit('0fb78706600000 3bc1');c.branch('0f86',done+'_bounded')
    c.emit('89c8');c.label(done+'_bounded')
    c.emit('69c068010000 31d2 f7f1 8945f0 6a16 6a00 6852665cff 6802010000 8b4df0')
    _value(c,('w',2,centre-180),'eax');c.emit('0345fc')
    _value(c,('h',1,-60),'edx');c.emit('0355f8');c.call(0x4f2888)
    for offset,x in ((0x6006,centre-30),(0x6008,centre+20)):
        c.emit('8b7df4 0fb787');c.word(offset)
        c.emit('8d95a0ffffff');c.call(BASE+origin+0x10000+0x3000)
        c.emit('68ece5b8ff 6a00 6a00')
        _value(c,('w',2,x),'edx');c.emit('0355fc')
        _value(c,('h',1,-56),'ecx');c.emit('034df8')
        # _value uses EDX, so set X after calculating Y.
        _value(c,('w',2,x),'edx');c.emit('0355fc')
        c.call(0x67571c)
    _text(c,origin,9,('w',2,centre+4),('h',1,-56))
    c.label(done)


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
