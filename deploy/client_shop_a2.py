"""A2 shop: the native item shop over the whole page, buying to a soldier or the warehouse.

Native controls, their callbacks, the catalogue and the purchase request stay
authoritative. This module lays the existing window_shop children out over
the A2 page and turns the unused "shop_admin" button into a Fighter/Warehouse
switch. In warehouse mode the shop backpack shows the client's own copy of
the personal warehouse (read-only) and the ordinary purchase request carries
owner 0, which the server delivers to the warehouse (tio/shop.py WAREHOUSE).
"""
from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client_equipment_batch import Code

BASE = 0x400000
SIZE = 0x8000

# Children of window_shop, in the native creation order.
CLOSE, FILTERS, LIST, NAME_TITLE, PRICE_TITLE, BUY, QUANTITY, TOTAL = 0, 1, 2, 3, 4, 5, 6, 7
SWITCH, PREVIOUS, NEXT, MODEL, SOLDIER_NAME, BAG, WEAR, WEIGHT = 8, 10, 11, 12, 13, 14, 15, 16
FITTING = tuple(range(17, 64))  # caption, two paper slots, their captions and stat rows
CHILDREN = 64
SOLDIER_ONLY = (PREVIOUS, NEXT, MODEL, SOLDIER_NAME, WEAR, WEIGHT) + FITTING

# Native client globals and routines (published Silver, pre-A2 image).
SHOP_PANEL = 0xac65c0     # -> var -> fitting panel; panel+4 window, panel+0x30 backpack
SELECTED = 0xac64b4       # -> selected soldier index in the shop
SOLDIERS = 0xac618c       # array of soldier objects; +0x6c inventory records
STOCKS = 0xac55cc         # -> client warehouse lists; +0x28 list of (kind, records)
HEADER = 0xac4bdc         # A2 barracks header; its parent is the page
SET_ITEMS = 0x8d657c      # (panel, owner, records): copy records into the backpack
REQUEST_STOCK = 0x9921a8  # (kind, force): native 69 warehouse query
SET_CAPTION = 0xa42b04
ABSOLUTE_X, ABSOLUTE_Y = 0xa4211c, 0xa42140
TEXT = 0x67571c
CLICK = 0xa459e0
BUTTON_DRAW = 0xa45400
# The two ordinary-purchase paths store the request owner: mov eax,[eax+0x28];
# mov [esi+0xc],eax. The builder 9919c8 then writes it as the 75 owner_id.
OWNER_SITES = (0x976199, 0x97646c)
OWNER_CODE = '8b402889460c'
# Calls that change the client's copy of the personal warehouse (6A reply:
# clear and add for kind 0) or refill the shop backpack with soldier items.
REFRESH_SITES = ((0x99266e, 0x917fd4), (0x9928c7, 0x917690), (0x9b33ce, SET_ITEMS))
# Each category change runs the native shop layout: it resizes the window to
# 832x448 (re-centred) and moves the catalogue and the buy row. Its prologue
# jumps to a wrapper that lays the A2 page out again before anything is drawn.
NATIVE_LAYOUT, NATIVE_LAYOUT_PROLOGUE = 0x9767fc, '558bec83c4f8'
# TGUIWindow flags: dragged by the caption, resized from the corner.
MOVABLE, RESIZABLE = 0x28c, 0x28d

# Entry offsets inside this module.
SHOW, APPLY, RESTORE = 0x0, 0x100, 0x3000
CLICK_ENTRY, FILL_STOCK, FILL_SOLDIER, OWNER_ENTRY, REFRESH_ENTRY = 0x4800, 0x4900, 0x4a00, 0x4b00, 0x4d00
DRAW_ENTRY, RELAYOUT, FIT, LAYOUT_WRAPPER = 0x5000, 0x5c00, 0x5d00, 0x5e00
STRINGS = 0x6000
MODE, DIRTY, SAVED_VALID, LAID_OUT, NO_REFILL, MOVE_VALID = 0x7f00, 0x7f04, 0x7f08, 0x7f0c, 0x7f10, 0x7f14
MOVE_SAVED, SAVED = 0x7f18, 0x7f40

BUY_CAPTIONS = ('Купить бойцу', 'Купить на склад', 'Купить')
LABELS = ('БОЕЦ', 'СКЛАД')
# At most 38 characters: they must fit beside the switch on a 1200 px page.
BANNERS = ('Покупки идут в рюкзак выбранного бойца',
           'Покупки идут на склад. Справа: склад')

MARGIN = 12
TOP = 34
SWITCH_WIDTH, SWITCH_HEIGHT = 240, 28
LIST_X = 160
# Catalogue rows draw name and price at fixed offsets; a wider list adds nothing.
LIST_WIDTH = 440
PRICE_COLUMN = 276
FOOTER = 46
SOLDIER_COLUMN = 392        # portrait and fitting room beside a wide backpack
WIDE = 760                  # right area wide enough for that side-by-side layout
ROW = TOP + SWITCH_HEIGHT + 10
MINIMUM_PAGE = (1200, 500)
NATIVE_SIZE = (832, 448)


@dataclass(frozen=True)
class Value:
    """Window-local coordinate: ((W*w + H*h + inner) >> shift) + outer."""
    outer: int = 0
    w: int = 0
    h: int = 0
    inner: int = 0
    shift: int = 0

    def at(self, width: int, height: int) -> int:
        return ((self.w*width + self.h*height + self.inner) >> self.shift) + self.outer


def _w(offset: int) -> Value:
    return Value(w=1, inner=offset)


def _h(offset: int) -> Value:
    return Value(h=1, inner=offset)


def _half_w(offset: int, outer: int) -> Value:
    return Value(outer=outer, w=1, inner=offset, shift=1)


Box = tuple[Value | int, Value | int, Value | int, Value | int]


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int


def _native() -> dict[int, tuple[int, int, int, int]]:
    """Window-local rectangles the native constructor gives each child."""
    rects = {CLOSE: (810, 6, 64, 16), FILTERS: (0, 30, 150, 413), LIST: (155, 50, 360, 362),
             NAME_TITLE: (157, 19, 273, 31), PRICE_TITLE: (431, 19, 84, 31), BUY: (165, 414, 150, 25),
             QUANTITY: (325, 414, 50, 22), TOTAL: (380, 414, 0, 0), SWITCH: (662, 15, 150, 25),
             PREVIOUS: (511, 16, 75, 25), NEXT: (579, 16, 75, 25), MODEL: (555, 84, 64, 128),
             SOLDIER_NAME: (545, 217, 100, 16), BAG: (523, 245, 296, 114), WEAR: (596, 382, 150, 25),
             WEIGHT: (530, 362, 282, 32), 17: (678, 38, 100, 16)}
    for first, (x, y), caption in ((18, (643, 74), (652, 56)), (41, (733, 74), (726, 56))):
        rects[first] = (x, y, 64, 32)
        rects[first+1] = (*caption, 100, 16)
        for row in range(7):
            top = y + 35 + 20*row
            at = first + 2 + 3*row
            rects[at], rects[at+1], rects[at+2] = (x, top, 16, 16), (x, top, 16, 16), (x+18, top, 100, 16)
    return rects


NATIVE = _native()
FITTING_ORIGIN = NATIVE[18][:2]


def right_x() -> int:
    return LIST_X + LIST_WIDTH + 16


def wide_from() -> int:
    """Smallest window width with the side-by-side soldier layout."""
    return right_x() + MARGIN + WIDE


def _common() -> dict[int, Box]:
    list_top = TOP + 31
    return {
        CLOSE: (_w(-22), 6, 64, 16),
        FILTERS: (0, 30, 150, _h(-35)),
        LIST: (LIST_X, list_top, LIST_WIDTH, _h(-list_top-FOOTER)),
        NAME_TITLE: (LIST_X+2, TOP, PRICE_COLUMN-3, 31),
        PRICE_TITLE: (LIST_X+PRICE_COLUMN, TOP, LIST_WIDTH-PRICE_COLUMN-16, 31),
        BUY: (LIST_X+10, _h(-36), 200, 25),
        QUANTITY: (LIST_X+220, _h(-36), 50, 22),
        TOTAL: (LIST_X+275, _h(-36), 0, 0),
        SWITCH: (right_x(), TOP, SWITCH_WIDTH, SWITCH_HEIGHT),
    }


def fitting_offset() -> tuple[int, int]:
    """Translation of the native fitting room into the soldier column."""
    return right_x() + 200 - FITTING_ORIGIN[0], ROW + 73 - FITTING_ORIGIN[1]


def _soldier(*, wide: bool) -> dict[int, Box]:
    x0 = right_x()
    rects: dict[int, Box] = {
        PREVIOUS: (x0, ROW, 75, 25),
        NEXT: (x0+80, ROW, 75, 25),
        # The portrait is drawn about 44 px above its box.
        MODEL: (x0+46, ROW+73, 64, 128),
        SOLDIER_NAME: (x0+28, ROW+206, 100, 16),
    }
    dx, dy = fitting_offset()
    for index in FITTING:
        x, y, width, height = NATIVE[index]
        rects[index] = (x+dx, y+dy, width, height)
    if wide:
        bag_x, bag_top, inner = x0+SOLDIER_COLUMN, ROW, -(x0+MARGIN+SOLDIER_COLUMN)
    else:
        bag_x, bag_top, inner = x0, ROW+232, -(x0+MARGIN)
    rects.update({
        BAG: (bag_x, bag_top, _w(inner), _h(-bag_top-82)),
        WEIGHT: (bag_x+4, _h(-80), _w(inner-8), 32),
        WEAR: (_half_w(inner, bag_x-75), _h(-40), 150, 25),
    })
    return rects


def plan(mode: str) -> dict[int, Box]:
    """Symbolic rectangles for 'wide', 'narrow' (soldier) or 'warehouse'."""
    rects = _common()
    if mode == 'warehouse':
        rects[BAG] = (right_x(), ROW, _w(-right_x()-MARGIN), _h(-ROW-FOOTER))
        return rects
    rects.update(_soldier(wide=mode == 'wide'))
    return rects


def _resolve(value: Value | int, width: int, height: int) -> int:
    return value if isinstance(value, int) else value.at(width, height)


def layout(width: int, height: int, *, warehouse: bool) -> dict[int, Rect]:
    """Window-local child rectangles for a shop window of the given size."""
    mode = 'warehouse' if warehouse else ('wide' if width >= wide_from() else 'narrow')
    return {index: Rect(*(_resolve(v, width, height) for v in box)) for index, box in plan(mode).items()}


# --- native code -------------------------------------------------------------

def _value(c: Code, value: Value | int) -> None:
    """EDX = value; ESI is the shop window."""
    if isinstance(value, int):
        c.emit('ba'); c.word(value)
        return
    if value.w == value.h == 0:
        c.emit('ba'); c.word((value.inner >> value.shift) + value.outer)
        return
    c.emit('8b5638' if value.w else '8b563c')
    if value.inner:
        c.emit('81c2'); c.word(value.inner)
    if value.shift:
        c.emit('c1fa'+f'{value.shift:02x}')
    if value.outer:
        c.emit('81c2'); c.word(value.outer)


def _child(c: Code, index: int, skip: str) -> None:
    """EAX = child; EDI is the children array."""
    c.emit('8b87'); c.word(index*4)
    c.emit('85c0'); c.branch('0f84', skip)


def _place(c: Code, index: int, box: Box, prefix: str) -> None:
    skip = f'{prefix}_{index}'
    _child(c, index, skip)
    for offset, value in zip((0x30, 0x34, 0x38, 0x3c), box, strict=True):
        _value(c, value); c.emit('8950'+f'{offset:02x}')
    if index == BAG:
        # The backpack caches its client size; the catalogue keeps zeros there.
        c.emit('8b5038 895044 8b503c 895040')
    if index in (LIST, BAG):
        # The child scrollbar follows the new box.
        c.emit('8b482c 85c9'); c.branch('0f84', skip)
        c.emit('83790800'); c.branch('0f8e', skip)
        c.emit('8b4904 8b09 85c9'); c.branch('0f84', skip)
        c.emit('8b5038 83ea10 895130 c7413400000000 c7413810000000 8b503c 89513c')
    c.label(skip)


def _panel_window(c: Code, skip: str) -> None:
    """ECX = the shop window (native fitting panel +4)."""
    c.emit('8b8b'); c.word(SHOP_PANEL-BASE)
    c.emit('85c9'); c.branch('0f84', skip)
    c.emit('8b09 85c9'); c.branch('0f84', skip)
    c.emit('8b4904 85c9'); c.branch('0f84', skip)


def _window(c: Code, skip: str) -> None:
    """ESI = shop window, EDI = its children (all 64 present)."""
    _panel_window(c, skip)
    c.emit('89ce 8b7e2c 85ff'); c.branch('0f84', skip)
    c.emit('837f08'+f'{CHILDREN-1:02x}'); c.branch('0f8e', skip)
    c.emit('8b7f04')


def _state(origin: int, offset: int) -> int:
    return origin + offset


def _arrange(c: Code, origin: int, mode: str, prefix: str) -> None:
    for index, box in plan(mode).items():
        _place(c, index, box, prefix)


def _visibility(c: Code, origin: int, *, hide: bool, prefix: str) -> None:
    """Save and hide the soldier-only controls, or restore what was saved."""
    if hide:
        c.emit('80bb'); c.word(_state(origin, SAVED_VALID)); c.emit('00'); c.branch('0f85', f'{prefix}_hide')
        for index in SOLDIER_ONLY:
            skip = f'{prefix}_save_{index}'
            _child(c, index, skip)
            c.emit('8a5049 8893'); c.word(_state(origin, SAVED+index))
            c.label(skip)
        c.emit('c683'); c.word(_state(origin, SAVED_VALID)); c.emit('01')
        c.label(f'{prefix}_hide')
        for index in SOLDIER_ONLY:
            skip = f'{prefix}_off_{index}'
            _child(c, index, skip); c.emit('c6404900'); c.label(skip)
        return
    c.emit('80bb'); c.word(_state(origin, SAVED_VALID)); c.emit('00'); c.branch('0f84', f'{prefix}_kept')
    for index in SOLDIER_ONLY:
        skip = f'{prefix}_restore_{index}'
        _child(c, index, skip)
        c.emit('8a93'); c.word(_state(origin, SAVED+index)); c.emit('885049')
        c.label(skip)
    c.emit('c683'); c.word(_state(origin, SAVED_VALID)); c.emit('00')
    c.label(f'{prefix}_kept')


def _caption(c: Code, origin: int, index: int, skip: str) -> None:
    _child(c, BUY, skip)
    c.emit('8d93'); c.word(origin+STRINGS+index*0x100+4)
    c.call(SET_CAPTION)


def hold_still(c: Code, valid: int, saved: int, prefix: str) -> None:
    """ESI = a page window: remember its drag/resize flags once, then clear them.

    The page window follows the A2 page every frame, so a drag would only
    snap back; the original flags return with the native layout.
    """
    c.emit('80bb'); c.word(valid); c.emit('00'); c.branch('0f85', f'{prefix}_still')
    for index, flag in enumerate((MOVABLE, RESIZABLE)):
        c.emit('8a86'); c.word(flag); c.emit('8883'); c.word(saved+index)
    c.emit('c683'); c.word(valid); c.emit('01')
    c.label(f'{prefix}_still')
    for flag in (MOVABLE, RESIZABLE):
        c.emit('c686'); c.word(flag); c.emit('00')


def let_move(c: Code, valid: int, saved: int, prefix: str) -> None:
    """ESI = the page window: give back the remembered drag/resize flags."""
    c.emit('80bb'); c.word(valid); c.emit('00'); c.branch('0f84', f'{prefix}_moved')
    for index, flag in enumerate((MOVABLE, RESIZABLE)):
        c.emit('8a83'); c.word(saved+index); c.emit('8886'); c.word(flag)
    c.emit('c683'); c.word(valid); c.emit('00')
    c.label(f'{prefix}_moved')


def _apply(origin: int) -> bytes:
    """Lay the open shop out for the current MODE and fill its backpack.

    With NO_REFILL set only the layout is redone (after a native relayout):
    the backpack keeps its records and no warehouse list is requested.
    """
    from .client_equipment_batch import Code

    c = Code(BASE+origin+APPLY)
    c.emit('9c60'); c.base()
    _window(c, 'done')
    c.emit('c683'); c.word(_state(origin, LAID_OUT)); c.emit('01')
    hold_still(c, _state(origin, MOVE_VALID), _state(origin, MOVE_SAVED), 'shop')
    c.emit('83bb'); c.word(_state(origin, MODE)); c.emit('00'); c.branch('0f85', 'warehouse')
    c.emit('817e38'); c.word(wide_from()); c.branch('0f8c', 'narrow')
    _arrange(c, origin, 'wide', 'wide'); c.branch('e9', 'soldier')
    c.label('narrow'); _arrange(c, origin, 'narrow', 'narrow')
    c.label('soldier')
    _visibility(c, origin, hide=False, prefix='soldier')
    _caption(c, origin, 0, 'soldier_caption'); c.label('soldier_caption')
    c.emit('80bb'); c.word(_state(origin, NO_REFILL)); c.emit('00'); c.branch('0f85', 'done')
    c.call(BASE+origin+FILL_SOLDIER)
    c.branch('e9', 'done')
    c.label('warehouse')
    _arrange(c, origin, 'warehouse', 'stock')
    _visibility(c, origin, hide=True, prefix='stock')
    _caption(c, origin, 1, 'stock_caption'); c.label('stock_caption')
    c.emit('80bb'); c.word(_state(origin, NO_REFILL)); c.emit('00'); c.branch('0f85', 'done')
    # Ask the server for a fresh personal list; its 6A reply marks DIRTY.
    c.emit('b000 b201'); c.call(REQUEST_STOCK)
    c.call(BASE+origin+FILL_STOCK)
    c.label('done'); c.emit('619dc3')
    return c.finish(RESTORE-APPLY)


def _restore(origin: int) -> bytes:
    """Back to the native layout once the shop opens outside the A2 canvas."""
    from .client_equipment_batch import Code

    c = Code(BASE+origin+RESTORE)
    c.emit('9c60'); c.base()
    _window(c, 'done')
    c.emit('c683'); c.word(_state(origin, LAID_OUT)); c.emit('00')
    c.emit('c783'); c.word(_state(origin, MODE)); c.word(0)
    let_move(c, _state(origin, MOVE_VALID), _state(origin, MOVE_SAVED), 'shop')
    c.emit('c74638'); c.word(NATIVE_SIZE[0])
    c.emit('c7463c'); c.word(NATIVE_SIZE[1])
    for index, rect in NATIVE.items():
        _place(c, index, rect, 'native')
    _visibility(c, origin, hide=False, prefix='native')
    _caption(c, origin, 2, 'native_caption'); c.label('native_caption')
    c.call(BASE+origin+FILL_SOLDIER)
    c.label('done'); c.emit('619dc3')
    return c.finish(CLICK_ENTRY-RESTORE)


def _show(origin: int, layout_state: int) -> bytes:
    """EAX = a window that was just shown or hidden (A2 SHOW chain)."""
    from .client_equipment_batch import Code

    c = Code(BASE+origin+SHOW)
    c.emit('9c60 89c6'); c.base()
    c.emit('807e4900'); c.branch('0f84', 'done')
    _panel_window(c, 'done')
    c.emit('39f1'); c.branch('0f85', 'done')
    c.emit('8b7e2c 85ff'); c.branch('0f84', 'done')
    c.emit('837f08'+f'{CHILDREN-1:02x}'); c.branch('0f8e', 'done')
    c.emit('8b7f04')
    c.emit('83bb'); c.word(layout_state); c.emit('01'); c.branch('0f85', 'native')
    _page(c, 'native')
    for offset in (0x30, 0x34, 0x38, 0x3c):
        c.emit('8b50'+f'{offset:02x}'+' 8956'+f'{offset:02x}')
    # Every opening starts with purchases going to the selected soldier.
    c.emit('c783'); c.word(_state(origin, MODE)); c.word(0)
    c.call(BASE+origin+APPLY)
    c.branch('e9', 'done')
    c.label('native')
    c.emit('80bb'); c.word(_state(origin, LAID_OUT)); c.emit('00'); c.branch('0f84', 'done')
    c.call(BASE+origin+RESTORE)
    c.label('done'); c.emit('619dc3')
    return c.finish(APPLY-SHOW)


def _fill_stock(origin: int) -> bytes:
    """Shop backpack = the client's kind-0 (personal) warehouse records, owner 0."""
    from .client_equipment_batch import Code

    c = Code(BASE+origin+FILL_STOCK)
    c.emit('9c60'); c.base()
    c.emit('8b83'); c.word(SHOP_PANEL-BASE); c.emit('85c0'); c.branch('0f84', 'out')
    c.emit('8b00 85c0'); c.branch('0f84', 'out')
    c.emit('89c6 31c9')
    c.emit('8b83'); c.word(STOCKS-BASE); c.emit('85c0'); c.branch('0f84', 'set')
    c.emit('8b00 85c0'); c.branch('0f84', 'set')
    c.emit('8b4028 85c0'); c.branch('0f84', 'set')
    c.emit('8b5008 8b7804')
    c.label('next')
    c.emit('85d2'); c.branch('0f8e', 'set')
    c.emit('4a 8b0497 85c0'); c.branch('0f84', 'next')
    c.emit('803800'); c.branch('0f85', 'next')
    c.emit('8b4804')
    c.label('set')
    c.emit('89f0 31d2'); c.call(SET_ITEMS)
    c.label('out'); c.emit('619dc3')
    return c.finish(0x100)


def _fill_soldier(origin: int) -> bytes:
    """Shop backpack = the selected soldier's inventory (as the native shop does)."""
    from .client_equipment_batch import Code

    c = Code(BASE+origin+FILL_SOLDIER)
    c.emit('9c60'); c.base()
    c.emit('8b83'); c.word(SHOP_PANEL-BASE); c.emit('85c0'); c.branch('0f84', 'out')
    c.emit('8b00 85c0'); c.branch('0f84', 'out')
    c.emit('89c6')
    c.emit('8b83'); c.word(SELECTED-BASE); c.emit('85c0'); c.branch('0f84', 'out')
    c.emit('8b10')
    c.emit('8b83'); c.word(SOLDIERS-BASE); c.emit('85c0'); c.branch('0f84', 'out')
    c.emit('8b0490 85c0'); c.branch('0f84', 'out')
    c.emit('8b486c 89f0'); c.call(SET_ITEMS)
    c.label('out'); c.emit('619dc3')
    return c.finish(0x100)


def _click(origin: int, layout_state: int) -> bytes:
    """EAX = released button; the switch flips the destination, others go native."""
    from .client_equipment_batch import Code

    c = Code(BASE+origin+CLICK_ENTRY)
    c.emit('9c60 89c6'); c.base()
    c.emit('83bb'); c.word(layout_state); c.emit('01'); c.branch('0f85', 'native')
    c.emit('80bb'); c.word(_state(origin, LAID_OUT)); c.emit('00'); c.branch('0f84', 'native')
    _panel_window(c, 'native')
    c.emit('8b492c 85c9'); c.branch('0f84', 'native')
    c.emit('83790808'); c.branch('0f8e', 'native')
    c.emit('8b4904 397120'); c.branch('0f85', 'native')
    c.emit('83b3'); c.word(_state(origin, MODE)); c.emit('01')
    c.call(BASE+origin+APPLY)
    c.emit('619dc3')
    c.label('native'); c.emit('619d'); c.jump(CLICK)
    return c.finish(0x100)


def _owner(origin: int, layout_state: int, index: int) -> bytes:
    """Ordinary purchase owner: 0 (warehouse) while the A2 shop is in warehouse mode."""
    from .client_equipment_batch import Code

    site = OWNER_SITES[index]
    c = Code(BASE+origin+OWNER_ENTRY+index*0x100)
    c.emit('8b4028 9c 53 51'); c.base()
    c.emit('83bb'); c.word(layout_state); c.emit('01'); c.branch('0f85', 'keep')
    c.emit('83bb'); c.word(_state(origin, MODE)); c.emit('01'); c.branch('0f85', 'keep')
    _panel_window(c, 'keep')
    c.emit('80794900'); c.branch('0f84', 'keep')
    c.emit('31c0')
    c.label('keep'); c.emit('59 5b 9d 89460c')
    c.jump(site+len(bytes.fromhex(OWNER_CODE)))
    return c.finish(0x100)


def _refresh(origin: int, index: int) -> bytes:
    """Run the native call, then let the next switch draw refill the warehouse view."""
    from .client_equipment_batch import Code

    _, target = REFRESH_SITES[index]
    c = Code(BASE+origin+REFRESH_ENTRY+index*0x100)
    c.call(target)
    c.emit('9c 53'); c.base()
    c.emit('c683'); c.word(_state(origin, DIRTY)); c.emit('01')
    c.emit('5b 9d c3')
    return c.finish(0x100)


def _text(c: Code, origin: int, index: int, x: int, y: int, colour: int, font: int) -> None:
    from .client_barracks_skin import native_colour

    c.emit('68'); c.word(native_colour(colour)); c.emit('6a'+f'{font:02x}'+' 6a00')
    c.emit('8b55fc 81c2'); c.word(x)
    c.emit('8b4df8 81c1'); c.word(y)
    c.emit('8d83'); c.word(origin+STRINGS+0x300+index*0x100+12)
    c.call(TEXT)


TEXT_WIDTH = 7  # approximate advance of the native Cyrillic fonts


def _segment(c: Code, origin: int, active: int) -> None:
    from .client_barracks_skin import _rectangle

    half = SWITCH_WIDTH // 2
    _rectangle(c, (0, 0, SWITCH_WIDTH, SWITCH_HEIGHT), 0xff3a4148)
    _rectangle(c, (1, 1, SWITCH_WIDTH-2, SWITCH_HEIGHT-2), 0xff161a1e)
    _rectangle(c, (active*half, 0, half, SWITCH_HEIGHT), 0xffe8891f)
    _rectangle(c, (active*half+2, 2, half-4, SWITCH_HEIGHT-4), 0xff2a2418)
    _rectangle(c, (active*half+2, SWITCH_HEIGHT-4, half-4, 2), 0xffe8891f)
    for index, label in enumerate(LABELS):
        colour = 0xffffd27a if index == active else 0xff8a8f96
        _text(c, origin, index, index*half + (half - len(label)*TEXT_WIDTH)//2, 7, colour, 3)
    _text(c, origin, 2+active, SWITCH_WIDTH+14, 7, 0xffc9b77a, 3)


def _page(c: Code, skip: str) -> None:
    """EAX = the A2 page (barracks header's parent) when it is large enough."""
    c.emit('8b83'); c.word(HEADER-BASE)
    c.emit('85c0'); c.branch('0f84', skip)
    c.emit('8b404c 85c0'); c.branch('0f84', skip)
    c.emit('817838'); c.word(MINIMUM_PAGE[0]); c.branch('0f8c', skip)
    c.emit('81783c'); c.word(MINIMUM_PAGE[1]); c.branch('0f8c', skip)


def _fit(c: Code, origin: int, shrink: str) -> None:
    """EDI = shop window. The native show re-centres it after SHOW, and the
    canvas may change while it is open: follow the page and lay out again,
    or go to shrink when the page became too small for the A2 shop."""
    _page(c, shrink)
    for offset in (0x30, 0x34, 0x38, 0x3c):
        c.emit('8b50'+f'{offset:02x}'+' 3957'+f'{offset:02x}'); c.branch('0f85', 'refit')
    c.branch('e9', 'fitted')
    c.label('refit')
    for offset in (0x30, 0x34, 0x38, 0x3c):
        c.emit('8b50'+f'{offset:02x}'+' 8957'+f'{offset:02x}')
    c.call(BASE+origin+RELAYOUT)
    c.label('fitted')


def _draw(origin: int, layout_state: int, forward: int) -> bytes:
    """The switch: two segments, the active one lit, and where purchases go."""
    from .client_equipment_batch import Code

    c = Code(BASE+origin+DRAW_ENTRY)
    c.emit('55 89e5 83ec10 9c60 89c6'); c.base()
    c.emit('80bb'); c.word(_state(origin, LAID_OUT)); c.emit('00'); c.branch('0f84', 'native')
    c.emit('807e4900'); c.branch('0f84', 'native')
    _panel_window(c, 'native')
    c.emit('89cf 8b492c 85c9'); c.branch('0f84', 'native')
    c.emit('83790808'); c.branch('0f8e', 'native')
    c.emit('8b4904 397120'); c.branch('0f85', 'native')
    c.emit('83bb'); c.word(layout_state); c.emit('01'); c.branch('0f85', 'native')
    # A 6A reply or a native soldier refill changed the backpack: show the stock again.
    c.emit('80bb'); c.word(_state(origin, DIRTY)); c.emit('00'); c.branch('0f84', 'paint')
    c.emit('c683'); c.word(_state(origin, DIRTY)); c.emit('00')
    c.emit('83bb'); c.word(_state(origin, MODE)); c.emit('01'); c.branch('0f85', 'paint')
    c.call(BASE+origin+FILL_STOCK)
    c.label('paint')
    c.emit('89f0'); c.call(ABSOLUTE_X); c.emit('8945fc')
    c.emit('89f0'); c.call(ABSOLUTE_Y); c.emit('8945f8')
    c.emit('83bb'); c.word(_state(origin, MODE)); c.emit('01'); c.branch('0f84', 'stock')
    _segment(c, origin, 0); c.branch('e9', 'done')
    c.label('stock'); _segment(c, origin, 1)
    c.label('done'); c.emit('619d 89ec5dc3')
    c.label('native'); c.emit('619d 89ec5d'); c.jump(forward)
    return c.finish(RELAYOUT-DRAW_ENTRY)


def _relayout(origin: int) -> bytes:
    """Lay out again without refilling the backpack or asking for the warehouse."""
    from .client_equipment_batch import Code

    c = Code(BASE+origin+RELAYOUT)
    c.emit('9c53'); c.base()
    c.emit('c683'); c.word(_state(origin, NO_REFILL)); c.emit('01')
    c.call(BASE+origin+APPLY)
    c.emit('c683'); c.word(_state(origin, NO_REFILL)); c.emit('00')
    c.emit('5b9dc3')
    return c.finish(FIT-RELAYOUT)


def _fit_entry(origin: int, layout_state: int) -> bytes:
    """EAX = a window about to be drawn. A laid-out shop follows the page, or
    goes back to native once the canvas left A2 or shrank, before it is drawn."""
    from .client_equipment_batch import Code

    c = Code(BASE+origin+FIT)
    c.emit('9c60 89c6'); c.base()
    c.emit('80bb'); c.word(_state(origin, LAID_OUT)); c.emit('00'); c.branch('0f84', 'done')
    _panel_window(c, 'done')
    c.emit('39f1'); c.branch('0f85', 'done')
    c.emit('89f7')
    c.emit('83bb'); c.word(layout_state); c.emit('01'); c.branch('0f85', 'shrink')
    _fit(c, origin, 'shrink')
    c.branch('e9', 'done')
    c.label('shrink'); c.call(BASE+origin+RESTORE)
    c.label('done'); c.emit('619dc3')
    return c.finish(LAYOUT_WRAPPER-FIT)


def _layout_wrapper(origin: int, layout_state: int) -> bytes:
    """Native shop layout, then at once the A2 page again (no drawn native frame)."""
    from .client_equipment_batch import Code

    trampoline = BASE+origin+LAYOUT_WRAPPER+0x100
    c = Code(BASE+origin+LAYOUT_WRAPPER)
    c.call(trampoline)
    c.emit('9c60'); c.base()
    c.emit('83bb'); c.word(layout_state); c.emit('01'); c.branch('0f85', 'out')
    c.emit('80bb'); c.word(_state(origin, LAID_OUT)); c.emit('00'); c.branch('0f84', 'out')
    _panel_window(c, 'out')
    c.emit('80794900'); c.branch('0f84', 'out')
    c.emit('89cf')
    _page(c, 'out')
    for offset in (0x30, 0x34, 0x38, 0x3c):
        c.emit('8b50'+f'{offset:02x}'+' 8957'+f'{offset:02x}')
    c.call(BASE+origin+RELAYOUT)
    c.label('out'); c.emit('619dc3')
    body = c.finish(0x100)
    t = Code(trampoline)
    t.emit(NATIVE_LAYOUT_PROLOGUE)
    t.jump(NATIVE_LAYOUT+len(bytes.fromhex(NATIVE_LAYOUT_PROLOGUE)))
    return body + t.finish(0x100)


def _strings() -> bytes:
    from .client_barracks_skin import caption_literal

    result = bytearray(0x1000)
    for index, caption in enumerate(BUY_CAPTIONS):
        # SetCaption takes a WideString: byte length, UTF-16, terminator.
        raw = caption.encode('utf-16le')
        literal = struct.pack('<I', len(raw)) + raw + b'\0\0'
        result[index*0x100:index*0x100+len(literal)] = literal
    for index, text in enumerate(LABELS + BANNERS):
        literal = caption_literal(text)
        at = 0x300 + index*0x100
        result[at:at+len(literal)] = literal
    return bytes(result)


def payload(origin: int, layout_state: int, draw_forward: int) -> bytes:
    """The module at RVA origin; layout_state is the A2 STATE flag (RVA)."""
    result = bytearray(SIZE)
    for offset, code in ((SHOW, _show(origin, layout_state)), (APPLY, _apply(origin)),
                         (RESTORE, _restore(origin)),
                         (CLICK_ENTRY, _click(origin, layout_state)),
                         (FILL_STOCK, _fill_stock(origin)), (FILL_SOLDIER, _fill_soldier(origin)),
                         (DRAW_ENTRY, _draw(origin, layout_state, draw_forward)),
                         (RELAYOUT, _relayout(origin)), (FIT, _fit_entry(origin, layout_state)),
                         (LAYOUT_WRAPPER, _layout_wrapper(origin, layout_state)),
                         (STRINGS, _strings())):
        result[offset:offset+len(code)] = code
    for index in range(len(OWNER_SITES)):
        at = OWNER_ENTRY + index*0x100
        result[at:at+0x100] = _owner(origin, layout_state, index)
    for index in range(len(REFRESH_SITES)):
        at = REFRESH_ENTRY + index*0x100
        result[at:at+0x100] = _refresh(origin, index)
    return bytes(result)


def show_entry(origin: int) -> int:
    return BASE + origin + SHOW


def click_entry(origin: int) -> int:
    return BASE + origin + CLICK_ENTRY


def draw_entry(origin: int) -> int:
    return BASE + origin + DRAW_ENTRY


def edits(origin: int) -> tuple[tuple[int, bytes, bytes], ...]:
    """Owner stores jump to their thunks; warehouse/backpack refills are wrapped."""
    result = []
    for index, site in enumerate(OWNER_SITES):
        before = bytes.fromhex(OWNER_CODE)
        after = b'\xe9' + struct.pack('<i', BASE+origin+OWNER_ENTRY+index*0x100-site-5)
        result.append((site, before, after.ljust(len(before), b'\x90')))
    for index, (site, target) in enumerate(REFRESH_SITES):
        result.append((site, b'\xe8'+struct.pack('<i', target-site-5),
                       b'\xe8'+struct.pack('<i', BASE+origin+REFRESH_ENTRY+index*0x100-site-5)))
    before = bytes.fromhex(NATIVE_LAYOUT_PROLOGUE)
    after = b'\xe9' + struct.pack('<i', BASE+origin+LAYOUT_WRAPPER-NATIVE_LAYOUT-5)
    result.append((NATIVE_LAYOUT, before, after.ljust(len(before), b'\x90')))
    return tuple(result)


def fit_entry(origin: int) -> int:
    return BASE + origin + FIT


