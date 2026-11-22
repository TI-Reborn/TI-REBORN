"""Draw flat barracks skill controls over the native docked page."""
from __future__ import annotations

import hashlib

import pefile

from .client_barracks_a2 import BASE, INFO, STATE
from .client_barracks_skin import _rectangle, native_colour
from .client_barracks_skills import PANEL_WIDTH, SKILL_TAB
from .client_equipment_batch import Code

SOURCE_SHA = 'd1f15a72886164262ba8afa52613abd4e6701acab55f9d0715ebf1d47f2de892'
ABILITY_TAB = 0xad1080
PANEL_PAINT, TAB_PAINT, ROW_PAINT, GAUGE_PAINT = 0xa4d44c, 0xa512b4, 0xa51dd4, 0xa4881b
PANEL_ENTRY, TAB_ENTRY, ROW_ENTRY, GAUGE_ENTRY = 0xcb5100, 0xcb5340, 0xcb5540, 0xcb5600
FOOTER_CALL, ABILITY_LIST_CALL = 0x9acca2, 0x9acd58
FOOTER_ENTRY, ABILITY_LIST_ENTRY = 0xcb5780, 0xcb5790
FRAME, BODY = 0xff42494a, 0xff1a1f24
GUTTER, TRACK_WIDTH, NATIVE_TRACK = 16, 183, 196
TAB_WIDTH = PANEL_WIDTH // 2


def _docked(c: Code) -> None:
    # Preserve the native paint arguments and identify the particular docked panel.
    c.emit('9c60')
    c.base()
    c.emit('83bb'); c.word(STATE); c.emit('01'); c.branch('0f85', 'stock')
    c.emit('8b93'); c.word(SKILL_TAB - BASE)
    c.emit('85d2'); c.branch('0f84', 'stock')
    c.emit('8b7a4c 85ff'); c.branch('0f84', 'stock')
    c.emit('8b8b'); c.word(INFO - BASE)
    c.emit('85c9'); c.branch('0f84', 'stock')
    c.emit('8b494c 85c9'); c.branch('0f84', 'stock')
    c.emit('394f4c'); c.branch('0f85', 'stock')


def _skill_content(c: Code, saved_widget: str) -> None:
    c.emit(saved_widget)
    c.emit('8b404c 85c0'); c.branch('0f84', 'stock')
    c.emit('39504c'); c.branch('0f85', 'stock')


def _origin(c: Code) -> None:
    # ESI is the paint target. Match the coordinate locals used by _rectangle.
    c.emit('83ec10 8d6c2410 89f0'); c.call(0xa4211c); c.emit('8945fc')
    c.emit('89f0'); c.call(0xa42140); c.emit('8945f8')


def _stock(c: Code, hook: int, original: str) -> None:
    c.label('stock')
    c.emit('619d')
    c.emit(original)
    c.jump(hook + len(bytes.fromhex(original)))


def panel_code() -> bytes:
    c = Code(PANEL_ENTRY)
    _docked(c)
    c.emit('8b74241c 39fe'); c.branch('0f85', 'stock')
    c.emit('89d3')
    _origin(c)
    c.emit('80bb 80020000 00'); c.branch('0f84', 'abilities')
    _rectangle(c, (0, 5, PANEL_WIDTH, 291), FRAME)
    _rectangle(c, (1, 6, PANEL_WIDTH - 2, 289), BODY)
    _rectangle(c, (GUTTER, 250, 205, 1), 0xff333b40)
    c.branch('e9', 'done')
    c.label('abilities')
    _rectangle(c, (0, 5, PANEL_WIDTH, 263), FRAME)
    _rectangle(c, (1, 6, PANEL_WIDTH - 2, 261), BODY)
    c.label('done')
    c.emit('83c410 619dc3')
    _stock(c, PANEL_PAINT, '558bec 53 8bd8')
    return c.finish(TAB_ENTRY - PANEL_ENTRY)


def tabs_code() -> bytes:
    c = Code(TAB_ENTRY)
    _docked(c)
    c.emit('8b74241c 39d6'); c.branch('0f84', 'recognized')
    c.emit('3bb3'); c.word(ABILITY_TAB - BASE); c.branch('0f85', 'stock')
    c.label('recognized')
    c.emit('397e4c'); c.branch('0f85', 'stock')
    c.emit('80be bc020000 00'); c.branch('0f85', 'stock')
    # Native input uses these same header offsets and widths.
    c.emit('31c0 39d6'); c.branch('0f84', 'first')
    c.emit(f'b0{TAB_WIDTH:02x}')
    c.label('first')
    c.emit('8986 b4020000 c786 b8020000'); c.word(TAB_WIDTH)
    _origin(c)
    c.emit('8b86 b4020000 0145fc')
    _rectangle(c, (1, 1, TAB_WIDTH - 1, 23), FRAME)
    c.emit('80be 80020000 00'); c.branch('0f84', 'inactive')
    _rectangle(c, (2, 2, TAB_WIDTH - 3, 21), 0xff292721)
    _rectangle(c, (2, 22, TAB_WIDTH - 3, 2), 0xffc88335)
    c.emit('b8'); c.word(native_colour(0xffeee2be)); c.branch('e9', 'caption')
    c.label('inactive')
    _rectangle(c, (2, 2, TAB_WIDTH - 3, 21), 0xff20262b)
    c.emit('b8'); c.word(native_colour(0xffbac1bd))
    c.label('caption')
    c.emit('8b4dfc 83c10e 8b55f8 83c205 52 50 8b565c b801000000'); c.call(0x4f29a8)
    c.emit('83c410 619dc3')
    _stock(c, TAB_PAINT, '558bec 83c4cc')
    return c.finish(ROW_ENTRY - TAB_ENTRY)


def row_code() -> bytes:
    c = Code(ROW_ENTRY)
    _docked(c)
    _skill_content(c, '8b44241c')
    c.emit('619dc3')
    _stock(c, ROW_PAINT, '558bec 53 8bd8')
    return c.finish(GAUGE_ENTRY - ROW_ENTRY)


def _fill(c: Code, local: str, colour: int, end: str) -> None:
    # Stock paint already computed current / maximum and the optional overlay.
    c.emit(f'8b45{local} 85c0'); c.branch('0f8e', end)
    c.emit('69c0'); c.word(TRACK_WIDTH)
    c.emit('31d2 b9'); c.word(NATIVE_TRACK)
    c.emit('f7f1 b9'); c.word(TRACK_WIDTH)
    c.emit('39c8 0f4fc1 89c1')
    c.emit('6a04 6a00 68'); c.word(native_colour(colour))
    c.emit('6802010000 8b45fc 8b55f8 83c204')
    c.call(0x4f2888)
    c.label(end)


def gauge_code() -> bytes:
    c = Code(GAUGE_ENTRY)
    _docked(c)
    _skill_content(c, '8b442410')
    # Take the absolute coordinates and fill widths from the native frame.
    c.emit('8b45fc 8b55f8 8b4c2404 8b742400 83ec10 8d6c2410')
    c.emit('8945f4 8955f0 894dfc 8975f8')
    _rectangle(c, (0, 4, TRACK_WIDTH, 4), 0xff343c41)
    _fill(c, 'f0', 0xff657e75, 'overlay_done')
    _fill(c, 'f4', 0xffb58c4f, 'fill_done')
    c.emit('83c410 619d')
    c.jump(0xa48aee)
    _stock(c, GAUGE_PAINT, '80bb c8020000 00')
    return c.finish(0x180)


def inset_code(entry: int, native_constructor: int, x: int) -> bytes:
    c = Code(entry)
    c.emit('b9'); c.word(x)
    c.jump(native_constructor)
    return c.finish(0x10)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected the verified barracks skills layout')
    candidate = bytearray(source)
    hooks = ((PANEL_PAINT, PANEL_ENTRY, panel_code()), (TAB_PAINT, TAB_ENTRY, tabs_code()),
             (ROW_PAINT, ROW_ENTRY, row_code()), (GAUGE_PAINT, GAUGE_ENTRY, gauge_code()))
    constructors = (
        (FOOTER_CALL, FOOTER_ENTRY, inset_code(FOOTER_ENTRY, 0xa4d58c, GUTTER)),
        (ABILITY_LIST_CALL, ABILITY_LIST_ENTRY, inset_code(ABILITY_LIST_ENTRY, 0x8aeb0c, 5)),
    )
    with pefile.PE(data=source, fast_load=True) as pe:
        for hook, entry, code in (*hooks, *constructors):
            at = pe.get_offset_from_rva(entry - BASE)
            if any(source[at:at + len(code)]):
                raise ValueError('Reserved skills skin space is in use')
            candidate[at:at + len(code)] = code
            at = pe.get_offset_from_rva(hook - BASE)
            redirect = Code(hook)
            if hook in (FOOTER_CALL, ABILITY_LIST_CALL):
                redirect.call(entry)
            else:
                redirect.jump(entry)
            candidate[at:at + len(redirect.data)] = redirect.data
    return bytes(candidate)
