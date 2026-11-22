"""Inventory armour row and a reversible, native warehouse viewport."""
from __future__ import annotations

import hashlib
import struct

import pefile

from . import client_barracks_full_height as full
from . import client_warehouse_chat as chat
from .client_barracks_a2 import BASE, LEFT, LAYOUT, TABLE, TABS, _child, _global
from .client_barracks_bag import BAG
from .client_barracks_equipment import SLOT_CHILDREN, SKIN, slot_rects
from .client_barracks_skills import SKILL_TAB
from .client_barracks_skills_skin import PANEL_ENTRY, PANEL_PAINT
from .client_barracks_skin import _rectangle, _text
from .client_equipment_batch import Code
from .client_ui_scale import INVENTORY_VIEW, ITEMS_VIEW

SOURCE_SHA = '81889ed73e328b07ffe19943124ace5fc53b1ff4cc72b7acc4fed329e9b171cd'
TICK, GEAR, WAREHOUSE, RESIZE, VISIBILITY, RESTORE, PAINT, LEFT_PAINT, CLICK = (
    0xcb9800, 0xcb9900, 0xcb9d00, 0xcba000, 0xcba400, 0xcba600, 0xcba700, 0xcbac00, 0xcbb300,
)
REQUESTED, ORIGINAL_X, EXTENDED_X, PREVIEW_VISIBLE, FILTER_X = (
    0xcbb800-BASE+i*4 for i in range(5)
)
OWNERS = 0xad1098
ROOT_TAIL, ROOT_PAINT = 0xcb4f81, 0xcbbb00
GAP, ARROW_W, ARROW_H, ARROW_TOP = 24, 20, 22, 3


def _slots(width: int) -> tuple[tuple[int, int, int, int], ...]:
    wide = width == 430
    cell = (width - 60)//3
    upper = tuple((18+i*(cell+12), 42 if wide else 35, cell, 88 if wide else 66)
                  for i in range(3))
    offset = 124 if wide else 96
    lower = tuple((r.x, r.y+offset, r.width, r.height) for r in slot_rects(width, 640)[3:])
    return (*upper, *lower)


def tick_code() -> bytes:
    c = Code(TICK)
    c.call(full.REFLOW)
    c.call(GEAR)
    c.jump(WAREHOUSE)
    return c.finish(GEAR-TICK)


def gear_code() -> bytes:
    c = Code(GEAR)
    c.emit('9c60')
    _global(c, BAG, 'done')
    c.emit('89c6 8178389e010000'); c.branch('0f84', 'wide')
    c.emit('8178383a010000'); c.branch('0f85', 'done')
    c.emit('817834f7000000'); c.branch('0f85', 'done')
    c.emit('bf60000000 8d8b'); c.word(0xcbb900-BASE); c.branch('e9', 'place')
    c.label('wide')
    c.emit('81783459010000'); c.branch('0f85', 'done')
    c.emit('bf7c000000 8d8b'); c.word(0xcbba00-BASE)
    c.label('place')
    _global(c, LEFT, 'done')
    c.emit('39464c'); c.branch('0f85', 'done')
    c.emit('8b502c 85d2'); c.branch('0f84', 'done')
    c.emit('837a081a'); c.branch('0f8e', 'done')
    c.emit('8b5204 53 89d3')
    c.label('slot')
    c.emit('0fb611 81faff000000'); c.branch('0f84', 'bags')
    c.emit('8b0493 85c0'); c.branch('0f84', 'next')
    for src, dst in ((1, 0x30), (3, 0x34), (5, 0x38), (7, 0x3c)):
        c.emit(f'0fbf51{src:02x} 8950{dst:02x}')
    c.label('next')
    c.emit('83c109'); c.branch('e9', 'slot')
    c.label('bags')
    for child in (6, 7):
        c.emit(f'8b43{child*4:02x} 85c0'); c.branch('0f84', f'button_{child}')
        c.emit('017834')
        c.label(f'button_{child}')
    c.emit('8b4308 85c0'); c.branch('0f84', 'move_bag')
    c.emit('83683020')
    c.label('move_bag')
    c.emit('5b 017e34 8b563c 29fa 83fa30'); c.branch('0f8c', 'done')
    c.emit('89f0'); c.call(ITEMS_VIEW)
    _child(c, LEFT, 26, 'done')
    c.emit('8b5634 03563c 83c207 895034')
    c.label('done')
    c.emit('619dc3')
    return c.finish(WAREHOUSE-GEAR)


def warehouse_code() -> bytes:
    c = Code(WAREHOUSE)
    c.emit('9c60')
    _global(c, TABLE, 'done'); c.emit('89c6')
    c.emit('83bb'); c.word(REQUESTED); c.emit('00'); c.branch('0f84', 'narrow')
    _global(c, BAG, 'done'); c.emit('8b5038')
    _global(c, LEFT, 'done')
    c.emit(f'035030 83c2{16+GAP:02x} 8b4630 39d0')
    c.branch('0f84', 'hide'); c.branch('0f8c', 'done')
    chat._put(c, 'eax', ORIGINAL_X); chat._put(c, 'edx', EXTENDED_X)
    c.call(RESIZE)
    c.label('hide')
    c.emit('b801000000'); c.call(VISIBILITY)
    c.branch('e9', 'done')
    c.label('narrow')
    chat._get(c, 'edx', ORIGINAL_X)
    c.emit('85d2'); c.branch('0f84', 'done')
    chat._get(c, 'eax', EXTENDED_X)
    c.emit('394630'); c.branch('0f85', 'reset')
    c.call(RESIZE)
    c.label('reset')
    c.emit('31c0'); chat._put(c, 'eax', ORIGINAL_X)
    c.call(VISIBILITY)
    c.label('done')
    c.emit('619dc3')
    return c.finish(RESIZE-WAREHOUSE)


def resize_code() -> bytes:
    c = Code(RESIZE)
    c.emit('9c60 89f7 8b7730 29d6 895730 017738')
    _global(c, chat.GRID, 'children')
    c.emit('39784c'); c.branch('0f85', 'children')
    c.emit('8b5038 01f2 8b483c'); c.call(INVENTORY_VIEW)
    c.label('children')
    _global(c, OWNERS, 'filter')
    c.emit('8b574c 39504c'); c.branch('0f85', 'filter')
    c.emit('297030')
    c.label('filter')
    _child(c, TABLE, 6, 'footer')
    c.emit('83bb'); c.word(REQUESTED); c.emit('00'); c.branch('0f84', 'filter_restore')
    c.emit('8b5030'); chat._put(c, 'edx', FILTER_X)
    c.emit('31d2'); c.branch('e9', 'filter_place')
    c.label('filter_restore')
    chat._get(c, 'edx', FILTER_X)
    c.label('filter_place')
    c.emit('895030')
    c.label('footer')
    for child, field in ((8, 0x38), (11, 0x30), (12, 0x38),
                         (13, 0x30), (14, 0x30), (15, 0x30)):
        skip = f'child_{child}'
        _child(c, TABLE, child, skip)
        c.emit(f'0170{field:02x}')
        c.label(skip)
    c.emit('619dc3')
    return c.finish(VISIBILITY-RESIZE)


def visibility_code() -> bytes:
    c = Code(VISIBILITY)
    c.emit('9c60 89c7 6a00')
    chat._get(c, 'esi', PREVIEW_VISIBLE)
    c.emit('85ff'); c.branch('0f85', 'change')
    c.emit('85f6'); c.branch('0f84', 'done')
    c.label('change')
    for index in range(3):
        skip = f'panel_{index}'
        if index == 0:
            _child(c, LEFT, 2, skip)
        elif index == 1:
            _global(c, SKILL_TAB, skip)
            c.emit('8b404c 85c0'); c.branch('0f84', skip)
            c.emit('89c1')
            _global(c, TABLE, skip)
            c.emit('8b504c 89c8')
            c.emit('39504c'); c.branch('0f85', skip)
        else:
            _global(c, TABS, skip)
        c.emit('85ff'); c.branch('0f84', f'show_{index}')
        c.emit('85f6'); c.branch('0f85', f'hide_{index}')
        c.emit('0fb64849'); c.emit(f'c1e1{index:02x} 090c24')
        c.label(f'hide_{index}')
        c.emit('c6404900'); c.branch('e9', skip)
        c.label(f'show_{index}')
        c.emit(f'89f1 c1e9{index:02x} 80e101 884849')
        c.label(skip)
    c.emit('31c0 85ff'); c.branch('0f84', 'save')
    c.emit('85f6'); c.branch('0f85', 'done')
    c.emit('8b0424 0d00010000')
    c.label('save')
    chat._put(c, 'eax', PREVIEW_VISIBLE)
    c.label('done')
    c.emit('83c404 619dc3')
    return c.finish(RESTORE-VISIBILITY)


def restore_code() -> bytes:
    c = Code(RESTORE)
    c.emit('9c60 31c0')
    chat._put(c, 'eax', REQUESTED); chat._put(c, 'eax', ORIGINAL_X)
    c.call(VISIBILITY)
    c.emit('619d')
    c.jump(LAYOUT)
    return c.finish(PAINT-RESTORE)


def paint_code(*, extra_panel: int | None = None) -> bytes:
    c = Code(PAINT)
    c.emit('9c60'); c.base()
    c.emit('83bb'); c.word(chat.ACTIVE); c.emit('00'); c.branch('0f84', 'stock')
    c.emit('8b74241c 3bb3'); c.word(LEFT-BASE); c.branch('0f84', 'left')
    if extra_panel is not None:
        c.emit('3bb3'); c.word(extra_panel); c.branch('0f84', 'skip_panel')
    c.emit('3bb3'); c.word(TABLE-BASE); c.branch('0f85', 'stock')
    c.emit('83ec08 8d6c2408 89f0'); c.call(0xa4211c); c.emit('8945fc')
    c.emit('89f0'); c.call(0xa42140); c.emit('8945f8')
    c.emit(f'836dfc{ARROW_W+2:02x} 8345f8{ARROW_TOP:02x}')
    _rectangle(c,(0,0,ARROW_W,ARROW_H),0xffa5773d)
    _rectangle(c,(1,1,ARROW_W-2,ARROW_H-2),0xff252829)
    c.emit('83bb'); c.word(ORIGINAL_X); c.emit('00'); c.branch('0f85', 'right')
    for x in range(6):
        _rectangle(c,(7+x,10-x,1,2+2*x),0xffead09a)
    c.branch('e9', 'finished')
    c.label('right')
    for x in range(6):
        _rectangle(c,(7+x,5+x,1,12-2*x),0xffead09a)
    c.label('finished')
    c.emit('83c408')
    c.label('skip_panel')
    c.emit('619dc3')
    c.label('left')
    c.emit('619d'); c.jump(LEFT_PAINT)
    c.label('stock')
    c.emit('619d'); c.jump(PANEL_ENTRY)
    return c.finish(LEFT_PAINT-PAINT)


def left_paint_code() -> bytes:
    c = Code(LEFT_PAINT)
    c.emit('9c60'); c.base()
    c.emit('8b74241c 83ec0c 8d6c240c')
    _global(c, BAG, 'done')
    c.emit('39704c'); c.branch('0f85', 'done')
    c.emit('8b4038 83c010 8945f4 89f0'); c.call(0xa4211c); c.emit('8945fc')
    c.emit('89f0'); c.call(0xa42140); c.emit('8945f8')
    # The stock skin has its original bag cells and captions baked in. This
    # inset is drawn before the live slots so their mouse handlers stay native.
    c.emit('8b463c 83e820 50'); full._fill(c,0xff1a1f24)
    c.emit('8b45fc 40 8b55f8 83c202 8b4df4 83e902'); c.call(0x4f2888)
    _text(c,SKIN,0,18,17)
    c.emit('817df4ae010000'); c.branch('0f85', 'compact')
    for width, label in ((430,'wide'),(330,'compact')):
        if label == 'compact':
            c.label(label)
        x,y,w,h = _slots(width)[-1]
        _rectangle(c,(x,y,w,h),0xff233e50)
        _rectangle(c,(x+1,y+1,w-2,h-2),0xff13202a)
        _text(c,SKIN,7,x+63,y+(h-14)//2,0xffa4c6da)
        _text(c,SKIN,1,18,446 if width==430 else 324)
        c.branch('e9', 'done')
    c.label('done')
    c.emit('83c40c 619dc3')
    return c.finish(CLICK-LEFT_PAINT)


def root_paint_code() -> bytes:
    c = Code(ROOT_PAINT)
    # Paint over the old dividers in the root skin, below the live owner tabs.
    c.emit('83bb'); c.word(ORIGINAL_X); c.emit('00'); c.branch('0f84', 'done')
    _global(c, TABLE, 'done')
    c.emit('89c6 8b564c 85d2'); c.branch('0f84', 'done')
    c.emit('8b522c 85d2'); c.branch('0f84', 'done')
    c.emit('837a0803'); c.branch('0f8e', 'done')
    c.emit('8b5204 8b44241c 39420c'); c.branch('0f85', 'done')
    c.emit('89f0'); c.call(0xa4211c); c.emit('8945fc')
    c.emit('89f0'); c.call(0xa42140); c.emit('8945f8')
    for inset, colour in ((0,0xff3a4148),(1,0xff1a1f24)):
        c.emit('8b463c')
        if inset:
            c.emit('83e802')
        c.emit('50'); full._fill(c,colour)
        c.emit('8b45fc 8b55f8 8b4e38')
        if inset:
            c.emit('40 42 83e902')
        c.call(0x4f2888)
    _child(c, TABLE, 12, 'done')
    c.emit('8b5030 83ea08 0155fc 8b4638 29d0 8945f4')
    for inset, colour in ((0,0xff3a4148),(1,0xff161a1e)):
        c.emit('6a'+f'{28-inset*2:02x}'); full._fill(c,colour)
        c.emit('8b45fc 8b55f8 8b4df4')
        if inset:
            c.emit('40 42 83e902')
        c.call(0x4f2888)
    c.emit('8b45f4 83e814 0145fc')
    for row, width in enumerate((9,7,5,3,1)):
        _rectangle(c,(row,11+row,width,1),0xffc9b77a)
    c.label('done')
    c.emit('619d89ec5d'); c.jump(0xa4d724)
    return c.finish(0x500)


def click_code() -> bytes:
    c = Code(CLICK)
    c.emit('9c60'); c.base()
    c.emit('807c241400'); c.branch('0f85', 'stock')
    c.emit('83bb'); c.word(chat.ACTIVE); c.emit('00'); c.branch('0f84', 'stock')
    c.emit('8b44241c 83b8d802000000'); c.branch('0f85', 'stock')
    _global(c, TABLE, 'stock')
    c.emit('80784900'); c.branch('0f84', 'stock')
    c.emit('89c6'); c.call(0xa4211c)
    chat._get(c, 'edx', chat.MOUSE_X-BASE)
    c.emit(f'8b12 29c2 83c2{ARROW_W+2:02x} 83fa{ARROW_W:02x}'); c.branch('0f83', 'stock')
    c.emit('89f0'); c.call(0xa42140)
    chat._get(c, 'edx', chat.MOUSE_Y-BASE)
    c.emit(f'8b12 29c2 83ea{ARROW_TOP:02x} 83fa{ARROW_H:02x}'); c.branch('0f83', 'stock')
    c.emit('83b3'); c.word(REQUESTED); c.emit('01 619d b801000000 c20400')
    c.label('stock')
    c.emit('619d'); c.jump(chat.BUTTON)
    return c.finish(0x400)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected the full-height barracks with the native outer frame')
    result = bytearray(source)
    with pefile.PE(data=source,fast_load=True) as pe:
        def write(va: int, value: bytes, *, unused: bool = False) -> None:
            at = pe.get_offset_from_rva(va-BASE)
            if unused and any(source[at:at+len(value)]):
                raise ValueError(f'Occupied warehouse code space at {va:#x}')
            result[at:at+len(value)] = value

        for entry, code in ((TICK,tick_code()),(GEAR,gear_code()),(WAREHOUSE,warehouse_code()),
                            (RESIZE,resize_code()),(VISIBILITY,visibility_code()),(RESTORE,restore_code()),
                            (PAINT,paint_code()),(LEFT_PAINT,left_paint_code()),(CLICK,click_code()),
                            (ROOT_PAINT,root_paint_code())):
            write(entry,code,unused=True)
        for width, address in ((330,0xcbb900),(430,0xcbba00)):
            slots = _slots(width)
            rows = [(child, *rect) for indices,rect in zip(SLOT_CHILDREN,slots,strict=True)
                    for child in indices]
            x,y,_,h = slots[-1]
            rows.append((25,x+14,y+(h-32)//2,32,32))
            write(address,b''.join(struct.pack('<Bhhhh',*row) for row in rows)+b'\xff',unused=True)
        write(BASE+REQUESTED,bytes(20),unused=True)
        for hook, target in ((PANEL_PAINT,PAINT),(chat.MOUSE_DOWN,CLICK),(ROOT_TAIL,ROOT_PAINT)):
            c = Code(hook)
            c.jump(target)
            write(hook,bytes(c.data))
        write(chat.FRAME,chat.frame_code(layout=TICK,restore=RESTORE))
        write(full.BAG_DRAW,full.bag_code(first_row=0))
    return bytes(result)
