"""A2 full-page layout for the SC goods and item rental shops.

Both windows keep their native controls and callbacks. Their lists draw rows
at fixed column offsets, so they only grow in height; filters, buttons and
captions follow the page. The windows cannot be dragged while laid out.
Every TGUIWindow draw passes through this module first: the ordinary A2 shop
and these windows are fitted to the page before anything of them is drawn.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct
from typing import TYPE_CHECKING

from .client_shop_a2 import Box, MINIMUM_PAGE, Value, _h, _value, _w, hold_still, let_move

if TYPE_CHECKING:
    from .client_equipment_batch import Code

BASE = 0x400000
SIZE = 0xf00                    # fits in the free tail of the shop block
HEADER = 0xac4bdc
NAME_EQUALS = 0xc2be00         # (name, literal, length): 1 when the UTF-16 names match
WINDOW_DRAW_SLOT, WINDOW_DRAW = 0xa31a48, 0xa43774   # TGUIWindow VMT +08

SHOW, DRAW, BLOCK, BLOCK_SIZE = 0x0, 0x40, 0x100, 0x600
# Per-window block: show, fit, restore and arrange routines, then the name.
SHOW_AT, FIT_AT, RESTORE_AT, ARRANGE_AT, NAME_AT = 0x0, 0x140, 0x240, 0x400, 0x580
# Per-window state (0x20 bytes each: pointer, laid out, drag flags) at an RVA
# the composer chooses.
POINTER, LAID_OUT, MOVE_VALID, MOVE_SAVED = 0x0, 0x4, 0x8, 0xc


@dataclass(frozen=True)
class PageWindow:
    name: str
    native_size: tuple[int, int]
    boxes: dict[int, Box]
    natives: dict[int, tuple[int, int, int, int]]
    scrolled: frozenset[int] = field(default_factory=frozenset)

    @property
    def children(self) -> int:
        return max(self.boxes) + 1


SC_SHOP = PageWindow(
    'window_scshop', (896, 512),
    boxes={0: (_w(-22), 6, 64, 16), 2: (0, 62, 150, _h(-108)),
           5: (160, 90, 546, _h(-136)), 12: (160, _h(-40), 100, 16)},
    natives={0: (874, 6, 64, 16), 2: (0, 62, 150, 358), 5: (160, 90, 546, 380), 12: (160, 473, 100, 16)},
    scrolled=frozenset({5}))
RENT_SHOP = PageWindow(
    'window_rentshop', (640, 544),
    boxes={0: (_w(-22), 6, 64, 16), 2: (0, 62, 150, _h(-108)), 7: (170, 90, 440, _h(-146)),
           12: (215, _h(-42), 175, 25), 13: (390, _h(-42), 175, 25)},
    natives={0: (618, 6, 64, 16), 2: (0, 62, 150, 358), 7: (170, 90, 440, 400),
             12: (215, 502, 175, 25), 13: (390, 502, 175, 25)},
    scrolled=frozenset({7}))
WINDOWS = (SC_SHOP, RENT_SHOP)


def layout(window: PageWindow, width: int, height: int) -> dict[int, tuple[int, int, int, int]]:
    """Window-local child rectangles on a page of the given size."""
    def resolve(value: Value | int) -> int:
        return value if isinstance(value, int) else value.at(width, height)
    return {index: tuple(resolve(v) for v in box) for index, box in window.boxes.items()}


# --- native code -------------------------------------------------------------

def _state(state: int, index: int, offset: int) -> int:
    return state + index*0x20 + offset


def _entry(origin: int, index: int, offset: int) -> int:
    return BASE + origin + BLOCK + index*BLOCK_SIZE + offset


def _page(c: Code, skip: str) -> None:
    """EAX = the A2 page (barracks header's parent) when it is large enough."""
    c.emit('8b83'); c.word(HEADER-BASE)
    c.emit('85c0'); c.branch('0f84', skip)
    c.emit('8b404c 85c0'); c.branch('0f84', skip)
    c.emit('817838'); c.word(MINIMUM_PAGE[0]); c.branch('0f8c', skip)
    c.emit('81783c'); c.word(MINIMUM_PAGE[1]); c.branch('0f8c', skip)


def _children(c: Code, window: PageWindow, skip: str) -> None:
    """EDI = children of the window in ESI, all laid-out indices present."""
    c.emit('8b7e2c 85ff'); c.branch('0f84', skip)
    c.emit('837f08'); c.emit(f'{window.children-1:02x}'); c.branch('0f8e', skip)
    c.emit('8b7f04')


def _place(c: Code, index: int, box, scrolled: bool, prefix: str) -> None:
    skip = f'{prefix}_{index}'
    c.emit('8b87'); c.word(index*4); c.emit('85c0'); c.branch('0f84', skip)
    for offset, value in zip((0x30, 0x34, 0x38, 0x3c), box, strict=True):
        _value(c, value); c.emit('8950'+f'{offset:02x}')
    if scrolled:
        c.emit('8b482c 85c9'); c.branch('0f84', skip)
        c.emit('83790800'); c.branch('0f8e', skip)
        c.emit('8b4904 8b09 85c9'); c.branch('0f84', skip)
        c.emit('8b5038 83ea10 895130 c7413400000000 c7413810000000 8b503c 89513c')
    c.label(skip)


def _arrange(origin: int, index: int, window: PageWindow) -> bytes:
    """ESI = window already sized to the page: place the page children."""
    from .client_equipment_batch import Code

    c = Code(_entry(origin, index, ARRANGE_AT))
    c.emit('60')
    _children(c, window, 'done')
    for child, box in window.boxes.items():
        _place(c, child, box, child in window.scrolled, 'page')
    c.label('done'); c.emit('61c3')
    return c.finish(NAME_AT-ARRANGE_AT)


def _restore(origin: int, state: int, index: int, window: PageWindow) -> bytes:
    """ESI = window: native size, native child boxes and drag flags."""
    from .client_equipment_batch import Code

    c = Code(_entry(origin, index, RESTORE_AT))
    c.emit('60'); c.base()
    c.emit('c683'); c.word(_state(state, index, LAID_OUT)); c.emit('00')
    let_move(c, _state(state, index, MOVE_VALID), _state(state, index, MOVE_SAVED), 'page')
    c.emit('c74638'); c.word(window.native_size[0])
    c.emit('c7463c'); c.word(window.native_size[1])
    _children(c, window, 'done')
    for child, rect in window.natives.items():
        _place(c, child, rect, child in window.scrolled, 'native')
    c.label('done'); c.emit('61c3')
    return c.finish(ARRANGE_AT-RESTORE_AT)


def _copy_page(c: Code) -> None:
    for offset in (0x30, 0x34, 0x38, 0x3c):
        c.emit('8b50'+f'{offset:02x}'+' 8956'+f'{offset:02x}')


def _show(origin: int, state: int, index: int, window: PageWindow, layout_state: int) -> bytes:
    """ESI = a window that was just shown or hidden."""
    from .client_equipment_batch import Code

    c = Code(_entry(origin, index, SHOW_AT))
    c.emit('60'); c.base()
    c.emit('807e4900'); c.branch('0f84', 'out')
    c.emit('8b4668 8d93'); c.word(origin+BLOCK+index*BLOCK_SIZE+NAME_AT)
    c.emit('b9'); c.word(len(window.name)); c.call(NAME_EQUALS)
    c.emit('85c0'); c.branch('0f84', 'out')
    c.emit('83bb'); c.word(layout_state); c.emit('01'); c.branch('0f85', 'native')
    _page(c, 'native')
    c.emit('89c2')
    _children(c, window, 'out')
    c.emit('89b3'); c.word(_state(state, index, POINTER))
    hold_still(c, _state(state, index, MOVE_VALID), _state(state, index, MOVE_SAVED), 'page')
    c.emit('89d0'); _copy_page(c)
    c.call(_entry(origin, index, ARRANGE_AT))
    c.emit('c683'); c.word(_state(state, index, LAID_OUT)); c.emit('01')
    c.branch('e9', 'out')
    c.label('native')
    c.emit('80bb'); c.word(_state(state, index, LAID_OUT)); c.emit('00'); c.branch('0f84', 'out')
    c.emit('3bb3'); c.word(_state(state, index, POINTER)); c.branch('0f85', 'out')
    c.call(_entry(origin, index, RESTORE_AT))
    c.label('out'); c.emit('61c3')
    return c.finish(FIT_AT-SHOW_AT)


def _fit(origin: int, state: int, index: int, layout_state: int) -> bytes:
    """EAX = window about to be drawn: follow the page, or go back to native."""
    from .client_equipment_batch import Code

    c = Code(_entry(origin, index, FIT_AT))
    c.emit('60'); c.base()
    c.emit('80bb'); c.word(_state(state, index, LAID_OUT)); c.emit('00'); c.branch('0f84', 'out')
    c.emit('3b83'); c.word(_state(state, index, POINTER)); c.branch('0f85', 'out')
    c.emit('89c6')
    c.emit('83bb'); c.word(layout_state); c.emit('01'); c.branch('0f85', 'shrink')
    _page(c, 'shrink')
    for offset in (0x30, 0x34, 0x38, 0x3c):
        c.emit('8b50'+f'{offset:02x}'+' 3956'+f'{offset:02x}'); c.branch('0f85', 'refit')
    c.branch('e9', 'out')
    c.label('refit'); _copy_page(c); c.call(_entry(origin, index, ARRANGE_AT))
    c.branch('e9', 'out')
    c.label('shrink'); c.call(_entry(origin, index, RESTORE_AT))
    c.label('out'); c.emit('61c3')
    return c.finish(RESTORE_AT-FIT_AT)


def _show_all(origin: int) -> bytes:
    """EAX = a window that was just shown or hidden (A2 SHOW chain)."""
    from .client_equipment_batch import Code

    c = Code(BASE+origin+SHOW)
    c.emit('9c60 89c6')
    for index in range(len(WINDOWS)):
        c.call(_entry(origin, index, SHOW_AT))
    c.emit('619dc3')
    return c.finish(DRAW-SHOW)


def _draw(origin: int, shop_fit: int) -> bytes:
    """TGUIWindow draw: fit the laid-out page windows first, then draw natively."""
    from .client_equipment_batch import Code

    c = Code(BASE+origin+DRAW)
    c.emit('9c60')
    c.call(shop_fit)
    for index in range(len(WINDOWS)):
        c.emit('8b44241c'); c.call(_entry(origin, index, FIT_AT))
    c.emit('619d'); c.jump(WINDOW_DRAW)
    return c.finish(BLOCK-DRAW)


def payload(origin: int, state: int, layout_state: int, shop_fit: int) -> bytes:
    """The module at RVA origin, its state at RVA state; layout_state is A2 STATE."""
    result = bytearray(SIZE)
    result[SHOW:DRAW] = _show_all(origin)
    result[DRAW:BLOCK] = _draw(origin, shop_fit)
    for index, window in enumerate(WINDOWS):
        block = BLOCK + index*BLOCK_SIZE
        for offset, code in ((SHOW_AT, _show(origin, state, index, window, layout_state)),
                             (FIT_AT, _fit(origin, state, index, layout_state)),
                             (RESTORE_AT, _restore(origin, state, index, window)),
                             (ARRANGE_AT, _arrange(origin, index, window))):
            result[block+offset:block+offset+len(code)] = code
        name = window.name.encode('utf-16le')
        result[block+NAME_AT:block+NAME_AT+len(name)] = name
    return bytes(result)


def show_entry(origin: int) -> int:
    return BASE + origin + SHOW


def edits(origin: int) -> tuple[tuple[int, bytes, bytes], ...]:
    return ((WINDOW_DRAW_SLOT, struct.pack('<I', WINDOW_DRAW), struct.pack('<I', BASE+origin+DRAW)),)
