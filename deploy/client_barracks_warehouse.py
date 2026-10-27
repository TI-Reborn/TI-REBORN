"""A2 warehouse column: full-height item grid with a drop-down filter list.

Geometry is pure data consumed by the A2 layout. The native code here only
toggles the existing TGUIItemsFilters list and draws the owner tabs and the
filter button; item data, filtering and transfers stay with native handlers.
"""
from __future__ import annotations

import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client_equipment_batch import Code

BASE = 0x400000
SIZE = 0x5400
Expr = int | tuple[str, int, int]
TABLE = 0xad10a4
OWNERS = 0xad1098
# TGUIButton.MouseUp calls the click routine directly for a left release.
CLICK_SITE = 0xa45953
CLICK = 0xa459e0
BUTTON_DRAW = 0xa45400
OWNER_CAPTIONS = ('ОБЩИЕ', 'ЛИЧНЫЕ', 'КЛАН')
FILTER_CAPTION = 'ФИЛЬТР'
# Children of the native warehouse panel (TABLE).
GRID, FILTERS, TOGGLE, FOOTER, TAG, SEARCH, SEARCH_CAPTION, FILTER_TOOL = 0, 6, 7, 8, 12, 13, 14, 16
BAR = 28
FOOTER_HEIGHT = 56
COUNTER_HEIGHT = 24
COLUMN_TOP = 112
# Column height is the page height minus the top and the 12 px margin.
COLUMN_BOTTOM = 124


def _bottom(offset: int) -> Expr:
    """A TABLE-local y measured upwards from the column's bottom edge."""
    return ('h', 1, -COLUMN_BOTTOM-offset)


def plan(right: int) -> dict[str, tuple[Expr, ...]]:
    """TABLE-local rectangles; owner tabs are relative to their own panel.

    Top bar: category filter, owner tabs, the native tag selector ('Метка').
    Counter row: 'Склад n/m' on the left, search on the right.
    """
    full = right >= 554
    toggle = 118 if full else 96
    owner = 84 if full else 68
    gap = 6 if full else 4
    tag = toggle + gap + 3*owner + gap
    search = 166 if full else 140
    grid_bottom = FOOTER_HEIGHT + COUNTER_HEIGHT
    grid_height = _bottom(BAR + 6 + grid_bottom)
    return {
        'toggle': (0, 0, toggle, BAR),
        'owners': (toggle+gap, 0, 3*owner, BAR),
        'owner': (0, 0, owner-4, BAR),
        'owner_pitch': (owner, 0, 0, 0),
        'tag_frame': (tag, 0, right-tag, BAR),
        'tag': (tag+8, 7, right-tag-26, 15),
        'search_caption': (right-search-50, _bottom(FOOTER_HEIGHT+COUNTER_HEIGHT-5), 46, 15),
        'search': (right-search, _bottom(FOOTER_HEIGHT+COUNTER_HEIGHT-1), search, COUNTER_HEIGHT-3),
        'grid': (0, BAR+6, right, grid_height),
        'grid_scroll': (right-16, 0, 16, grid_height),
        'filters': (0, BAR+2, toggle+80, _bottom(BAR+2+grid_bottom)),
        'filter_tool': (toggle+80-22, BAR+8, 16, 16),
        'footer': (0, _bottom(FOOTER_HEIGHT), right, FOOTER_HEIGHT),
        'resource_a': (5, _bottom(29), 22, 22),
        'resource_b': ((81 if full else 61), _bottom(28), 22, 22),
        'refresh': (right-30, _bottom(30), 24, 24),
        'marker': (right-52, _bottom(46), 0, 0),
    }


def counter_offset() -> tuple[int, int]:
    """'Склад n/m' sits bottom-left, between the grid and the resource row."""
    return 10, FOOTER_HEIGHT + COUNTER_HEIGHT - 5


def arrow_offset(right: int) -> int:
    """Rotate arrows flank the navigation tabs under the soldier."""
    from .client_barracks_a2 import tab_width

    return 5*tab_width(right)//2 + 8


def _children(c: Code, skip: str) -> None:
    """ESI=TABLE, EDX=children array; requires every child up to FILTER_TOOL."""
    c.emit('8bb3'); c.word(TABLE-BASE)
    c.emit('85f6'); c.branch('0f84', skip)
    c.emit('8b562c 85d2'); c.branch('0f84', skip)
    c.emit('837a08'+f'{FILTER_TOOL:02x}'); c.branch('0f8e', skip)
    c.emit('8b5204')


def apply_code(address: int, layout_state: int, open_flag: int) -> bytes:
    """Show the category list and its tool button only while open."""
    from .client_equipment_batch import Code

    c = Code(address)
    c.emit('9c60'); c.base()
    c.emit('83bb'); c.word(layout_state); c.emit('01'); c.branch('0f85', 'done')
    _children(c, 'done')
    c.emit('8a83'); c.word(open_flag)
    for child in (FILTERS, FILTER_TOOL):
        c.emit('8b8a'); c.word(child*4); c.emit('884149')
    c.label('done'); c.emit('619dc3')
    return c.finish(0x100)


# TABLE child 7 natively switches the grid to its list view, firing on press.
BUTTON_DOWN = (0xa2ed74, 0xa45150)     # TGUIButton +40: press (fires the action)
CONTROL_DOWN = 0xa43308                # inherited press: captures the mouse


def toggle_down_code(address: int, layout_state: int) -> bytes:
    """Keep the press capture for the filter button, never its view switch."""
    from .client_equipment_batch import Code

    c = Code(address)
    c.emit('55 89e5 9c60'); c.base()
    c.emit('83bb'); c.word(layout_state); c.emit('01'); c.branch('0f85', 'native')
    c.emit('89c7')
    _children(c, 'native')
    c.emit('3b7a'+f'{TOGGLE*4:02x}'); c.branch('0f85', 'native')
    c.emit('619d 5d ff742404'); c.call(CONTROL_DOWN); c.emit('c20400')
    c.label('native'); c.emit('619d 5d'); c.jump(BUTTON_DOWN[1])
    return c.finish(0x100)


# Input/draw methods replaced in the VMTs of the two warehouse classes.
GRID_MOVE = (0x995ee8, 0x99edb4)       # TGUIInventoryList +24: move (EDX=x, ECX=y)
GRID_DOWN = (0x995eec, 0x99ee20)       # TGUIInventoryList +28: press (ECX=x, [ESP+4]=y)
FILTERS_DOWN = (0x6ca028, 0x6cc62c)    # TGUIItemsFilters +28: press, selects a category
FILTERS_DRAW = (0x6ca008, 0x6cc3c8)    # TGUIItemsFilters +08: draw


def _open_child(c: Code, layout_state: int, open_flag: int, child: int, skip: str) -> None:
    """ESI=the TABLE child when the A2 list is open and EAX is that child."""
    c.emit('83bb'); c.word(layout_state); c.emit('01'); c.branch('0f85', skip)
    c.emit('83bb'); c.word(open_flag); c.emit('00'); c.branch('0f84', skip)
    c.emit('89c7')
    _children(c, skip)
    c.emit('3b7a'+f'{child*4:02x}'); c.branch('0f85', skip)
    c.emit('8b72'+f'{FILTERS*4:02x}')


def _inside_filters(c: Code, x: str, y: str, outside: str) -> None:
    """Parent-local point (registers or [ebp] operands) within the list rect."""
    c.emit('8b'+x+' 2b4630'); c.branch('0f8c', outside)
    c.emit('3b4638'); c.branch('0f8d', outside)
    c.emit('8b'+y+' 2b4634'); c.branch('0f8c', outside)
    c.emit('3b463c'); c.branch('0f8d', outside)


def grid_move_code(address: int, layout_state: int, open_flag: int) -> bytes:
    """No item hover or tooltip under the open list."""
    from .client_equipment_batch import Code

    c = Code(address)
    c.emit('55 89e5 52 51 9c60'); c.base()
    _open_child(c, layout_state, open_flag, GRID, 'native')
    _inside_filters(c, '45fc', '45f8', 'native')
    c.emit('619d 89ec5dc3')
    c.label('native'); c.emit('619d 89ec5d'); c.jump(GRID_MOVE[1])
    return c.finish(0x100)


def grid_down_code(address: int, layout_state: int, open_flag: int, apply: int) -> bytes:
    """While open the grid ignores presses; one outside the list closes it.

    The grid is dispatched before the list, so it must not hide the list for
    a press on a category, or the native selection would never run.
    """
    from .client_equipment_batch import Code

    c = Code(address)
    c.emit('55 89e5 51 9c60'); c.base()
    _open_child(c, layout_state, open_flag, GRID, 'native')
    _inside_filters(c, '45fc', '4508', 'close')
    c.branch('e9', 'swallow')
    c.label('close')
    c.emit('c783'); c.word(open_flag); c.word(0)
    c.call(apply)
    c.label('swallow'); c.emit('619d 89ec5dc20400')
    c.label('native'); c.emit('619d 89ec5d'); c.jump(GRID_DOWN[1])
    return c.finish(0x100)


def filters_down_code(address: int, layout_state: int, open_flag: int, apply: int) -> bytes:
    """Close the list after the native handler applied the chosen category."""
    from .client_equipment_batch import Code

    c = Code(address)
    c.emit('55 89e5 50 51 ff7508'); c.call(FILTERS_DOWN[1])
    c.emit('8b45fc 9c60'); c.base()
    _open_child(c, layout_state, open_flag, FILTERS, 'done')
    _inside_filters(c, '45f8', '4508', 'done')
    c.emit('c783'); c.word(open_flag); c.word(0)
    c.call(apply)
    c.label('done'); c.emit('619d 89ec5dc20400')
    return c.finish(0x100)


def filters_draw_code(address: int, layout_state: int, open_flag: int) -> bytes:
    """An opaque terminal panel behind the category list."""
    from .client_barracks_skin import _rectangle
    from .client_equipment_batch import Code

    c = Code(address)
    c.emit('55 89e5 83ec10 9c60 89c6'); c.base()
    c.emit('89f0')
    _open_child(c, layout_state, open_flag, FILTERS, 'native')
    c.emit('89f0'); c.call(0xa4211c); c.emit('8945fc')
    c.emit('89f0'); c.call(0xa42140); c.emit('8945f8')
    _rectangle(c, (0, 0, ('w', 1, 0), ('h', 1, 4)), 0xffe8891f)
    _rectangle(c, (1, 1, ('w', 1, -2), ('h', 1, 2)), 0xfa12161a)
    _rectangle(c, (1, 1, ('w', 1, -2), 2), 0xffc87a22)
    c.label('native'); c.emit('619d 89ec5d'); c.jump(FILTERS_DRAW[1])
    return c.finish(0x200)


def click_code(address: int, layout_state: int, open_flag: int, apply: int) -> bytes:
    """Toggle the list for the A2 filter button; forward every other click."""
    from .client_equipment_batch import Code

    c = Code(address)
    c.emit('9c60'); c.base()
    c.emit('83bb'); c.word(layout_state); c.emit('01'); c.branch('0f85', 'native')
    c.emit('89c7')
    _children(c, 'native')
    c.emit('3b7a'+f'{TOGGLE*4:02x}'); c.branch('0f85', 'native')
    c.emit('83b3'); c.word(open_flag); c.emit('01')
    c.call(apply)
    c.emit('619dc3')
    c.label('native'); c.emit('619d'); c.jump(CLICK)
    return c.finish(0x100)


def _chevron(c: Code, x: Expr, y: int, colour: int) -> None:
    from .client_barracks_a2 import _relative
    from .client_barracks_skin import _rectangle

    for row, width in enumerate((9, 7, 5, 3, 1)):
        _rectangle(c, (_relative(x, row), y+row, width, 1), colour)


def _frame(c: Code, colour: int, fill: int) -> None:
    from .client_barracks_skin import _rectangle

    _rectangle(c, (0, 0, ('w', 1, 0), ('h', 1, 0)), colour)
    _rectangle(c, (1, 1, ('w', 1, -2), ('h', 1, -2)), fill)


TABS = 0xad1094
SETTINGS = 2
# Inventory settings cog in the Inventory tab's corner (rows of '#').
COG = ('.....#.....', '..#.###.#..', '...#####...', '.#########.', '.###...###.',
       '####...####', '.###...###.', '.#########.', '...#####...', '..#.###.#..', '.....#.....')


def _runs(rows: tuple[str, ...]) -> tuple[tuple[int, int, int], ...]:
    """(x, y, width) for each horizontal run of '#'."""
    result = []
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            if row[x] != '#':
                x += 1
                continue
            start = x
            while x < len(row) and row[x] == '#':
                x += 1
            result.append((start, y, x-start))
    return tuple(result)


def draw_code(address: int, layout_state: int, open_flag: int, captions: int) -> bytes:
    """Owner tabs, filter button and settings cog; others keep the native draw."""
    from .client_barracks_skin import _rectangle, native_colour
    from .client_equipment_batch import Code

    c = Code(address)
    c.emit('55 89e5 83ec10 9c60 89c6'); c.base()
    c.emit('83bb'); c.word(layout_state); c.emit('01'); c.branch('0f85', 'native')
    c.emit('807e4900'); c.branch('0f84', 'native')
    c.emit('8b464c 3b83'); c.word(OWNERS-BASE); c.branch('0f84', 'owner')
    c.emit('3b83'); c.word(TABS-BASE); c.branch('0f84', 'settings')
    c.emit('3b83'); c.word(TABLE-BASE); c.branch('0f85', 'native')
    c.emit('8b402c 85c0'); c.branch('0f84', 'native')
    c.emit('83780807'); c.branch('0f8e', 'native')
    c.emit('8b4004 3b701c'); c.branch('0f85', 'native')
    c.emit('89f0'); c.call(0xa4211c); c.emit('8945fc')
    c.emit('89f0'); c.call(0xa42140); c.emit('8945f8')
    c.emit('83bb'); c.word(open_flag); c.emit('00'); c.branch('0f85', 'toggle_open')
    c.emit('80be8002000000'); c.branch('0f85', 'toggle_open')
    _frame(c, 0xff3a4148, 0xff161a1e)
    c.branch('e9', 'toggle_mark')
    c.label('toggle_open')
    _frame(c, 0xffe8891f, 0xff20262c)
    c.label('toggle_mark')
    _rectangle(c, (0, ('h', 1, -2), ('w', 1, 0), 2), 0xffc87a22)
    _chevron(c, ('w', 1, -20), 11, 0xffe8891f)
    c.emit('68'); c.word(native_colour(0xffece5b8)); c.emit('6a03 6a00')
    c.emit('8b55fc 83c20a 8b4df8 83c106 8d83'); c.word(captions+len(OWNER_CAPTIONS)*0x40+12)
    c.call(0x67571c)
    c.branch('e9', 'done')

    c.label('owner')
    c.emit('8b402c 85c0'); c.branch('0f84', 'native')
    c.emit('89f0'); c.call(0xa4211c); c.emit('8945fc')
    c.emit('89f0'); c.call(0xa42140); c.emit('8945f8')
    c.emit('80bec902000000'); c.branch('0f85', 'owner_active')
    c.emit('80be8002000000'); c.branch('0f85', 'owner_hover')
    _frame(c, 0xff3a4148, 0xff161a1e)
    c.branch('e9', 'owner_caption')
    c.label('owner_hover')
    _frame(c, 0xff6d5632, 0xff1d2226)
    c.branch('e9', 'owner_caption')
    c.label('owner_active')
    _frame(c, 0xffe8891f, 0xff2a2418)
    _rectangle(c, (1, ('h', 1, -3), ('w', 1, -2), 2), 0xffe8891f)
    c.label('owner_caption')
    c.emit('8b464c 8b402c 8b4004')
    for index, caption in enumerate(OWNER_CAPTIONS):
        c.emit('3b70'+f'{index*4:02x}'); c.branch('0f85', f'owner_next_{index}')
        c.emit('68'); c.word(native_colour(0xffece5b8)); c.emit('6a00 6a00')
        c.emit('8b5638 81ea'); c.word(len(caption)*7)
        c.emit('d1fa 0355fc 8b4df8 83c107 8d83')
        c.word(captions+index*0x40+12)
        c.call(0x67571c)
        c.branch('e9', 'done')
        c.label(f'owner_next_{index}')
    c.label('settings')
    c.emit('8b402c 85c0'); c.branch('0f84', 'native')
    c.emit('83780802'); c.branch('0f8e', 'native')
    c.emit('8b4004 3b70'+f'{SETTINGS*4:02x}'); c.branch('0f85', 'native')
    c.emit('89f0'); c.call(0xa4211c); c.emit('8945fc')
    c.emit('89f0'); c.call(0xa42140); c.emit('8945f8')
    c.emit('80be8002000000'); c.branch('0f85', 'settings_hover')
    _frame(c, 0xff6d5632, 0xff161a1e)
    c.branch('e9', 'settings_cog')
    c.label('settings_hover')
    _frame(c, 0xffe8891f, 0xff2a2418)
    c.label('settings_cog')
    for x, y, width in _runs(COG):
        _rectangle(c, (x+2, y+2, width, 1), 0xffe8891f)
    c.label('done'); c.emit('619d 89ec5dc3')
    c.label('native'); c.emit('619d 89ec5d'); c.jump(BUTTON_DRAW)
    return c.finish(0x2000)


def payload(origin: int, layout_state: int, open_flag: int) -> bytes:
    from .client_barracks_skin import caption_literal

    result = bytearray(SIZE)
    apply = BASE+origin+0x200
    result[0:0x100] = click_code(BASE+origin, layout_state, open_flag, apply)
    result[0x200:0x300] = apply_code(apply, layout_state, open_flag)
    for offset, build in ((0x300, lambda at: toggle_down_code(at, layout_state)),
                          (0x400, lambda at: grid_move_code(at, layout_state, open_flag)),
                          (0x500, lambda at: grid_down_code(at, layout_state, open_flag, apply)),
                          (0x600, lambda at: filters_down_code(at, layout_state, open_flag, apply))):
        result[offset:offset+0x100] = build(BASE+origin+offset)
    result[0x800:0xa00] = filters_draw_code(BASE+origin+0x800, layout_state, open_flag)
    result[0x1000:0x3000] = draw_code(BASE+origin+0x1000, layout_state, open_flag, origin+0x5000)
    for index, caption in enumerate(OWNER_CAPTIONS+(FILTER_CAPTION,)):
        raw = caption_literal(caption)
        at = 0x5000+index*0x40
        result[at:at+len(raw)] = raw
    return bytes(result)


def apply_entry(origin: int) -> int:
    return BASE+origin+0x200


def draw_entry(origin: int) -> int:
    return BASE+origin+0x1000


VMT_HOOKS = ((BUTTON_DOWN, 0x300), (GRID_MOVE, 0x400), (GRID_DOWN, 0x500),
             (FILTERS_DOWN, 0x600), (FILTERS_DRAW, 0x800))


def edits(origin: int) -> tuple[tuple[int, bytes, bytes], ...]:
    site = CLICK_SITE
    result = [(site, b'\xe8'+struct.pack('<i', CLICK-site-5),
               b'\xe8'+struct.pack('<i', BASE+origin-site-5))]
    for (slot, method), offset in VMT_HOOKS:
        result.append((slot, struct.pack('<I', method), struct.pack('<I', BASE+origin+offset)))
    return tuple(result)
