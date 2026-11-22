"""Dock the native chat over the extended warehouse without rebuilding its tabs."""
from __future__ import annotations

import hashlib
import struct

import pefile

from .client_barracks_a2 import BASE, INFO, STATE, TABLE, _child, _global
from .client_barracks_skin import _rectangle, native_colour
from .client_equipment_batch import Code
from .client_ui_scale import INVENTORY_FOOTER, INVENTORY_VIEW

SOURCE_SHA = 'cfee6098302be50715f92184430cd9039da4aba81d601bd5054ccb35f049d923'
CHAT_VMT = 0xa00704
GRID = 0xac4bd8
GUI_MANAGER = 0xac622c
SCREEN_HEIGHT = 0xac5e60
MOUSE_X, MOUSE_Y = 0xac5b70, 0xac5a04
DOCK_HEIGHT, BAND_TOP = 52, 24
ARROW_X, ARROW_Y, ARROW_W, ARROW_H = 42, 27, 28, 20
FRAME_DRAW, CHAT_DRAW, AREA_DRAW = 0xa3f400, 0xa08998, 0xa4d724
MOUSE_DOWN, TAB_SELECT, TAB_AUTO_FOCUS = 0xa3f7e0, 0xa5050d, 0xa4faaf
FRAME, CHAT, AREA, BUTTON, TAB, FOCUS, SKIN = (
    0xcb6000, 0xcb6500, 0xcb6b00, 0xcb6c00, 0xcb6e00, 0xcb6f00, 0xcb7000,
)
STORAGE = 0xcb7200 - BASE
OPEN_DEFAULT, BACKDROP = 0xcb7300, 0xcb7500
AUTO_FOCUS = 0xcb7700
SET_UNREAD, KEEP_UNREAD, BLINK_UNREAD = 0xcb7800, 0xcb7900, 0xcb7a00
RELEASE_EDIT = 0xcb7b00
ACTIVE, EXPANDED, CHAT_Y, DRAWN_Y, PAGE, PAGE_H, DRAWN_H = (
    STORAGE + offset for offset in range(0, 28, 4)
)


def _get(c: Code, register: str, displacement: int) -> None:
    c.emit({'eax': '8b83', 'ecx': '8b8b', 'edx': '8b93', 'esi': '8bb3',
            'edi': '8bbb'}[register]); c.word(displacement)


def _put(c: Code, register: str, displacement: int) -> None:
    c.emit({'eax': '8983', 'ecx': '898b', 'edx': '8993', 'esi': '89b3',
            'edi': '89bb'}[register]); c.word(displacement)


def _stock(c: Code, address: int, original: str) -> None:
    c.label('stock')
    c.emit('619d')
    c.emit(original)
    c.jump(address + len(bytes.fromhex(original)))


def frame_code(*, layout: int = BACKDROP, restore: int | None = None,
               with_information: bool = False) -> bytes:
    c = Code(FRAME)
    c.emit('9c60'); c.base()
    c.emit('83ec0c 8d6c240c')
    # Store the incoming manager before looking at the live squad page.
    c.emit('8b451c 8945fc 31c0 8945f8 8945f4')
    c.emit('83bb'); c.word(STATE); c.emit('01'); c.branch('0f85', 'lookup')
    _global(c, TABLE, 'lookup')
    c.emit('8b784c 85ff'); c.branch('0f84', 'lookup')
    c.emit('897df4 807f4900'); c.branch('0f84', 'lookup')
    c.emit('80784900')
    if with_information:
        c.branch('0f85', 'barracks_page')
        _get(c, 'edx', INFO-BASE)
        c.emit('85d2'); c.branch('0f84', 'lookup')
        c.emit('397a4c'); c.branch('0f85', 'lookup')
        c.emit('807a4900')
    c.branch('0f84', 'lookup')
    c.label('barracks_page')
    c.emit('8d93'); c.word(0xa31a40 - BASE)
    c.emit('3917'); c.branch('0f85', 'lookup')
    c.emit('8945f8')
    c.label('lookup')
    # Walk the manager's live window list rather than dereferencing a saved widget.
    c.emit('837df800'); c.branch('0f85', 'find')
    c.emit('83bb'); c.word(ACTIVE); c.emit('00'); c.branch('0f84', 'done')
    c.label('find')
    c.emit('8b45fc 8b8080020000 85c0'); c.branch('0f84', 'missing')
    c.emit('8b4808 8b5004 8dbb'); c.word(CHAT_VMT - BASE)
    c.label('window')
    c.emit('85c9'); c.branch('0f8e', 'missing')
    c.emit('8b02 3938'); c.branch('0f84', 'found')
    c.emit('83c204 49'); c.branch('e9', 'window')
    c.label('found')
    c.emit('89c6 837df800'); c.branch('0f84', 'leave')
    c.emit('807e4900'); c.branch('0f84', 'leave')
    _get(c, 'eax', ACTIVE); c.emit('39f0'); c.branch('0f84', 'chat_saved')
    _put(c, 'esi', ACTIVE)
    c.emit('31c0'); _put(c, 'eax', EXPANDED)
    c.emit('8b4634'); _put(c, 'eax', CHAT_Y); _put(c, 'eax', DRAWN_Y)
    c.label('chat_saved')
    _get(c, 'eax', DRAWN_Y)
    c.emit('394634'); c.branch('0f84', 'place_chat')
    c.emit('8b4634'); _put(c, 'eax', CHAT_Y)
    c.label('place_chat')
    _get(c, 'edx', SCREEN_HEIGHT - BASE)
    c.emit('8b12 b8'); c.word(DOCK_HEIGHT)
    c.emit('83bb'); c.word(EXPANDED); c.emit('00'); c.branch('0f84', 'dock')
    c.emit('8b463c')
    c.label('dock')
    c.emit('29c2 895634'); _put(c, 'edx', DRAWN_Y)
    c.emit('8b7df4 8b8694020000 3b8794020000'); c.branch('0f8d', 'size_page')
    c.emit('89f0'); c.call(0xa43720)

    c.label('size_page')
    _get(c, 'eax', PAGE)
    c.emit('39f8'); c.branch('0f85', 'save_height')
    _get(c, 'eax', DRAWN_H)
    c.emit('39473c'); c.branch('0f84', 'page_saved')
    c.label('save_height')
    c.emit('8b473c'); _put(c, 'edi', PAGE); _put(c, 'eax', PAGE_H)
    c.label('page_saved')
    _get(c, 'eax', SCREEN_HEIGHT - BASE)
    c.emit(f'8b00 2b4734 83e8{DOCK_HEIGHT:02x}')
    _get(c, 'edx', PAGE_H)
    c.emit('39d0 0f4cc2 89473c'); _put(c, 'eax', DRAWN_H)
    # The table bottom uses the full docked viewport. Move its footer and
    # refresh the stock item-grid scrollbar without changing item selection.
    _get(c, 'ecx', SCREEN_HEIGHT - BASE)
    c.emit(f'8b09 2b4f34 83e9{DOCK_HEIGHT:02x} 8b75f8 2b4e34')
    c.emit('81f9f0000000'); c.branch('0f8c', 'backdrop')
    c.emit('89cf 2b7e3c'); c.branch('0f84', 'backdrop')
    c.emit('8b5638 89f0'); c.call(INVENTORY_FOOTER)
    _global(c, GRID, 'backdrop')
    c.emit('39704c'); c.branch('0f85', 'backdrop')
    c.emit('89c6')
    c.emit('8b5038 8b483c 01f9'); c.call(INVENTORY_VIEW)
    # The native search controls sit beside the counter, just below the grid.
    c.emit('8b7e34 037e3c')
    for index, inset in ((13, 1), (14, 5)):
        skip = f'search_{index}'
        _child(c, TABLE, index, skip)
        c.emit(f'8d57{inset:02x} 895034')
        c.label(skip)
    c.label('backdrop')
    _get(c, 'esi', ACTIVE)
    c.call(layout)
    c.branch('e9', 'done')

    c.label('leave')
    _get(c, 'eax', ACTIVE); c.emit('39f0'); c.branch('0f85', 'missing')
    _get(c, 'eax', DRAWN_Y)
    c.emit('394634'); c.branch('0f85', 'missing')
    _get(c, 'eax', CHAT_Y); c.emit('894634')
    c.label('missing')
    _get(c, 'eax', PAGE)
    c.emit('3b45f4'); c.branch('0f85', 'reset')
    c.emit('85c0'); c.branch('0f84', 'reset')
    _get(c, 'edx', DRAWN_H)
    c.emit('39503c'); c.branch('0f85', 'reset')
    _get(c, 'edx', PAGE_H); c.emit('89503c')
    c.label('reset')
    c.emit('31c0'); _put(c, 'eax', ACTIVE); _put(c, 'eax', PAGE)
    if restore is not None:
        c.call(restore)
    c.label('done'); c.emit('83c40c')
    _stock(c, FRAME_DRAW, '558bec 83c4ec')
    return c.finish(CHAT - FRAME)


def _focused_edit_code() -> bytes:
    c = Code(FOCUS)
    _get(c, 'eax', GUI_MANAGER - BASE)
    c.emit('8b00 8b8098020000 85c0'); c.branch('0f84', 'done')
    c.emit('8d8b'); c.word(0xa2fbd4 - BASE)
    c.emit('3908'); c.branch('0f85', 'no')
    c.emit('89c2')
    c.label('parent')
    c.emit('8b404c 85c0'); c.branch('0f84', 'done')
    c.emit('39f0'); c.branch('0f85', 'parent')
    c.emit('89d0 c3')
    c.label('no'); c.emit('31c0')
    c.label('done'); c.emit('c3')
    return c.finish(SKIN - FOCUS)


def release_edit_code() -> bytes:
    c = Code(RELEASE_EDIT)
    c.call(FOCUS)
    c.emit('85c0'); c.branch('0f84', 'done')
    c.emit('31d2'); c.call(0xa45be4)
    _get(c, 'edx', 0xac58dc - BASE)
    c.emit('c60200')
    c.label('done')
    c.emit('c3')
    return c.finish(0x100)


def _chat_body(c: Code, opacity: int, *, collapsed: bool = False) -> None:
    c.emit(f'6a{DOCK_HEIGHT - BAND_TOP:02x}' if collapsed else 'ff763c')
    c.emit('6a00 68'); c.word(native_colour((opacity << 24) | 0x171d22))
    c.emit('6802010000 8b4630 8b5634 8b4e38')
    if collapsed:
        c.emit(f'83c2{BAND_TOP:02x}')
    c.call(0x4f2888)
    c.emit('6a01 6a00 68'); c.word(native_colour(0xff514735 if collapsed else 0xff685234))
    c.emit('6802010000 8b4630 8b5634 8b4e38')
    if collapsed:
        c.emit(f'83c2{BAND_TOP:02x}')
    c.call(0x4f2888)


def chat_code() -> bytes:
    c = Code(CHAT)
    c.emit('9c60'); c.base()
    c.emit('8b74241c 3bb3'); c.word(ACTIVE); c.branch('0f85', 'stock')
    c.emit('807e4900'); c.branch('0f84', 'stock')
    c.emit('83bb'); c.word(EXPANDED); c.emit('00'); c.branch('0f84', 'collapsed')
    _get(c, 'eax', MOUSE_Y - BASE)
    c.emit('8b00 3b4634'); c.branch('0f8d', 'opaque')
    c.call(FOCUS); c.emit('85c0'); c.branch('0f85', 'opaque')
    _chat_body(c, 0xa6)
    c.branch('e9', 'native')
    c.label('opaque')
    _chat_body(c, 0xff)
    c.branch('e9', 'native')
    c.label('collapsed')
    _chat_body(c, 0xff, collapsed=True)
    c.label('native')
    c.emit('89f0'); c.call(0xa42a34)
    # Draw the arrow last so native memo and skin layers cannot cover it.
    c.emit(f'83ec08 8d6c2408 8b4638 034630 83e8{ARROW_X:02x} 8945fc')
    _get(c, 'eax', SCREEN_HEIGHT - BASE)
    c.emit(f'8b00 83e8{ARROW_Y:02x} 8945f8')
    _rectangle(c, (0, 0, ARROW_W, ARROW_H), 0xff8b6b40)
    _rectangle(c, (1, 1, ARROW_W - 2, ARROW_H - 2), 0xff252829)
    c.emit('83bb'); c.word(EXPANDED); c.emit('00'); c.branch('0f85', 'down')
    for y in range(6):
        _rectangle(c, (13-y, 7+y, 2+2*y, 1), 0xffead09a)
    c.branch('e9', 'done')
    c.label('down')
    for y in range(6):
        _rectangle(c, (8+y, 7+y, 12-2*y, 1), 0xffead09a)
    c.label('done')
    c.emit('83c408 619dc3')
    _stock(c, CHAT_DRAW, '558bec 83783c00')
    return c.finish(AREA - CHAT)


def area_code() -> bytes:
    c = Code(AREA)
    c.emit('9c60'); c.base()
    _get(c, 'edx', ACTIVE); c.emit('85d2'); c.branch('0f84', 'stock')
    c.emit('39504c'); c.branch('0f85', 'stock')
    c.emit('83783800'); c.branch('0f8e', 'stock')
    c.emit('619dc3')
    _stock(c, AREA_DRAW, '558bec 51 53')
    return c.finish(BUTTON - AREA)


def button_code(*, release_covered_focus: bool = False) -> bytes:
    c = Code(BUTTON)
    c.emit('9c60'); c.base()
    _get(c, 'esi', ACTIVE); c.emit('85f6'); c.branch('0f84', 'stock')
    c.emit('807c241400'); c.branch('0f85', 'stock')
    c.emit('8b44241c 83b8d802000000'); c.branch('0f85', 'stock')
    _get(c, 'eax', MOUSE_X - BASE)
    c.emit(f'8b00 2b4630 2b4638 83c0{ARROW_X:02x} 83f8{ARROW_W:02x}')
    c.branch('0f83', 'stock')
    _get(c, 'eax', MOUSE_Y - BASE)
    _get(c, 'edx', SCREEN_HEIGHT - BASE)
    c.emit(f'8b00 2b02 83c0{ARROW_Y:02x} 83f8{ARROW_H:02x}')
    c.branch('0f83', 'stock')
    c.emit('83b3'); c.word(EXPANDED); c.emit('01'); c.branch('0f84', 'clear_focus')
    c.call(OPEN_DEFAULT)
    if release_covered_focus:
        c.emit('56')
        _get(c, 'esi', PAGE)
        c.call(RELEASE_EDIT)
        c.emit('5e')
    c.label('clear_focus')
    if release_covered_focus:
        c.call(RELEASE_EDIT)
    else:
        c.call(FOCUS); c.emit('85c0'); c.branch('0f84', 'handled')
        c.emit('31d2'); c.call(0xa45be4)
        _get(c, 'edx', 0xac58dc - BASE); c.emit('c60200')
    c.label('handled'); c.emit('619d b801000000 c20400')
    _stock(c, MOUSE_DOWN, '558bec 51 53 56')
    return c.finish(TAB - BUTTON)


def auto_focus_code() -> bytes:
    c = Code(AUTO_FOCUS)
    c.emit('9c60'); c.base()
    _get(c, 'edx', ACTIVE); c.emit('85d2'); c.branch('0f84', 'stock')
    c.label('parent')
    c.emit('85c0'); c.branch('0f84', 'stock')
    c.emit('39d0'); c.branch('0f84', 'visible_tab')
    c.emit('8b404c'); c.branch('e9', 'parent')
    c.label('visible_tab')
    # Selecting a page can happen again in the game loop after a toggle.
    # Only clicking the actual input field should activate typing here.
    c.emit('619d'); c.jump(0xa4fabc)
    c.label('stock')
    c.emit('619d'); c.call(0xa45be4); c.jump(TAB_AUTO_FOCUS+5)
    return c.finish(0x100)


def tab_code(*, release_covered_focus: bool = False) -> bytes:
    c = Code(TAB)
    c.emit('9c60'); c.base()
    _get(c, 'eax', ACTIVE); c.emit('85c0'); c.branch('0f84', 'stock')
    c.emit('8b55fc 39424c'); c.branch('0f85', 'stock')
    # A click on a native tab opens its messages before the unread flag clears.
    if release_covered_focus:
        c.emit('83bb'); c.word(EXPANDED); c.emit('00'); c.branch('0f85', 'stock')
        _get(c, 'esi', PAGE)
        c.call(RELEASE_EDIT)
    c.emit('c783'); c.word(EXPANDED); c.word(1)
    _stock(c, TAB_SELECT, '55 0fb7de 89d8')
    return c.finish(FOCUS - TAB)


def open_default_code() -> bytes:
    c = Code(OPEN_DEFAULT)
    # Preserve the native active tab. Only use Global when none is selected.
    c.emit('9c60 8b462c 85c0'); c.branch('0f84', 'done')
    c.emit('8b4808 8b5004 8dbb'); c.word(0xa34c48 - BASE)
    c.label('control')
    c.emit('85c9'); c.branch('0f8e', 'done')
    c.emit('8b02 3938'); c.branch('0f84', 'pages')
    c.emit('83c204 49'); c.branch('e9', 'control')
    c.label('pages')
    c.emit('89c7 8b402c 85c0'); c.branch('0f84', 'done')
    c.emit('8b4808 8b5004 85c9'); c.branch('0f8e', 'done')
    c.emit('8b02 83b8780200000c'); c.branch('0f85', 'done')
    c.emit('80784900'); c.branch('0f84', 'done')
    c.label('page')
    c.emit('8b02 80784a00'); c.branch('0f85', 'selected')
    c.emit('83c204 49'); c.branch('0f85', 'page')
    c.emit('8b4734 83c025 50 8b4f30 83c146 31d2 89f8')
    c.call(0xa50240)
    c.branch('e9', 'done')
    c.label('selected')
    c.emit('c6808d02000000')
    c.label('done'); c.emit('619dc3')
    return c.finish(BACKDROP - OPEN_DEFAULT)


def backdrop_code() -> bytes:
    c = Code(BACKDROP)
    # The old chassis ended behind the original chat. Extend the dark surface
    # below it before the warehouse and overlay are painted.
    c.emit('55 89e5 83ec10')
    _get(c, 'eax', SCREEN_HEIGHT - BASE)
    c.emit('8b00 2b463c 8945f8 c745fc00000000')
    c.emit('8b463c 8945f4')
    c.emit('ff75f4 6a00 68'); c.word(native_colour(0xff1b2026))
    c.emit('6802010000 31c0 8b55f8 8b4e38')
    c.call(0x4f2888)
    c.emit('8b4638 83e812 8945fc')
    for x, colour in ((1, 0xff2d343a), (2, 0xff43423b)):
        c.emit('ff75f4 6a00 68'); c.word(native_colour(colour))
        c.emit(f'6802010000 b8{x + 14:02x}000000 8b55f8 b901000000')
        c.call(0x4f2888)
        c.emit('ff75f4 6a00 68'); c.word(native_colour(colour))
        c.emit(f'6802010000 8b45fc 83c0{x:02x} 8b55f8 b901000000')
        c.call(0x4f2888)
    c.emit('89ec5dc3')
    return c.finish(0x200)


def skin_height_code(address: int, inset: int) -> bytes:
    c = Code(address)
    c.emit('83bb'); c.word(ACTIVE); c.emit('00'); c.branch('0f84', 'original')
    _get(c, 'edx', TABLE - BASE)
    c.emit('8b523c')
    if inset:
        c.emit('83ea02')
    c.emit('c3')
    c.label('original')
    c.emit('81c2'); c.word(-124-inset); c.emit('c3')
    return c.finish(0x40)


def _collapsed_page(c: Code, saved_page: str) -> None:
    c.emit('9c60'); c.base()
    c.emit('83bb'); c.word(EXPANDED); c.emit('00'); c.branch('0f85', 'stock')
    _get(c, 'edx', ACTIVE); c.emit('85d2'); c.branch('0f84', 'stock')
    c.emit(saved_page)
    c.emit('8b404c 85c0'); c.branch('0f84', 'stock')
    c.emit('39504c'); c.branch('0f85', 'stock')


def set_unread_code() -> bytes:
    c = Code(SET_UNREAD)
    _collapsed_page(c, '8b442404')
    # The selected tab is still behind the dock, including when a new message
    # arrives in the very conversation that was open before collapsing.
    c.emit('619d'); c.jump(0xa4f7e5)
    c.label('stock')
    c.emit('619d 807e4a00'); c.branch('0f85', 'read')
    c.jump(0xa4f7e5)
    c.label('read'); c.jump(0xa4f7e9)
    return c.finish(0x100)


def keep_unread_code() -> bytes:
    c = Code(KEEP_UNREAD)
    _collapsed_page(c, '8b442404')
    c.emit('619d'); c.jump(0xa4faa3)
    _stock(c, 0xa4fa9c, 'c6868d02000000')
    return c.finish(0x100)


def blink_unread_code() -> bytes:
    c = Code(BLINK_UNREAD)
    _collapsed_page(c, '8b44241c')
    c.emit('619d'); c.jump(0xa50948)
    c.label('stock')
    c.emit('619d 80784a00'); c.branch('0f85', 'read')
    c.jump(0xa50948)
    c.label('read'); c.jump(0xa50980)
    return c.finish(0x100)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected the verified docked skills skin')
    candidate = bytearray(source)
    with pefile.PE(data=source, fast_load=True) as pe:
        def write(address: int, value: bytes, *, unused: bool = False) -> None:
            offset = pe.get_offset_from_rva(address - BASE)
            if unused and any(source[offset:offset + len(value)]):
                raise ValueError(f'Reserved chat code in use at {address:#x}')
            candidate[offset:offset + len(value)] = value

        for hook, entry, code in (
            (FRAME_DRAW, FRAME, frame_code()), (CHAT_DRAW, CHAT, chat_code()),
            (AREA_DRAW, AREA, area_code()), (MOUSE_DOWN, BUTTON, button_code()),
            (TAB_SELECT, TAB, tab_code()), (TAB_AUTO_FOCUS, AUTO_FOCUS, auto_focus_code()),
            (0xa4f7df, SET_UNREAD, set_unread_code()), (0xa4fa9c, KEEP_UNREAD, keep_unread_code()),
            (0xa50942, BLINK_UNREAD, blink_unread_code()),
        ):
            write(entry, code, unused=True)
            redirect = Code(hook)
            redirect.jump(entry)
            write(hook, redirect.data)
        write(FOCUS, _focused_edit_code(), unused=True)
        write(BASE+STORAGE, bytes(DRAWN_H+4-STORAGE), unused=True)
        write(OPEN_DEFAULT, open_default_code(), unused=True)
        write(BACKDROP, backdrop_code(), unused=True)
        for inset, addresses in (
            (0, (0xcb0257, 0xcb1227, 0xcb21f7, 0xcb31bf, 0xcb4187)),
            (2, (0xcb02bd, 0xcb128d, 0xcb225d, 0xcb3225, 0xcb41ed)),
        ):
            entry = SKIN + 0x20*inset
            write(entry, skin_height_code(entry, inset), unused=True)
            for address in addresses:
                extra = struct.pack('<i', -124-inset)
                if pe.get_data(address - BASE, 6) != b'\x81\xc2'+extra:
                    raise ValueError(f'Warehouse frame guard failed at {address:#x}')
                redirect = Code(address)
                redirect.call(entry)
                write(address, redirect.data + b'\x90')
    return bytes(candidate)
