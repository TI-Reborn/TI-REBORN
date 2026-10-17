"""Pure native UI scaling extension for the published 2026.10.09.11 client.

Silver's own canvas and copied mouse coordinates become logical pixels. The TI
backbuffer, camera and physical mouse remain untouched. A guarded runtime thunk
scales only XYZRHW vertex data copied to a GPU buffer during Silver_Render; its
viewport guard excludes the separately rendered character target. The original
CPU vertices, all texture coordinates, depth, colours and non-UI draws survive.

This transformer neither starts a game nor attaches to a process or publishes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import pefile
from .client_equipment_batch import Code as NativeCode


class Code(NativeCode):
    def jump_label(self, label):
        self.branch('e9', label)

BASE_SHA = '7a58e792614a179cfef1920e7f2d3b1775bc573ef0c39c8dc00eef3ccf23a8a8'
IMAGE_BASE = 0x400000
CORE_RVA = 0x825000
CORE_SIZE = 0x4000
STATE = 0x828f00
SETTER = IMAGE_BASE + CORE_RVA
RESIZE = SETTER + 0x400
RESIZE_NATIVE = SETTER + 0x580
INSTALL = SETTER + 0x600
UPLOAD = SETTER + 0xa00
RENDER = SETTER + 0xc00
RENDER_NATIVE = SETTER + 0xc80
CLIP = SETTER + 0xd00
INVERSE_X = SETTER + 0xf00
INVERSE_Y = SETTER + 0xf40
MOUSE_PROCESS = SETTER + 0x1000
MOUSE_DOWN = SETTER + 0x1100
MOUSE_UP = SETTER + 0x1200
MOUSE_MOVE = SETTER + 0x1300
MOUSE_DOUBLE = SETTER + 0x1400
SCOPE_WRAPPERS = SETTER + 0x1500
CURSOR = SETTER + 0x2c00
SQUAD_REFLOW = SETTER + 0x2d00
INVENTORY_FOOTER = SETTER + 0x3400
INVENTORY_VIEW = SETTER + 0x3600
ITEMS_VIEW = SETTER + 0x3800
SIGNATURE_RVA = CORE_RVA + 0x3e00
SIGNATURE = b'TIO-independent-ui-scale-v1'
KERNEL32_RVA = CORE_RVA + 0x3e80
FLUSH_NAME_RVA = CORE_RVA + 0x3ec0
TI_UPLOAD_CALL = 0x6508be
TI_COPY = 0x406cdc
PERCENTS = (100, 125, 150, 200)

# STATE is a public PIC interface used by the following Screen-controls patch.
# +00 effective percent; +04/+08 physical size; +0c/+10 logical size; +14 render
# scope; +18 requested percent; +1c/+20 forward XY float factors; +24 optional
# bootstrap function RVA (zero until the Screen-controls transformer sets it).
# +28 installation result (0 pending, 1 installed, -1 unavailable); +2c error;
# +30/+34 protection scratch; +38 FlushInstructionCache function pointer.
HOOKS = (
    (0x9f47f8, bytes.fromhex('558bec8b550c'), RESIZE),
    (0x9f4004, bytes.fromhex('558bec83c4f4'), RENDER),
    (0x4f2ec7, bytes.fromhex('a1045fac008b00ffd0'), CLIP),
    (0x9f3aa5, bytes.fromhex('8b15045aac008902'), MOUSE_PROCESS),
    (0x9f4856, bytes.fromhex('8b7d108b750c8b5d08'), MOUSE_DOWN),
    (0x9f4b76, bytes.fromhex('8b7d108b750c8b5d08'), MOUSE_UP),
    (0x9f4e1d, bytes.fromhex('8b75108b5d0c'), MOUSE_MOVE),
    (0x9f4b5d, bytes.fromhex('8b550c8b4508'), MOUSE_DOUBLE),
)
NEUTRALIZED_HIGHLOW = (0x0f2ec8, 0x5f3aa7)
# These native calls draw explicit screen-space GUI. World chat balloons,
# isometric cell markers/ranges and other camera-anchored overlays keep their
# physical geometry. Native TextOut flushes its font batch before returning.
UI_CALLS = (
    (0x9f4027, 0x9de5e8, 'city_frame'),
    (0x9f4043, 0x71c7a4, 'city_assault_time'),
    (0x9f4052, 0xa68e5c, 'city_gui_manager'),
    (0x9f40bd, 0x957b00, 'battle_roster'),
    (0x9f40db, 0x9fe170, 'screen_notices'),
    (0x9f40ea, 0x9db2a4, 'battle_hud'),
    (0x9f40f9, 0x9c29ec, 'battle_hud2'),
    (0x9f413a, 0xa68e5c, 'battle_gui_manager'),
    (0x9f414e, 0x8b7af8, 'ordinary_chat_status'),
    (0x9f415d, 0x95730c, 'roster_loading'),
    (0x9f416c, 0x82c588, 'assault_flagbar'),
    (0x9f417b, 0x71c7a4, 'battle_assault_time'),
    (0x9f4180, 0x7fc008, 'achievement_chain'),
    (0x9f4194, 0x6d31d8, 'referral_tip'),
    (0x9f41b2, 0x9d78b4, 'gui_hint'),
    (0x9f41c1, 0x688518, 'gui_minihint'),
    (0x9f41e7, 0x9c6668, 'gui_highlighter'),
    (0x9f41fd, 0x6a15f8, 'gui_popup'),
    (0x9f4220, 0x6c09dc, 'squad_achievements'),
    (0x9f4234, 0x9fdf70, 'top_screen_notice'),
)
WORLD_CALLS = ((0x9f40ae, 0xc18a00, 'f7_cell_markers'),
               (0x9f40cc, 0x881158, 'world_chat_balloons'),
               (0x9f4108, 0x9bfea0, 'world_regions'))


def call_bytes(va, target):
    return b'\xe8' + struct.pack('<i', target-va-5)


CALL_HOOKS = tuple((va, call_bytes(va, native), SCOPE_WRAPPERS+index*0x100)
                   for index, (va, native, _) in enumerate(UI_CALLS)) + (
                       (0x9f41a3, call_bytes(0x9f41a3, 0xa6a408), CURSOR),)


def get(c: Code, register: str, offset: int):
    c.emit({'eax': '8b83', 'edx': '8b93', 'ecx': '8b8b',
            'esi': '8bb3', 'edi': '8bbb'}[register]); c.word(STATE + offset)


def put(c: Code, offset: int):
    c.emit('8983'); c.word(STATE + offset)


def immediate(c: Code, offset: int, value: int):
    c.emit('c783'); c.word(STATE + offset); c.word(value)


def host(c: Code, address: int):
    c.emit('bf'); c.word(address); c.emit('ffd7')


def iat(c: Code, rva: int):
    c.emit('ff93'); c.word(rva)


def validate_percent(c: Code):
    for value in PERCENTS:
        c.emit('3d'); c.word(value); c.branch('0f84', 'valid_percent')
    c.emit('b864000000')
    c.label('valid_percent')


def setter_code():
    c = Code(SETTER); c.emit('53 56 57 55'); c.base()
    validate_percent(c); put(c, 0x18)
    # No canvas is resized before the physical client bounds are initialized.
    get(c, 'eax', 4); c.emit('85c0'); c.branch('0f8e', 'uninitialized')
    get(c, 'eax', 8); c.emit('85c0'); c.branch('0f8e', 'uninitialized')
    c.call(INSTALL); c.emit('85c0'); c.branch('0f84', 'fallback')
    get(c, 'ecx', 0x18); c.jump_label('calculate')
    c.label('fallback'); c.emit('b964000000')
    c.label('calculate')
    # The native PDA constructors require 768 logical rows; smaller canvases
    # force their minimum-height layout across the chat. Keep it fully usable.
    get(c, 'eax', 4); c.emit('6bc064 31d2 f7f1'); put(c, 0xc)
    get(c, 'eax', 8); c.emit('6bc064 31d2 f7f1'); put(c, 0x10)
    c.emit('83f964'); c.branch('0f84', 'dimensions_ready')
    get(c, 'eax', 0xc); c.emit('3d20030000'); c.branch('0f8c', 'lower')
    get(c, 'eax', 0x10); c.emit('3d00030000'); c.branch('0f8d', 'dimensions_ready')
    c.label('lower')
    c.emit('81f9c8000000'); c.branch('0f85', 'below_200')
    c.emit('b996000000'); c.jump_label('calculate')
    c.label('below_200'); c.emit('81f996000000'); c.branch('0f85', 'below_150')
    c.emit('b97d000000'); c.jump_label('calculate')
    c.label('below_150'); c.emit('b964000000'); c.jump_label('calculate')
    c.label('dimensions_ready'); c.emit('89c8'); put(c, 0)
    # Ratios use the rounded canvas bounds to cover every physical pixel.
    for physical, logical, ratio in ((4, 0xc, 0x1c), (8, 0x10, 0x20)):
        c.emit('db83'); c.word(STATE + physical)
        c.emit('dab3'); c.word(STATE + logical)
        c.emit('d99b'); c.word(STATE + ratio)
    get(c, 'eax', 0x10); c.emit('50'); get(c, 'eax', 0xc); c.emit('50')
    c.call(RESIZE_NATIVE)
    # Native Resize is also called while SILVER_Init has no manager yet. Its
    # own manager guard permits the logical canvas to initialize at that point,
    # but the extra chat/anchor callbacks require the existing GUI instance.
    c.emit('8b83'); c.word(0xac622c - IMAGE_BASE)
    c.emit('85c0'); c.branch('0f84', 'reflow_done')
    c.emit('8b00 85c0'); c.branch('0f84', 'reflow_done')
    # Reflow existing chat pages and cached anchors; never reconstruct the GUI.
    c.call(0xa029dc); c.call(0xc24000); c.call(0xc24300)
    c.call(SQUAD_REFLOW)
    c.label('reflow_done')
    get(c, 'eax', 0); c.emit('5d 5f 5e 5b c3')
    c.label('uninitialized'); immediate(c, 0, 100)
    c.emit('b864000000 5d 5f 5e 5b c3')
    return c.finish(0x400)


def resize_code():
    c = Code(RESIZE); c.emit('55 8bec 53 56 57'); c.base()
    c.emit('8b4508'); put(c, 4); c.emit('8b450c'); put(c, 8)
    get(c, 'eax', 0x18); c.emit('85c0'); c.branch('0f85', 'requested')
    # Transient startup/minimized bounds must not freeze an automatic default
    # before the real physical display is known. Native GUI dimensions still
    # follow the event, while the requested percent remains uninitialized.
    get(c, 'eax', 4); c.emit('3d20030000'); c.branch('0f8c', 'transient')
    get(c, 'eax', 8); c.emit('3d58020000'); c.branch('0f8c', 'transient')
    get(c, 'eax', 0x24); c.emit('85c0'); c.branch('0f84', 'default')
    c.emit('01d8 ffd0'); c.jump_label('requested')
    c.label('default'); c.emit('b864000000')
    c.label('requested'); c.call(SETTER)
    c.emit('5f 5e 5b 5d c20800')
    c.label('transient')
    c.emit('ff750c ff7508'); c.call(RESIZE_NATIVE)
    c.emit('b864000000 5f 5e 5b 5d c20800')
    return c.finish(0x180)


def install_code():
    c = Code(INSTALL); c.emit('9c60'); c.base()
    get(c, 'eax', 0x28); c.emit('85c0'); c.branch('0f85', 'existing')
    # The exact pinned host call is the only executable memory changed.
    c.emit('813d'); c.word(TI_UPLOAD_CALL); c.word(0xdb6419e8)
    c.branch('0f85', 'unavailable')
    c.emit('803d'); c.word(TI_UPLOAD_CALL + 4); c.emit('ff')
    c.branch('0f85', 'unavailable')
    c.emit('813d5c086500558bec83'); c.branch('0f85', 'unavailable')
    c.emit('8d83'); c.word(KERNEL32_RVA); c.emit('50'); iat(c, 0x77a178)
    c.emit('85c0'); c.branch('0f84', 'unavailable')
    c.emit('8d93'); c.word(FLUSH_NAME_RVA); c.emit('52 50'); iat(c, 0x77a170)
    c.emit('85c0'); c.branch('0f84', 'unavailable'); put(c, 0x38)
    c.emit('8d83'); c.word(STATE + 0x30); c.emit('50 6a40 6a05 68')
    c.word(TI_UPLOAD_CALL); iat(c, 0x77a090)
    c.emit('85c0'); c.branch('0f84', 'unavailable')
    c.emit('8d83'); c.word(UPLOAD - IMAGE_BASE)
    c.emit('2d'); c.word(TI_UPLOAD_CALL + 5)
    c.emit('a3'); c.word(TI_UPLOAD_CALL + 1)
    c.emit('c605'); c.word(TI_UPLOAD_CALL); c.emit('e8')
    iat(c, 0x77a1b0); c.emit('6a05 68'); c.word(TI_UPLOAD_CALL); c.emit('50')
    c.emit('ff93'); c.word(STATE + 0x38)
    c.emit('85c0'); c.branch('0f84', 'restore_original')
    immediate(c, 0x28, 1); c.jump_label('restore_protection')
    c.label('restore_original')
    c.emit('c705'); c.word(TI_UPLOAD_CALL); c.word(0xdb6419e8)
    c.emit('c605'); c.word(TI_UPLOAD_CALL + 4); c.emit('ff')
    immediate(c, 0x28, -1); immediate(c, 0x2c, 2)
    # Flush the restored original instructions before closing the writable page.
    iat(c, 0x77a1b0); c.emit('6a05 68'); c.word(TI_UPLOAD_CALL); c.emit('50')
    c.emit('ff93'); c.word(STATE + 0x38)
    c.label('restore_protection')
    c.emit('8d83'); c.word(STATE + 0x34); c.emit('50')
    get(c, 'eax', 0x30); c.emit('50 6a05 68'); c.word(TI_UPLOAD_CALL)
    iat(c, 0x77a090); c.emit('85c0'); c.branch('0f85', 'existing')
    immediate(c, 0x2c, 3)
    c.label('existing'); get(c, 'eax', 0x28); c.emit('83f801 0f94c0 0fb6c0')
    c.emit('8944241c 619d c3')
    c.label('unavailable'); immediate(c, 0x28, -1); immediate(c, 0x2c, 1)
    c.emit('31c0 8944241c 619d c3')
    return c.finish(0x400)


def guard_render(c: Code, skip: str):
    get(c, 'eax', 0x14); c.emit('85c0'); c.branch('0f84', skip)
    get(c, 'eax', 0); c.emit('83f864'); c.branch('0f86', skip)
    get(c, 'eax', 4); c.emit('85c0'); c.branch('0f8e', skip)
    c.emit('8b0d0cde7600 85c9'); c.branch('0f84', skip)
    c.emit('8b09 85c9'); c.branch('0f84', skip)
    c.emit('3b8199020000'); c.branch('0f87', skip)
    get(c, 'eax', 8); c.emit('3b819d020000'); c.branch('0f87', skip)


def upload_code():
    c = Code(UPLOAD); c.emit('9c60'); c.base()
    # Replay the native copy first, preserving immutable CPU-side geometry.
    host(c, TI_COPY)
    guard_render(c, 'done')
    c.emit('8b75fc 85f6'); c.branch('0f84', 'done')
    c.emit('8b4618 83e00e 83f804'); c.branch('0f85', 'done')
    c.emit('8b7e1c 83ff10'); c.branch('0f82', 'done')
    c.emit('81ff00010000'); c.branch('0f87', 'done')
    c.emit('8b442418 31d2 f7f7 85d2'); c.branch('0f85', 'done')
    c.emit('85c0'); c.branch('0f84', 'done')
    c.emit('3d00000100'); c.branch('0f87', 'done')
    c.emit('89c1 8b742414')
    c.label('vertex')
    c.emit('d906 d88b'); c.word(STATE + 0x1c); c.emit('d91e')
    c.emit('d94604 d88b'); c.word(STATE + 0x20); c.emit('d95e04')
    c.emit('01fe 49'); c.branch('0f85', 'vertex')
    c.label('done'); c.emit('619d c3')
    return c.finish(0x200)


def render_code():
    return scoped_code(RENDER, RENDER_NATIVE, 0, size=0x80)


def scoped_code(address, native, scope, *, size=0x100, cursor=False):
    c = Code(address); c.emit('55 8bec 83ec0c 9c60'); c.base()
    get(c, 'eax', 0x14); c.emit('8945fc'); immediate(c, 0x14, scope)
    if cursor:
        # The software cursor is drawn in physical pixels and retains its
        # native size. Hit testing and drag controls keep the logical copies.
        for logical_rva, host_pointer, local in ((0x6c5b70, 0x76e518, -8),
                                                 (0x6c5a04, 0x76e440, -12)):
            c.emit('8b93'); c.word(logical_rva); c.emit('8b02 8945'); c.emit(f'{local&255:02x}')
            c.emit('8b0d'); c.word(host_pointer); c.emit('85c9'); c.branch('0f84', f'cursor_skip_{local}')
            c.emit('8b01 8902'); c.label(f'cursor_skip_{local}')
    c.emit('619d'); c.call(native)
    c.emit('9c60'); c.base(); c.emit('8b45fc'); put(c, 0x14)
    if cursor:
        for rva, local in ((0x6c5b70, -8), (0x6c5a04, -12)):
            c.emit('8b93'); c.word(rva); c.emit('8b45'); c.emit(f'{local&255:02x}'); c.emit('8902')
    c.emit('619d 8be5 5d c3')
    return c.finish(size)


def clip_code():
    c = Code(CLIP); c.emit('9c60'); c.base(); guard_render(c, 'done')
    # The original four argument dwords remain on the native caller's stack.
    for index, physical, logical in ((0, 4, 0xc), (1, 8, 0x10),
                                     (2, 4, 0xc), (3, 8, 0x10)):
        c.emit('8b8424'); c.word(36 + index*4)
        get(c, 'ecx', physical); c.emit('f7e9')
        get(c, 'ecx', logical); c.emit('f7f9')
        c.emit('898424'); c.word(36 + index*4)
    c.label('done'); c.emit('619d 53'); c.base()
    c.emit('8b83'); c.word(0x6c5f04); c.emit('5b 8b00 ffd0')
    c.jump(0x4f2ed0)
    return c.finish(0x200)


def inverse_code(address: int, physical: int, logical: int):
    c = Code(address)
    get(c, 'ecx', physical); c.emit('85c9'); c.branch('0f8e', 'done')
    c.emit('f7ab'); c.word(STATE + logical); c.emit('f7f9')
    c.label('done'); c.emit('c3')
    return c.finish(0x40)


def input_code(address: int, before: bytes, resume: int, slots: tuple[int, int]):
    c = Code(address); c.data.extend(before); c.emit('9c60'); c.base()
    for slot, helper, global_rva in zip(slots, (INVERSE_X, INVERSE_Y),
                                        (0x6c5b70, 0x6c5a04)):
        c.emit('8b4424'); c.emit(f'{slot:02x}'); c.call(helper)
        c.emit('894424'); c.emit(f'{slot:02x}')
        c.emit('8b93'); c.word(global_rva); c.emit('8902')
    c.emit('619d'); c.jump(resume)
    return c.finish(0x100)


def process_mouse_code():
    c = Code(MOUSE_PROCESS); c.emit('9c60'); c.base()
    c.emit('8b93'); c.word(0x6c5a04); c.emit('8902 89542414')
    for helper, global_rva in ((INVERSE_X, 0x6c5b70), (INVERSE_Y, 0x6c5a04)):
        c.emit('8bb3'); c.word(global_rva); c.emit('8b06'); c.call(helper)
        c.emit('8906')
    c.emit('619d'); c.jump(0x9f3aad)
    return c.finish(0x100)


def existing_control(c, global_va, vmt, skip, *, parent=True):
    """Select an existing control of the pinned native class and parent."""
    c.emit('8b83'); c.word(global_va - IMAGE_BASE)
    c.emit('85c0'); c.branch('0f84', skip)
    c.emit('8d93'); c.word(vmt - IMAGE_BASE)
    c.emit('3910'); c.branch('0f85', skip)
    if parent:
        c.emit('39704c'); c.branch('0f85', skip)


def squad_reflow_code():
    c = Code(SQUAD_REFLOW); c.emit('9c60'); c.base()
    c.emit('8b83'); c.word(0xac622c - IMAGE_BASE)
    c.emit('85c0'); c.branch('0f84', 'done')
    c.emit('8b00 85c0'); c.branch('0f84', 'done')
    c.emit('89c6 8d93'); c.word(0x9af088 - IMAGE_BASE)
    c.call(0xa3fca8); c.emit('83f8ff'); c.branch('0f84', 'done')
    c.emit('89c2 89f0'); c.call(0xa3f2a0)
    c.emit('85c0'); c.branch('0f84', 'done')
    c.emit('8d93'); c.word(0xa31a40 - IMAGE_BASE)
    c.emit('3910'); c.branch('0f85', 'done')
    c.emit('89c6 6683be4003000000'); c.branch('0f84', 'done')
    c.emit('6683be4203000000'); c.branch('0f84', 'done')
    get(c, 'edi', 0x10); c.emit('81ff00030000'); c.branch('0f8d', 'height')
    c.emit('bf00030000'); c.label('height')
    # Exactly the original root constructor 9aef1b..9aef5a, including native
    # background-tile quantization and the existing close-button geometry.
    get(c, 'eax', 0xc); c.emit('2dbe000000 50 89f8 2d45010000 50')
    c.emit('b948000000 ba92000000 89f0'); c.call(0xa439d8)
    # Header, operations strip, portrait/bag, categories, table, crafting and
    # abilities tabs retain their native fixed columns and screen-size formulas.
    existing_control(c, 0xac4bdc, 0x8c98b0, 'header_done')
    c.emit('8b5638 83ea64 895038'); c.label('header_done')
    for global_va, width, height, footer in (
        (0xad1094, 'screen', 34, False),
        (0xad1098, 20, -456, False),
        (0xad109c, 'screen', -456, False),
        (0xad10a0, 232, -420, False),
        (0xad10a4, 'capped', -456, True),
        (0xad10a8, 252, -420, False),
        (0xad10ac, 252, -420, False),
    ):
        skip = f'panel_{global_va:x}'
        existing_control(c, global_va, 0xa2bf58, skip)
        if width in ('screen', 'capped'):
            get(c, 'edx', 0xc); c.emit('81eac2010000')
            if width == 'capped':
                c.emit('81fa11030000'); c.branch('0f8e', skip+'_width')
                c.emit('ba11030000'); c.label(skip+'_width')
        else:
            c.emit('ba'); c.word(width)
        if height < 0:
            c.emit('89f9 81e9'); c.word(-height)
        else:
            c.emit('b9'); c.word(height)
        if footer:
            c.call(INVENTORY_FOOTER)
        else:
            c.emit('895038 89483c')
        c.label(skip)
    # The three existing bag lists all use the same native row/scroll geometry.
    for panel, items, subtract in ((0xad10a0, 0xac4bd4, 660),
                                   (0xad10a8, 0xac4bbc, 630),
                                   (0xad10ac, 0xac4bc0, 490)):
        skip = f'items_{items:x}'
        c.emit('56 8bb3'); c.word(panel - IMAGE_BASE)
        existing_control(c, items, 0x9b23e0, skip)
        c.emit('89fa 81ea'); c.word(subtract); c.call(ITEMS_VIEW)
        c.label(skip); c.emit('5e')
    c.emit('56 8bb3'); c.word(0xad10a4 - IMAGE_BASE)
    existing_control(c, 0xac4bd8, 0x995ec4, 'table_done')
    c.emit('8b5638 81ea82000000 8b4e3c 83e950'); c.call(INVENTORY_VIEW)
    c.emit('8b7838')
    for global_va, field, subtract in ((0xad106c, 0x30, 200),
                                       (0xad1070, 0x30, 120),
                                       (0xad1068, 0x38, 277)):
        skip = f'column_{global_va:x}'
        existing_control(c, global_va, 0x6c29cc, skip)
        c.emit('89fa 81ea'); c.word(subtract)
        c.emit('8950'); c.emit(f'{field:02x}'); c.label(skip)
    c.label('table_done'); c.emit('5e')
    c.label('done'); c.emit('619d c3')
    return c.finish(0x700)


def inventory_footer_code():
    # EAX existing table panel, EDX/ECX desired size. Footer coordinates in
    # 9aa13a..9aa740 are all parentH-63..parentH-28. Move exactly that strip;
    # The native filter column 9aa13a..9aa166 fills parentH-63; its zoom button
    # 9aa1a1..9aa1df uses parentH-92. Preserve its items/filter selections while
    # refreshing only geometry and the constructor's cached viewport fields.
    c = Code(INVENTORY_FOOTER); c.emit('55 8bec 83ec14 9c60'); c.base()
    c.emit('895dec')
    c.emit('89c6 8b403c 8945fc 89c8 2b45fc 8945f8')
    c.emit('8b4638 8945f4 89d0 2b45f4 8945f0 895638 894e3c')
    c.emit('89f0'); c.call(0xa424d4); c.emit('89c7 31db')
    c.label('child'); c.emit('39fb'); c.branch('0f8d', 'done')
    c.emit('89f0 89da'); c.call(0xa424c4)
    c.emit('85c0'); c.branch('0f84', 'next')
    c.emit('8b55ec 81c2'); c.word(0x6ca000-IMAGE_BASE)
    c.emit('3910'); c.branch('0f85', 'zoom')
    c.emit('8b55ec 3b82'); c.word(0xac4bb4-IMAGE_BASE)
    c.branch('0f85', 'next'); c.emit('39704c'); c.branch('0f85', 'next')
    c.emit('8b563c 83ea3f 89503c 895040 8b5638 83ea7d 895030')
    c.emit('8b5038 895044'); c.jump_label('next')
    c.label('zoom')
    c.emit('8b55ec 81c2'); c.word(0xa2ed34-IMAGE_BASE)
    c.emit('3910'); c.branch('0f85', 'footer')
    c.emit('83783820'); c.branch('0f85', 'footer')
    c.emit('83783c20'); c.branch('0f85', 'footer')
    c.emit('8b55f4 83ea20 395030'); c.branch('0f85', 'footer')
    c.emit('8b55fc 83ea5c 395034'); c.branch('0f85', 'footer')
    c.emit('8b55f8 015034 8b55f0 015030'); c.jump_label('next')
    c.label('footer')
    c.emit('8b55fc 83ea40 395034'); c.branch('0f8c', 'next')
    c.emit('8b55f8 015034 8b55f4 81eaf0000000 395030')
    c.branch('0f8c', 'next'); c.emit('8b55f0 015030')
    c.label('next'); c.emit('43'); c.jump_label('child')
    c.label('done'); c.emit('619d 8be5 5d c3')
    return c.finish(0x200)


def inventory_view_code():
    # Existing TGUIInventoryList viewport and scrollbar, followed by its pure
    # native content-extent calculation. Selection/filter/actor data survive.
    c = Code(INVENTORY_VIEW); c.emit('9c60 89c6 895038 895044 89483c 894840')
    c.emit('83e920 898e88020000 8b8680020000 85c0')
    c.branch('0f84', 'done')
    c.emit('c7403810000000 8b5638 2b5038 895030 31d2 895034')
    c.emit('8b563c'); c.call(0xa4176c)
    c.emit('89f0'); c.call(0x99efd4)
    c.label('done'); c.emit('619d c3')
    return c.finish(0x200)


def items_view_code():
    # Existing TGUIGameItemsListbox: native row geometry and pure scrollbar
    # range calculation. Footer weight bars retain their constructor margin4.
    c = Code(ITEMS_VIEW); c.emit('55 8bec 83ec10 9c60'); c.base()
    c.emit('895df4 89c6')
    c.emit('8955fc 8b463c 8945f8 89563c 895640 89d0 c1f804')
    c.emit('8986ac020000 8b8698020000 85c0'); c.branch('0f84', 'weight')
    c.emit('8b5638 2b5038 895030 31d2 895034 8b55fc')
    c.call(0xa4176c)
    # This list's native width remains222: its existing filtered content height
    # remains valid. Recompute only the scroll range and cached offset, avoiding
    # even the native item-resource cache updates in a fresh content traversal.
    c.emit('8b868c020000 2b463c 8945f0 db45f0 d95df0 ff75f0')
    c.emit('8b8698020000'); c.call(0xa417d0)
    c.emit('8b8698020000 d980a4020000'); c.call(0x407438)
    c.emit('8986b0020000')
    c.label('weight')
    c.emit('8b464c 85c0'); c.branch('0f84', 'done')
    c.emit('89c6'); c.call(0xa424d4); c.emit('89c7 31db')
    c.label('child'); c.emit('39fb'); c.branch('0f8d', 'done')
    c.emit('89f0 89da'); c.call(0xa424c4)
    c.emit('85c0'); c.branch('0f84', 'next')
    # Parent was already validated by the caller. VMT comes from its native
    # WeightBar class variable, so relocated Silver keeps the exact class guard.
    c.emit('8b55f4 81c2'); c.word(0x9b0b10 - IMAGE_BASE)
    c.emit('3910'); c.branch('0f85', 'next')
    c.emit('8b55fc 2b55f8 015034')
    c.label('next'); c.emit('43'); c.jump_label('child')
    c.label('done'); c.emit('619d 8be5 5d c3')
    return c.finish(0x200)


def payload():
    result = bytearray(CORE_SIZE)
    parts = {
        SETTER: setter_code(), RESIZE: resize_code(), INSTALL: install_code(),
        UPLOAD: upload_code(), RENDER: render_code(), CLIP: clip_code(),
        INVERSE_X: inverse_code(INVERSE_X, 4, 0xc),
        INVERSE_Y: inverse_code(INVERSE_Y, 8, 0x10),
        MOUSE_PROCESS: process_mouse_code(),
        MOUSE_DOWN: input_code(MOUSE_DOWN, HOOKS[4][1], 0x9f485f, (4, 0)),
        MOUSE_UP: input_code(MOUSE_UP, HOOKS[5][1], 0x9f4b7f, (4, 0)),
        MOUSE_MOVE: input_code(MOUSE_MOVE, HOOKS[6][1], 0x9f4e23, (0x10, 4)),
        MOUSE_DOUBLE: input_code(MOUSE_DOUBLE, HOOKS[7][1], 0x9f4b63, (0x1c, 0x14)),
        CURSOR: scoped_code(CURSOR, 0xa6a408, 0, cursor=True),
        SQUAD_REFLOW: squad_reflow_code(),
        INVENTORY_FOOTER: inventory_footer_code(),
        INVENTORY_VIEW: inventory_view_code(),
        ITEMS_VIEW: items_view_code(),
    }
    for index, (_, native, _) in enumerate(UI_CALLS):
        address = SCOPE_WRAPPERS+index*0x100
        parts[address] = scoped_code(address, native, 1)
    for native, old, address in ((0x9f47fe, HOOKS[0][1], RESIZE_NATIVE),
                                 (0x9f400a, HOOKS[1][1], RENDER_NATIVE)):
        c = Code(address); c.data.extend(old); c.jump(native); parts[address] = c.finish(0x20)
    for address, code in parts.items():
        offset = address - IMAGE_BASE - CORE_RVA
        if any(result[offset:offset + len(code)]):
            raise ValueError('UI scale payload overlaps another helper')
        result[offset:offset + len(code)] = code
    for rva, data in ((SIGNATURE_RVA, SIGNATURE + b'\0'),
                      (KERNEL32_RVA, 'kernel32.dll\0'.encode('utf-16le')),
                      (FLUSH_NAME_RVA, b'FlushInstructionCache\0')):
        at = rva - CORE_RVA; result[at:at+len(data)] = data
    struct.pack_into('<I', result, STATE - CORE_RVA, 100)
    struct.pack_into('<ff', result, STATE - CORE_RVA + 0x1c, 1.0, 1.0)
    return bytes(result)


def hook_bytes(va: int, before: bytes, target: int):
    if any(item[0] == va for item in CALL_HOOKS):
        return call_bytes(va, target)
    return b'\xe9' + struct.pack('<i', target-va-5) + b'\x90' * (len(before)-5)


def patch(data: bytes) -> bytes:
    pe = pefile.PE(data=data)
    signature_offset = pe.get_offset_from_rva(SIGNATURE_RVA) if pe.OPTIONAL_HEADER.SizeOfImage > SIGNATURE_RVA else None
    if signature_offset is not None and data[signature_offset:signature_offset+len(SIGNATURE)] == SIGNATURE:
        for va, before, target in HOOKS+CALL_HOOKS:
            offset = pe.get_offset_from_rva(va-IMAGE_BASE)
            if data[offset:offset+len(before)] != hook_bytes(va, before, target):
                raise ValueError('Existing UI scale hook differs from the supported patch')
        return data
    if hashlib.sha256(data).hexdigest() != BASE_SHA:
        raise ValueError('UI scale requires the exact published .11 Silver baseline')
    last = pe.sections[-1]
    if (last.Name.rstrip(b'\0') != b'.tioscr' or last.VirtualAddress != 0x823000
            or last.SizeOfRawData != 0x2000 or last.Misc_VirtualSize != 0x2000
            or last.PointerToRawData+last.SizeOfRawData != len(data)
            or pe.OPTIONAL_HEADER.SizeOfImage != CORE_RVA):
        raise ValueError('Unexpected final section layout')
    result = bytearray(data)
    for va, before, target in HOOKS+CALL_HOOKS:
        offset = pe.get_offset_from_rva(va-IMAGE_BASE)
        if data[offset:offset+len(before)] != before:
            raise ValueError(f'Native UI scale hook guard failed at {va:#x}')
        result[offset:offset+len(before)] = hook_bytes(va, before, target)
    found = set()
    for block in pe.DIRECTORY_ENTRY_BASERELOC:
        for entry in block.entries:
            if entry.rva in NEUTRALIZED_HIGHLOW:
                if entry.type != pefile.RELOCATION_TYPE['IMAGE_REL_BASED_HIGHLOW']:
                    raise ValueError('Unexpected overwritten relocation type')
                # ABSOLUTE leaves the original relocation directory shape intact.
                struct.pack_into('<H', result, entry.struct.get_file_offset(), entry.rva & 0xfff)
                found.add(entry.rva)
    if found != set(NEUTRALIZED_HIGHLOW):
        raise ValueError('Native UI hooks lost their exact relocation guards')
    result.extend(payload())
    new_size = last.SizeOfRawData + CORE_SIZE
    struct.pack_into('<I', result, last.get_field_absolute_offset('Misc_VirtualSize'), new_size)
    struct.pack_into('<I', result, last.get_field_absolute_offset('SizeOfRawData'), new_size)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), CORE_RVA+CORE_SIZE)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 0)
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    original = args.source.read_bytes(); updated = patch(original)
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_bytes(updated)
    report = {'base_sha256': hashlib.sha256(original).hexdigest(),
              'candidate_sha256': hashlib.sha256(updated).hexdigest(),
              'candidate_bytes': len(updated), 'core_rva': hex(CORE_RVA),
              'core_size': CORE_SIZE, 'setter_va': hex(SETTER), 'state_rva': hex(STATE),
              'physical_backbuffer_unchanged': True, 'input_world_picking_unchanged': True,
              'real_client_rendering_verified': False, 'published': False}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
