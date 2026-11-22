"""Place the fighter beside the stacked native skills and abilities panels."""
from __future__ import annotations

import hashlib

import pefile

from . import client_barracks_skills_skin as skin
from . import client_barracks_wide_warehouse as wide
from . import client_warehouse_chat as chat
from .client_barracks_a2 import BASE, DRAW as STOCK_MODEL_DRAW, INFO, LEFT, TABLE, TABS, _child, _global
from .client_barracks_bag import BAG
from .client_barracks_skills import ENTRY as SKILLS_ENTRY, REPARENT, layout_code as skills_layout_code
from .client_barracks_skin import _rectangle, native_colour
from .client_equipment_batch import Code

SOURCE_SHA = '041ff09237d4fcc72839e0843e8c3d9bd837015f6d1e0a372749ec0acd16b0be'
INFORMATION_OVERLAP_SHA = '2df974d49c980faf29ff6d84f153cebec43c5ff75ef41716931082084fea9eec'
TICK, ARRANGE, RESET, ROWS, DRAW, LEAVE = (
    0xcc1900, 0xcc1940, 0xcc1f00, 0xcc2400, 0xcc2600, 0xcc2a00,
)
PANEL, SAVED_TAB, ACTOR, MODEL, MODEL_SIZE = (0xcc2b00-BASE+i*4 for i in range(5))
DRAW_MODEL = 0xcc2c00
ABILITY_LIST, SELECTED_ACTOR = 0xac4be0, 0xac64b4
HEADER, SKILL_FOOTER, ROW, GAP = 24, 40, 28, 10
MIN_SKILL_HEIGHT = HEADER + ROW*7 + SKILL_FOOTER
MIN_ABILITY_HEIGHT = 132
COMPACT_STACK_HEIGHT = 510
SKILL_WIDTH = skin.PANEL_WIDTH
STACK_TOP_INSET = wide.ARROW_TOP + wide.ARROW_H + 8
STACK_BOTTOM_INSET = 12


def _memory(c: Code, instruction: str, value: int) -> None:
    c.emit(instruction)
    c.word(value)


def _tabs(c: Code, skip: str) -> None:
    _global(c, skin.SKILL_TAB, skip); c.emit('89c6')
    _global(c, skin.ABILITY_TAB, skip); c.emit('89c7 8b464c 85c0')
    c.branch('0f84', skip)
    c.emit('39474c'); c.branch('0f85', skip)
    c.emit('8945fc')


def _contents(c: Code, *, split: bool) -> None:
    _child(c, skin.SKILL_TAB, 0, 'ability_list')
    c.emit('8a9680020000 885049')
    if split:
        c.emit(f'8b563c 83ea{HEADER:02x} 89503c 895040')
        c.emit(f'50 8d42{(-SKILL_FOOTER)&255:02x} 31d2 b907000000 f7f1 89c1 58')
    else:
        _memory(c, 'c7403c', 226)
        _memory(c, 'c74040', 226)
        _memory(c, 'b9', 32)
    c.call(ROWS)
    c.label('ability_list')
    _global(c, ABILITY_LIST, 'done')
    c.emit('39784c'); c.branch('0f85', 'done')
    c.emit('8a9780020000 885049')
    if split:
        c.emit('8b4f3c 83e940')
    else:
        _memory(c, 'b9', 196)
    c.emit('39483c')
    c.branch('0f84', 'learn')
    c.emit('89483c 894840')
    c.call(0x8afe50)
    c.label('learn')
    _child(c, skin.ABILITY_TAB, 1, 'done')
    c.emit('8a9780020000 885049')
    if split:
        c.emit('8b573c 83ea1e 895034')
    else:
        _memory(c, 'c74034', 230)


def arrange_code(*, adopt_information: bool = False) -> bytes:
    c = Code(ARRANGE)
    c.emit('9c60 83ec24 8d6c2424')
    _tabs(c, 'done')
    _global(c, TABLE, 'done')
    c.emit('8b504c 8b4dfc 39514c')
    if adopt_information:
        # Compact layouts can leave both skills tabs inside Information.
        c.branch('0f84', 'parent_ready')
        c.emit('8b494c 85c9'); c.branch('0f84', 'done')
        c.emit('3b8b'); c.word(INFO-BASE); c.branch('0f85', 'done')
        c.emit('39514c'); c.branch('0f85', 'done')
        c.label('parent_ready')
    else:
        c.branch('0f85', 'done')
    c.emit('8b4030 85d2'); c.branch('0f84', 'done')
    chat._get(c, 'ecx', wide.ORIGINAL_X)
    c.emit('85c9 0f45c1 8945f0')
    _global(c, LEFT, 'done')
    c.emit('39504c'); c.branch('0f85', 'done')
    c.emit('8945f8')
    _global(c, BAG, 'done')
    c.emit('8b4df8 39484c'); c.branch('0f85', 'done')
    c.emit('8b5038 83c21c 035130 8955f4')
    _global(c, TABS, 'done')
    # Anchor the stack between the warehouse header and the bottom buttons.
    c.emit(f'8b4034 8945e8 8b4df8 8b5134 83c2{STACK_TOP_INSET:02x} 8955ec 29d0')
    c.emit(f'83e8{GAP+STACK_BOTTOM_INSET:02x}')
    _memory(c, '3d', MIN_SKILL_HEIGHT+MIN_ABILITY_HEIGHT)
    c.branch('0f8c', 'too_small')
    # Broaden the skill rows on taller canvases and give the rest to the list.
    c.emit('50 31d2 2d'); c.word(COMPACT_STACK_HEIGHT)
    c.emit(f'0f48c2 b912000000 f7f1 83c0{ROW:02x} ba28000000 39d0 0f4fc2')
    c.emit(f'6bc007 83c0{HEADER+SKILL_FOOTER:02x} 8945dc 59 29c1 894de0')
    _memory(c, '8b45f0 2d', SKILL_WIDTH+12)
    c.emit('8945e4 2b45f4 83e80c 83f870'); c.branch('0f8c', 'too_small')
    _child(c, LEFT, 2, 'done')
    if adopt_information:
        c.emit('50 56 8b75fc 8b55f8 8b524c')
        c.call(REPARENT)
        c.emit('85c0 5e 58'); c.branch('0f84', 'done')
    chat._put(c, 'eax', MODEL)
    c.emit('8b55e4 2b55f4 83ea0c 895038')
    c.emit('8b4df8 8b55f4 2b5130 895030 c740340c000000')
    c.emit('8b55e8 2b5134 83ea26 89503c 8990f4020000')
    # Keep the hit area in the left column while enlarging the rendered quad.
    c.emit('8b4838 01c9 39d1 0f4fca')
    _memory(c, 'ba', 590)
    c.emit('39d1 0f4fca'); chat._put(c, 'ecx', MODEL_SIZE)
    c.emit('8b4df8')
    c.emit('8b503c d1fa 035034 035134 8b4de8 83c10c 29d1 8988f0020000')

    c.emit('8b45fc 3b83'); c.word(PANEL); c.branch('0f84', 'position')
    chat._put(c, 'eax', PANEL)
    c.emit('0fb69780020000'); chat._put(c, 'edx', SAVED_TAB)
    _memory(c, 'c783', ACTOR); c.word(-1)
    c.label('position')
    c.emit('8b55e4 895030 8b55ec 895034')
    _memory(c, 'c74038', SKILL_WIDTH)
    c.emit('31d2 895634 895630 895730')
    c.emit(f'8b55dc 89563c 895640 899684020000 83c2{GAP:02x} 895734 0355e0 89503c')
    c.emit('8b55e0 89573c 895740 899784020000')
    c.emit('c6868002000001 c6878002000001 c686bc02000001 c687bc02000001')
    _contents(c, split=True)
    # Use the native tab-open refresh for each selected fighter's own list.
    _global(c, SELECTED_ACTOR, 'done')
    c.emit('8b00 85c0'); c.branch('0f88', 'done')
    c.emit('3b83'); c.word(ACTOR); c.branch('0f84', 'done')
    chat._put(c, 'eax', ACTOR)
    c.emit('8d878c020000'); c.call(0xa54964)
    c.branch('e9', 'done')
    c.label('too_small')
    chat._get(c, 'eax', PANEL)
    c.emit('85c0'); c.branch('0f84', 'done')
    c.call(RESET)
    c.call(wide.LAYOUT)
    c.label('done')
    c.emit('83c424 619dc3')
    return c.finish(RESET-ARRANGE)


def reset_code() -> bytes:
    c = Code(RESET)
    c.emit('9c60 83ec04 8d6c2404')
    chat._get(c, 'ecx', PANEL)
    c.emit('85c9'); c.branch('0f84', 'done')
    c.emit('31c0'); chat._put(c, 'eax', PANEL)
    chat._put(c, 'eax', MODEL)
    _tabs(c, 'done')
    c.emit('394dfc'); c.branch('0f85', 'done')
    c.emit('c7463405000000 c7473405000000 31c0 894630 894730')
    for tab in ('86','87'):
        _memory(c, f'c7{tab}84020000', 250)
        c.emit(f'c6{tab}bc02000000')
    for register, invert in (('esi', True), ('edi', False)):
        chat._get(c, 'edx', SAVED_TAB)
        if invert:
            c.emit('83f201')
        c.emit('89f0' if register == 'esi' else '89f8')
        c.call(0xa51bd4)
    c.emit('8b463c 894640 8b473c 894740')
    _contents(c, split=False)
    c.label('done')
    c.emit('83c404 619dc3')
    return c.finish(ROWS-RESET)


def rows_code() -> bytes:
    c = Code(ROWS)
    c.emit('60 50 8db3'); c.word(0xad10d4-BASE)
    c.emit('31d2 bf07000000')
    c.label('row')
    for offset in (0, 4, 8, 12, 16, 20):
        skip = f'part_{offset}'
        c.emit(f'8b46{offset:02x} 85c0'); c.branch('0f84', skip)
        c.emit('895034')
        if offset == 8:
            c.emit('89483c')
        elif offset in (12, 16, 20):
            c.emit('834034'+('10' if offset == 12 else '0d'))
        c.label(skip)
    c.emit('83c618 01ca 4f'); c.branch('0f85', 'row')
    c.emit('58 8b402c 85c0'); c.branch('0f84', 'done')
    c.emit('8b4808 85c9'); c.branch('0f8e', 'done')
    c.emit('8b4004 8b4488fc 895034')
    c.label('done')
    c.emit('61c3')
    return c.finish(DRAW-ROWS)


def draw_code() -> bytes:
    c = Code(DRAW)
    c.emit('9c60'); c.base()
    c.emit('8b74241c')
    chat._get(c, 'eax', PANEL)
    c.emit('85c0'); c.branch('0f84', 'stock')
    c.emit('39464c'); c.branch('0f85', 'stock')
    c.emit('3bb3'); c.word(skin.SKILL_TAB-BASE); c.branch('0f84', 'card')
    c.emit('3bb3'); c.word(skin.ABILITY_TAB-BASE); c.branch('0f85', 'stock')
    c.label('card')
    skin._origin(c)
    _rectangle(c, (0,0,('w',1,0),('h',1,0)), skin.FRAME)
    _rectangle(c, (1,1,('w',1,-2),('h',1,-2)), skin.BODY)
    _rectangle(c, (1,1,('w',1,-2),HEADER-2), 0xff292721)
    _rectangle(c, (1,HEADER-3,('w',1,-2),2), 0xffc88335)
    c.emit('3bb3'); c.word(skin.SKILL_TAB-BASE); c.branch('0f85', 'caption')
    _rectangle(c, (16,('h',1,-SKILL_FOOTER-1),205,1), 0xff333b40)
    c.label('caption')
    c.emit('8b4dfc 83c10d 8b55f8 83c205 52 68'); c.word(native_colour(0xffeee2be))
    c.emit('8b565c b801000000'); c.call(0x4f29a8)
    c.emit('83c410 619dc3')
    c.label('stock')
    c.emit('619d'); c.jump(skin.TAB_ENTRY)
    return c.finish(LEAVE-DRAW)


def draw_model_code() -> bytes:
    c = Code(DRAW_MODEL)
    c.emit('9c60'); c.base()
    c.emit('8b770c 85f6'); c.branch('0f84', 'stock')
    c.emit('3bb3'); c.word(MODEL); c.branch('0f85', 'stock')
    c.emit('83ec10 8d6c2410 89f0'); c.call(0xa4211c)
    c.emit('8945f0 034638 8945f8 89f0'); c.call(0xa42140)
    c.emit('8945f4 03463c 8945fc 8d45f0')
    c.call(0x4f2d1c)
    chat._get(c, 'ecx', MODEL_SIZE)
    c.emit('8b451c 8b5514'); c.call(0xc2ba00)
    c.call(0x4f2e68)
    c.emit('83c410 619dc3')
    c.label('stock')
    c.emit('619d'); c.jump(STOCK_MODEL_DRAW)
    return c.finish(0x300)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected the approved expandable warehouse')
    result = bytearray(source)
    with pefile.PE(data=source, fast_load=True) as pe:
        def write(address: int, data: bytes, *, unused: bool = False) -> None:
            offset = pe.get_offset_from_rva(address-BASE)
            if unused and any(source[offset:offset+len(data)]):
                raise ValueError(f'Occupied preview code space at {address:#x}')
            result[offset:offset+len(data)] = data

        tick = Code(TICK); tick.call(wide.TICK); tick.jump(ARRANGE)
        leave = Code(LEAVE); leave.call(RESET); leave.jump(wide.RESTORE)
        for address, code in ((TICK,tick.finish(ARRANGE-TICK)), (ARRANGE,arrange_code()),
                              (RESET,reset_code()), (ROWS,rows_code()), (DRAW,draw_code()),
                              (LEAVE,leave.finish(BASE+PANEL-LEAVE)), (BASE+PANEL,bytes(20)),
                              (DRAW_MODEL,draw_model_code())):
            write(address,code,unused=True)
        tab_hook = Code(skin.TAB_PAINT); tab_hook.jump(DRAW)
        write(skin.TAB_PAINT,bytes(tab_hook.data))
        model_hook = Code(0x8aa21f); model_hook.call(DRAW_MODEL)
        write(model_hook.address,bytes(model_hook.data))
        write(wide.PAINT,wide.paint_code(extra_panel=PANEL))
        write(chat.FRAME,chat.frame_code(layout=TICK,restore=LEAVE))
    return bytes(result)


def patch_information_overlap(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != INFORMATION_OVERLAP_SHA:
        raise ValueError('Expected the reviewed published Silver')
    before = arrange_code()
    after = arrange_code(adopt_information=True)
    legacy = skills_layout_code()
    with pefile.PE(data=source, fast_load=True) as pe:
        offset = pe.get_offset_from_rva(ARRANGE-BASE)
        if (source[offset:offset+len(before)] != before
                or pe.get_data(SKILLS_ENTRY-BASE, len(legacy)) != legacy):
            raise ValueError('Unexpected barracks layout code')
    return source[:offset] + after + source[offset+len(before):]
