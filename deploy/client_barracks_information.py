"""Fit the native rating and achievement controls to the New barracks panel."""
from __future__ import annotations

import hashlib

import pefile

from . import client_barracks_preview as preview
from . import client_warehouse_chat as chat
from .client_barracks_a2 import BASE, INFO, STATE, TABLE, _child, _global
from .client_barracks_skin import native_colour
from .client_barracks_skills_skin import PANEL_PAINT
from .client_barracks_wide_warehouse import PAINT, REQUESTED
from .client_equipment_batch import Code

SOURCE_SHA = '0e10bf669399fe69e3c6b888599051de500070e035025350ff0228f73aa3ba8a'
REFLOW, ROW, DOTS, VALUE, SPRITE, SHADE = (
    0xcc6000, 0xcc6600, 0xcc6700, 0xcc6780, 0xcc6800, 0xcc6900,
)
RATING, ACHIEVEMENTS, GRID = 0xad1084, 0xad108c, 0xac4bb8
RATING_WIDTH, ROW_PITCH = 0xcc6a00-BASE, 0xcc6a04-BASE
TICK = 0xcc6b00
MARGIN, CONTENT_MARGIN, STATS_TOP = 12, 12, 164


def _check_mode(c: Code, fallback: str) -> None:
    c.emit('83bb'); c.word(STATE); c.emit('01')
    c.branch('0f85', fallback)


def _set_field(c: Code, offset: int, value: int) -> None:
    c.emit(f'c740{offset:02x}'); c.word(value)


def tick_code() -> bytes:
    """Reuse the inventory layout and give its right column to Information."""
    c = Code(TICK)
    c.emit('9c60')
    _global(c, INFO, 'inventory')
    c.emit('80784900'); c.branch('0f84', 'inventory')
    c.emit('89c7')
    _global(c, TABLE, 'inventory')
    c.emit('8b504c 39574c'); c.branch('0f85', 'inventory')
    c.emit('80784900'); c.branch('0f85', 'inventory')
    c.emit('c783'); c.word(REQUESTED); c.word(0)
    c.emit('89c6')
    c.call(preview.TICK)
    for offset in (0x30, 0x34, 0x38, 0x3c):
        c.emit(f'8b56{offset:02x} 8957{offset:02x}')
    c.emit('619dc3')
    c.label('inventory')
    c.emit('619d'); c.jump(preview.TICK)
    return c.finish(0x100)


def reflow_code() -> bytes:
    c = Code(REFLOW)
    c.emit('9c60'); c.base()
    _check_mode(c, 'done')
    _global(c, INFO, 'done')
    c.emit('3944241c'); c.branch('0f85', 'done')
    c.emit('8b7838 8b703c 81ff4c010000'); c.branch('0f8c', 'done')
    c.emit('81fe30010000'); c.branch('0f8c', 'done')
    c.emit(f'83ef{2*MARGIN:02x} 83ee{2*MARGIN:02x}')
    _global(c, RATING, 'done')
    c.emit('8b404c 85c0'); c.branch('0f84', 'done')
    _set_field(c, 0x30, MARGIN)
    _set_field(c, 0x34, MARGIN)
    c.emit('897838 89703c 897844 897040')
    for page in (RATING, ACHIEVEMENTS):
        skip = f'page_{page:x}'
        _global(c, page, skip)
        c.emit('897838 897844 8d56fb 899084020000 895040 80b88002000000')
        c.branch('0f84', skip)
        c.emit('89503c')
        c.label(skip)

    # Keep the native text, icons and tooltip targets aligned to the same bars.
    for index, (x, y, width) in enumerate((
        (12, 36, None), (-14, 36, None), (12, 59, -26), (12, 36, -26),
        (12, 100, None), (64, 100, None), (-38, 100, None), (-30, 100, None),
        (12, 123, -26), (12, 100, -26), (CONTENT_MARGIN, 0, None),
    )):
        skip = f'rating_{index}'
        _child(c, RATING, index, skip)
        if x < 0:
            c.emit(f'8d57{x & 255:02x} 895030')
        else:
            _set_field(c, 0x30, x)
        if width:
            c.emit(f'8d57{width & 255:02x} 895038 895044')
        if index == 10:
            c.emit('50 89f0 2d'); c.word(STATS_TOP+16)
            c.emit('31d2 b905000000 f7f1')
            c.emit('8983'); c.word(ROW_PITCH)
            c.emit('d1e8 05'); c.word(STATS_TOP-8)
            c.emit('89c2 58 895034')
            c.emit(f'8d57{-2*CONTENT_MARGIN & 255:02x} 8993'); c.word(RATING_WIDTH)
        else:
            _set_field(c, 0x34, y)
        c.label(skip)

    _global(c, GRID, 'done')
    c.emit('89c1 8d56d6 39513c'); c.branch('0f85', 'resize_grid')
    c.emit('89f8 2b4138 d1e8 394130'); c.branch('0f84', 'done')
    c.label('resize_grid')
    # Pick a square pitch from both axes. Reserve a full native scrollbar lane
    # before rounding down to whole columns used by paint and hit testing.
    c.emit('89513c 895140 899180020000')
    c.emit('57 8d47f0 89d6 31d2 b907000000 f7f1 89c7 89f0 31d2 b906000000 f7f1 39f8 0f4fc7 5f')
    c.emit('ba2b000000 39d0 0f4cc2')
    c.emit('89c6')
    _global(c, GRID, 'done')
    c.emit('89c1 89b188020000 89b18c020000')
    c.emit('8d47f0 31d2 f7f6 0fafc6 83c010 894138 894144')
    c.emit('29c7 d1ef 897930')
    c.emit('c7413420000000')
    c.emit('8b8198020000 85c0'); c.branch('0f84', 'done')
    c.emit('8b5138 83ea10 895030 8b513c 89503c 895040')
    c.emit('89c8'); c.call(0x6c09f0)
    c.label('done')
    c.emit('619d')
    c.jump(PAINT)
    return c.finish(ROW-REFLOW)


def row_code() -> bytes:
    c = Code(ROW)
    c.emit('9c60'); c.base()
    _check_mode(c, 'done')
    c.emit('8bb3'); c.word(ROW_PITCH)
    c.emit('85f6'); c.branch('0f84', 'done')
    # Entry EBP belongs to the native statistics callback, where -4 is X.
    c.emit('8b44241c 8b00 8d4ef1 0fafc1 01442414')
    c.emit('8b542414 89f1 d1e9 29ca 83c208')
    c.emit('8d4efb 51 6a00 68'); c.word(native_colour(0xff252c31))
    c.emit('6802010000 8b8b'); c.word(RATING_WIDTH)
    c.emit('8b45fc'); c.call(0x4f2888)
    c.label('done')
    c.emit('619d'); c.jump(0x9abf90)
    return c.finish(DOTS-ROW)


def dots_code() -> bytes:
    c = Code(DOTS)
    c.emit('9c60'); c.base()
    _check_mode(c, 'stock')
    c.emit('83bb'); c.word(ROW_PITCH); c.emit('00'); c.branch('0f84', 'stock')
    c.emit('619d c20c00')
    c.label('stock')
    c.emit('619d'); c.jump(0x67571c)
    return c.finish(VALUE-DOTS)


def value_code() -> bytes:
    c = Code(VALUE)
    c.emit('53'); c.base()
    _check_mode(c, 'stock')
    c.emit('83bb'); c.word(ROW_PITCH); c.emit('00'); c.branch('0f84', 'stock')
    c.emit('0393'); c.word(RATING_WIDTH)
    c.emit('83ea08'); c.branch('e9', 'done')
    c.label('stock')
    c.emit('81c2e4000000')
    c.label('done')
    c.emit('5b'); c.jump(0x9ac019)
    return c.finish(SPRITE-VALUE)


def _achievement_guard(c: Code) -> None:
    _check_mode(c, 'stock')
    c.emit('8b75fc 3bb3'); c.word(GRID-BASE); c.branch('0f85', 'stock')


def sprite_code() -> bytes:
    c = Code(SPRITE)
    c.emit('57 9c60'); c.base()
    _achievement_guard(c)
    c.emit('8bbe8c020000 83ef03 3983'); c.word(0xac5be4-BASE)
    c.branch('0f84', 'frame')
    c.emit('83ef08')
    c.label('frame')
    c.emit('893c24 619d')
    # Scaled atlas draw takes width, height, frame index, tint and flags.
    c.emit('57 57 ff742414 6aff ff742418')
    c.call(0x4f2910)
    c.emit('5f c20800')
    c.label('stock')
    c.emit('619d 5f'); c.jump(0x674e38)
    return c.finish(SHADE-SPRITE)


def shade_code() -> bytes:
    c = Code(SHADE)
    c.emit('9c60'); c.base()
    _achievement_guard(c)
    c.emit('8bb688020000 83ee03 89742418 89742434')
    c.label('stock')
    c.emit('619d'); c.jump(0x67527c)
    return c.finish(0x100)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected the published New interface from 2026.11.20.13')
    result = bytearray(source)
    with pefile.PE(data=source, fast_load=True) as pe:
        def edit(address: int, before: bytes, after: bytes) -> None:
            at = pe.get_offset_from_rva(address-BASE)
            if source[at:at+len(after)] != before:
                raise ValueError(f'Unexpected Information patch site {address:#x}')
            result[at:at+len(after)] = after

        def redirect(address: int, original: int, target: int, *, call: bool = True) -> None:
            old, new = Code(address), Code(address)
            (old.call if call else old.jump)(original)
            (new.call if call else new.jump)(target)
            edit(address, bytes(old.data), bytes(new.data))

        for address, payload in ((REFLOW, reflow_code()), (ROW, row_code()), (DOTS, dots_code()),
                                 (VALUE, value_code()), (SPRITE, sprite_code()), (SHADE, shade_code()),
                                 (TICK, tick_code())):
            edit(address, bytes(len(payload)), payload)
        edit(chat.FRAME, chat.frame_code(layout=preview.TICK, restore=preview.LEAVE),
             chat.frame_code(layout=TICK, restore=preview.LEAVE, with_information=True))
        redirect(PANEL_PAINT, PAINT, REFLOW, call=False)
        for address in (0x9ac0f9, 0x9ac131, 0x9ac169, 0x9ac1a1, 0x9ac1d9):
            redirect(address, 0x9abf90, ROW)
        redirect(0x9abff5, 0x67571c, DOTS)
        jump = Code(0x9ac013)
        jump.jump(VALUE)
        edit(0x9ac013, bytes.fromhex('81c2e4000000'), jump.finish(6))
        for address in (0x6bfd17, 0x6bfd29):
            redirect(address, 0x674e38, SPRITE)
        redirect(0x6bfd99, 0x67527c, SHADE)
    return bytes(result)
