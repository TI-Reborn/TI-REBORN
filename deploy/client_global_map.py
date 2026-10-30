"""Checked native full-viewport global-map presentation for release 2026.10.10.4.

The authoritative world remains -512..511. The existing native town renderer
receives borrowed deep copies with screen-space bounds only during its draw;
the original array and authoritative town geometry remain unchanged. Native
town labels, clan badges, tooltips and the original avatar rendering survive.
The inverse projection sends the original native 1B travel request.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys

import pefile
from .client_equipment_batch import Code
from . import client_global_map_visual as visual
from . import client_global_map_filter as filters

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = '077a80c0f856a9496745c50b19ef51d31a6e85e857b2f22025cbcd60c0bed1c0'
TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
IMAGE_BASE = 0x400000
REGION = 0x85b000
SIZE = 0x18000
DRAW = IMAGE_BASE + REGION
CLICK = DRAW + 0x1000
INITIALIZE = DRAW + 0x1800
LOAD_WRAPPER = DRAW + 0x1c00
PROJECT_X = DRAW + 0x2000
PROJECT_Y = DRAW + 0x2040
INVERSE_X = DRAW + 0x2080
INVERSE_Y = DRAW + 0x20c0
VIEWPORT = DRAW + 0x2100
AVATAR = DRAW + 0x2200
STOCK_DRAW = DRAW + 0x2300
STOCK_CLICK = DRAW + 0x2340
PATH = DRAW + 0x2380
STATE = REGION + 0x2800
ROWS = REGION + 0x2900
ROW_SIZE = 0x20
NAMES = REGION + 0x3000
TABLE = REGION + 0x5004
TOWNS = REGION + 0x5200
TOWN_SIZE = 0x35c
MAX_TOWNS = 64
SIGNATURE_RVA = REGION + 0x15f00
SIGNATURE = b'TIO-native-global-map-full-viewport-v1'

# State: ready, init count, draws, clicks, left/top/width/height, saved table,
# saved camera XY, saved avatar XY, projected avatar XY, clone length.
READY, LOADS, DRAWS, CLICKS = 0, 4, 8, 12
LEFT, TOP, WIDTH, HEIGHT = 16, 20, 24, 28
OLD_TABLE, OLD_X, OLD_Y, OLD_AVX, OLD_AVY = 32, 36, 40, 44, 48
AVX, AVY, LENGTH = 52, 56, 60


def sha(data):
    return hashlib.sha256(data).hexdigest()


def resources():
    catalog = json.loads((ROOT / 'assets/global-map-v2/catalog.json').read_text(encoding='utf-8'))
    # TI7492cc strips directories AND extensions before its cache lookup.
    # A release-unique stem prevents e.g. denver.png aliasing assault/denver.tga.
    out = [{'id': 0, 'name': 'Terrain', 'path': 'pda\\global-map-v2\\gm-v2-terrain.png', 'world_size': 0}]
    for item in sorted(catalog['locations'], key=lambda x: x['id']):
        world_size = item['diameter_world'] * .8 if item['kind'] == 'city' else 16
        if item['id'] in (12, 16):
            world_size = 12
        out.append({'id': item['id'], 'name': item['name'],
                    'path': 'pda\\global-map-v2\\gm-v2-' + item['object_asset'],
                    'world_size': world_size})
    assert [r['id'] for r in out] == list(range(23))
    return out


def mem(c, op, rva):
    c.emit(op); c.word(rva)


def state(c, op, offset):
    mem(c, op, STATE + offset)


def set_state(c, offset, value):
    state(c, 'c783', offset); c.word(value)


def global_pointer(c, va, register='eax'):
    mem(c, {'eax': '8b83', 'esi': '8bb3', 'edi': '8bbb', 'edx': '8b93'}[register], va - IMAGE_BASE)


def projection(address, axis, inverse=False):
    c = Code(address)
    origin, extent = (LEFT, WIDTH) if axis == 'x' else (TOP, HEIGHT)
    if inverse:
        state(c, '2b83', origin); c.emit('c1e00a 99'); state(c, 'f7bb', extent)
        c.emit('2d00020000')
    else:
        c.emit('0500020000'); state(c, '0faf83', extent)
        c.emit('c1f80a'); state(c, '0383', origin)
    c.emit('c3')
    return c.finish(0x40)


def viewport_code():
    c = Code(VIEWPORT)
    global_pointer(c, 0xac5a4c); c.emit('8b10'); state(c, '8993', LEFT)
    c.emit('8b5004'); state(c, '8993', TOP)
    c.emit('8b5008 2b10'); state(c, '8993', WIDTH)
    c.emit('8b500c 2b5004'); state(c, '8993', HEIGHT)
    c.emit('c3')
    return c.finish(0x80)


def initializer_code():
    c = Code(INITIALIZE); c.emit('9c60'); c.base()
    set_state(c, READY, 0); state(c, 'ff83', LOADS)
    c.emit('8db3'); c.word(ROWS); c.emit('bf17000000')
    c.label('load'); c.emit('8b4614 01d8 ba03000000 89f1')
    c.emit('837e0c00'); c.branch('0f84', 'terrain')
    c.call(DRAW + filters.LOAD_OFFSET); c.branch('e9', 'loaded')
    c.label('terrain'); c.call(0x4f2c50)
    c.label('loaded')
    c.emit('833e00'); c.branch('0f84', 'failed')
    c.emit('83c620 4f'); c.branch('0f85', 'load')
    set_state(c, READY, 1); c.branch('e9', 'done')
    c.label('failed'); set_state(c, READY, -1)
    c.label('done'); c.emit('619d c3')
    return c.finish(0x400)


def load_wrapper_code():
    c = Code(LOAD_WRAPPER); c.call(0x4f2c50)
    c.emit('9c60'); c.call(INITIALIZE); c.emit('619d c3')
    return c.finish(0x80)


def draw_sprite(c):
    # ESI is the immutable real town. Native APIs preserve EBX/ESI/EDI/EBP.
    c.emit('0fb64608 83f801'); c.branch('0f82', 'sprite_done')
    c.emit('83f816'); c.branch('0f87', 'sprite_done')
    c.emit('807e0400'); c.branch('0f85', 'sprite_enabled')
    c.emit('83f801'); c.branch('0f85', 'sprite_done')  # Texas is decorative.
    c.label('sprite_enabled'); c.emit('c1e005 8dbc03'); c.word(ROWS)
    c.emit('837f0000'); c.branch('0f84', 'sprite_done')
    # Preserve the PNG aspect ratio inside the projected world-space footprint.
    state(c, '8b83', WIDTH); state(c, '3b83', HEIGHT)
    c.branch('0f8e', 'sprite_extent'); state(c, '8b83', HEIGHT)
    c.label('sprite_extent'); c.emit('0faf4710 c1f814 50 50')
    c.emit('8b8618020000 038610020000 c1f801'); c.call(PROJECT_X)
    c.emit('8b542404 d1fa 29d0 50')
    c.emit('8b861c020000 038614020000 c1f801'); c.call(PROJECT_Y)
    c.emit('8b542404 d1fa 29d0 89c1 5a')
    # Width was pushed first, then height: native width,height,frame,color,flags.
    c.emit('6a00 6aff 6a00 89f8'); c.call(0x4f2910)
    c.label('sprite_done')


def project_avatar(c):
    global_pointer(c, 0xac5b7c, 'esi')
    c.emit('8b461c'); state(c, '8983', OLD_AVX)
    c.emit('8b4620'); state(c, '8983', OLD_AVY)
    c.emit('d9461c'); c.call(0x40742c); c.call(PROJECT_X); state(c, '8983', AVX)
    c.emit('50 db0424 d95e1c 83c404')
    c.emit('d94620'); c.call(0x40742c); c.call(PROJECT_Y); state(c, '8983', AVY)
    c.emit('50 db0424 d95e20 83c404')


def path_code():
    c = Code(PATH); c.emit('9c60')
    global_pointer(c, 0xac5b7c, 'esi')
    c.emit('83be24020000ff'); c.branch('0f85', 'done')
    for offset in (0x14, 0x18):
        c.emit('8b46'); c.emit(f'{offset:02x}'); c.emit('0500020000 3d00040000')
        c.branch('0f83', 'done')
    c.emit('d9461c'); c.call(0x40742c); c.call(PROJECT_X); state(c, '8983', AVX)
    c.emit('d94620'); c.call(0x40742c); c.call(PROJECT_Y); state(c, '8983', AVY)
    c.emit('8b4614'); c.call(PROJECT_X); c.emit('89c7')
    c.emit('8b4618'); c.call(PROJECT_Y)
    c.emit('50 6882bdd1ff 89f9'); state(c, '8b93', AVY); state(c, '8b83', AVX)
    c.call(0x6750e4)
    c.label('done'); c.emit('619d c3')
    return c.finish(0x200)


def draw_code():
    c = Code(DRAW); c.emit('9c60'); c.base()
    c.emit('f644241c01'); c.branch('0f85', 'update_only')
    state(c, '83bb', READY); c.emit('01'); c.branch('0f85', 'stock')
    c.call(VIEWPORT)
    for offset in (WIDTH, HEIGHT):
        state(c, '83bb', offset); c.emit('00'); c.branch('0f8e', 'stock')
    global_pointer(c, 0xb749e4); c.emit('85c0'); c.branch('0f84', 'stock')
    state(c, '8983', OLD_TABLE); c.emit('8b40fc 83f840'); c.branch('0f87', 'stock')
    c.emit('85c0'); c.branch('0f84', 'stock')
    state(c, '8983', LENGTH); mem(c, '8983', TABLE - 4)
    c.call(0x9edef4); state(c, 'ff83', DRAWS)
    global_pointer(c, 0xac5a4c); c.call(0x4f2eb4)
    c.emit('b802000000'); c.call(0x4f2998)
    state(c, 'ffb3', WIDTH); state(c, 'ffb3', HEIGHT)
    c.emit('6a00 6aff 6a00 8d83'); c.word(ROWS)
    state(c, '8b93', LEFT); state(c, '8b8b', TOP); c.call(0x4f2910)
    c.call(PATH)
    c.call(DRAW + filters.BEGIN_OFFSET)
    c.emit('31ed')
    c.label('clone')
    state(c, '8b83', OLD_TABLE); c.emit('8b34a8 89e8 69c0'); c.word(TOWN_SIZE)
    c.emit('8dbc03'); c.word(TOWNS)
    c.emit('89bcab'); c.word(TABLE)
    c.emit('56 b9'); c.word(TOWN_SIZE // 4); c.emit('fc f3a5 5e')
    c.emit('89e8 69c0'); c.word(TOWN_SIZE); c.emit('8dbc03'); c.word(TOWNS)
    for offset, function in ((0x210, PROJECT_X), (0x214, PROJECT_Y),
                             (0x218, PROJECT_X), (0x21c, PROJECT_Y)):
        c.emit('8b86'); c.word(offset); c.call(function); c.emit('8987'); c.word(offset)
    draw_sprite(c)
    c.emit('45'); state(c, '3bab', LENGTH); c.branch('0f82', 'clone')
    c.call(DRAW + filters.END_OFFSET)
    # Scope only the original renderer. Original game objects are never written.
    for va, offset in ((0xb749ec, OLD_X), (0xb749f0, OLD_Y)):
        global_pointer(c, va); state(c, '8983', offset)
        mem(c, 'c783', va - IMAGE_BASE); c.word(0)
    c.emit('8d83'); c.word(TABLE); mem(c, '8983', 0xb749e4 - IMAGE_BASE)
    c.call(0x9ebda4)
    # Native hover may start a town-info request. Preserve its four cache fields
    # so the borrowed copy does not discard the original ten-second throttle.
    c.emit('31ed')
    c.label('cache')
    state(c, '8b83', OLD_TABLE); c.emit('8b34a8 89e8 69c0'); c.word(TOWN_SIZE)
    c.emit('8dbc03'); c.word(TOWNS)
    c.emit('8b8750020000 898650020000')
    c.emit('668b8734020000 66898634020000 8a8736020000 888636020000')
    c.emit('45'); state(c, '3bab', LENGTH); c.branch('0f82', 'cache')
    # Restore the town table before avatar/city callbacks can inspect world data.
    state(c, '8b83', OLD_TABLE); mem(c, '8983', 0xb749e4 - IMAGE_BASE)
    project_avatar(c); c.call(AVATAR)
    for offset, target in ((OLD_AVX, 0x1c), (OLD_AVY, 0x20)):
        state(c, '8b83', offset); c.emit('8946'); c.emit(f'{target:02x}')
    for va, offset in ((0xb749ec, OLD_X), (0xb749f0, OLD_Y)):
        state(c, '8b83', offset); mem(c, '8983', va - IMAGE_BASE)
    c.emit('619d c3')
    c.label('update_only'); c.call(0x9edef4); c.emit('619d c3')
    c.label('stock'); c.emit('619d'); c.jump(STOCK_DRAW)
    return c.finish(0x1000)


def click_code(*, mode_rva=None):
    c = Code(CLICK); c.emit('9c60'); c.base()
    if mode_rva is not None:
        mem(c, '83bb', mode_rva); c.emit('00'); c.branch('0f85', 'stock')
    state(c, '83bb', READY); c.emit('01'); c.branch('0f85', 'stock')
    global_pointer(c, 0xac5dec); c.emit('803800'); c.branch('0f84', 'done')
    c.call(0xa62988); c.emit('84c0'); c.branch('0f85', 'done')
    c.call(0x66754c); c.emit('84c0'); c.branch('0f84', 'done')
    c.call(VIEWPORT)
    for offset in (WIDTH, HEIGHT):
        state(c, '83bb', offset); c.emit('00'); c.branch('0f8e', 'done')
    global_pointer(c, 0xac5b70, 'esi'); c.emit('8b36')
    global_pointer(c, 0xac5a04, 'edi'); c.emit('8b3f')
    # Outside the clipped map never emits a travel packet.
    state(c, '3bb3', LEFT); c.branch('0f8c', 'done')
    state(c, '8b83', LEFT); state(c, '0383', WIDTH); c.emit('39c6'); c.branch('0f8d', 'done')
    state(c, '3bbb', TOP); c.branch('0f8c', 'done')
    state(c, '8b83', TOP); state(c, '0383', HEIGHT); c.emit('39c7'); c.branch('0f8d', 'done')
    global_pointer(c, 0xac5d58); c.emit('8338ff'); c.branch('0f8e', 'travel')
    # Retain the original avatar's +/-8 logical-pixel city-entry hit target.
    global_pointer(c, 0xac5b7c); c.emit('d9401c'); c.call(0x40742c); c.call(PROJECT_X)
    c.emit('29f0 83c008 83f810'); c.branch('0f83', 'travel')
    global_pointer(c, 0xac5b7c); c.emit('d94020'); c.call(0x40742c); c.call(PROJECT_Y)
    c.emit('29f8 83c008 83f810'); c.branch('0f83', 'travel')
    c.call(0x8596e0); c.branch('e9', 'done')
    c.label('travel')
    global_pointer(c, 0xac5630); c.emit('837808fe'); c.branch('0f85', 'hover_ok')
    c.emit('c74008ffffffff'); c.label('hover_ok')
    c.emit('89f0'); c.call(INVERSE_X); c.emit('50 89f8'); c.call(INVERSE_Y)
    c.emit('89c2 58'); c.call(0x889e5c); state(c, 'ff83', CLICKS)
    c.label('done'); c.emit('619d c3')
    c.label('stock'); c.emit('619d'); c.jump(STOCK_CLICK)
    return c.finish(0x800)


def extension():
    result = bytearray(SIZE)
    def store(va, data):
        offset = va - IMAGE_BASE - REGION; result[offset:offset + len(data)] = data
    for va, data in ((DRAW, draw_code()), (CLICK, click_code()),
                     (INITIALIZE, initializer_code()), (LOAD_WRAPPER, load_wrapper_code()),
                     (PROJECT_X, projection(PROJECT_X, 'x')),
                     (PROJECT_Y, projection(PROJECT_Y, 'y')),
                     (INVERSE_X, projection(INVERSE_X, 'x', True)),
                     (INVERSE_Y, projection(INVERSE_Y, 'y', True)),
                     (VIEWPORT, viewport_code()), (PATH, path_code())):
        store(va, data)
    for va, data in visual.extra_entries(sys.modules[__name__]) + filters.extra_entries(sys.modules[__name__]):
        store(va, data)
    c = Code(AVATAR); c.emit('558bec83c4d0 535657'); c.jump(0x9ee40d); store(AVATAR, c.finish(0x40))
    for va, native, prologue in ((STOCK_DRAW, 0x9ee156, '558bec83c4d0'),
                                 (STOCK_CLICK, 0x9ee68a, '558bec83c4f8')):
        c = Code(va); c.emit(prologue); c.jump(native); store(va, c.finish(0x40))
    for index, item in enumerate(resources()):
        name = item['path']; name_rva = NAMES + index * 0x100
        raw = struct.pack('<HHiI', 1200, 2, -1, len(name)) + name.encode('utf-16le') + b'\0\0'
        assert len(raw) <= 0x100
        store(IMAGE_BASE + name_rva, raw)
        struct.pack_into('<III', result, ROWS - REGION + index * ROW_SIZE + 12,
                         item['id'], round(item['world_size'] * 1024), name_rva + 12)
    store(IMAGE_BASE + SIGNATURE_RVA, SIGNATURE)
    return bytes(result)


def patch(data, *, expected_sha=BASE_SHA):
    if expected_sha != BASE_SHA or sha(data) != BASE_SHA:
        raise ValueError('Global map requires the exact hosted 2026.10.10.4 Silver baseline')
    p = pefile.PE(data=data)
    if (p.FILE_HEADER.Machine != 0x14c or p.OPTIONAL_HEADER.ImageBase != IMAGE_BASE or
            p.OPTIONAL_HEADER.SizeOfImage != REGION):
        raise ValueError('Unexpected native global-map PE target')
    last = p.sections[-1]
    if (last.PointerToRawData + last.SizeOfRawData != len(data) or
            last.Misc_VirtualSize != last.SizeOfRawData or len(data) % 0x200 or
            last.Characteristics & 0xe0000000 != 0xe0000000):
        raise ValueError('Native final section is not safely appendable')
    pad = REGION - last.VirtualAddress - last.SizeOfRawData
    if not 0 <= pad < 0x1000 or pad % 0x200:
        raise ValueError('Unexpected final-section image alignment')
    edits = []
    for va, target, old in ((0x9ee150, DRAW, '558bec83c4d0'),
                            (0x9ee684, CLICK, '558bec83c4f8')):
        edits.append((va, bytes.fromhex(old), b'\xe9' + struct.pack('<i', target - va - 5) + b'\x90'))
    va = 0xa6b1aa
    edits.append((va, b'\xe8' + struct.pack('<i', 0x4f2c50 - va - 5),
                  b'\xe8' + struct.pack('<i', LOAD_WRAPPER - va - 5)))
    edits.extend(visual.native_edits(sys.modules[__name__]))
    result = bytearray(data)
    relocations = [e.rva for block in p.DIRECTORY_ENTRY_BASERELOC for e in block.entries if e.type == 3]
    for va, before, after in edits:
        offset = p.get_offset_from_rva(va - IMAGE_BASE)
        if data[offset:offset + len(before)] != before:
            raise ValueError(f'Global-map native hook differs at {va:#x}')
        if any(va - IMAGE_BASE <= r < va - IMAGE_BASE + len(before) for r in relocations):
            raise ValueError('Global-map hook overlaps a PE relocation')
        result[offset:offset + len(after)] = after
    for field in ('Misc_VirtualSize', 'SizeOfRawData'):
        struct.pack_into('<I', result, last.get_field_absolute_offset(field), getattr(last, field) + pad + SIZE)
    struct.pack_into('<I', result, p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), REGION + SIZE)
    struct.pack_into('<I', result, p.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 0)
    result.extend(bytes(pad)); result.extend(extension())
    return bytes(result)


def metadata():
    return {'scope': 'Native full-viewport global-map presentation and inverse picking',
            'baseline_sha256': BASE_SHA, 'ti_sha256': TI_SHA, 'region_rva': hex(REGION),
            'region_size': SIZE, 'state_rva': hex(STATE), 'rows_rva': hex(ROWS),
            'row_stride': ROW_SIZE, 'resources': resources(),
            'hook_addresses': ['0x9ee150', '0x9ee684', '0xa6b1aa'] +
                              [hex(va) for va, _, _ in visual.native_edits(sys.modules[__name__])],
            'world_bounds': [-512, -512, 511, 511],
            'projection': 'left+(world_x+512)*viewport_width/1024; same for y',
            'inverse': 'floor((mouse_x-left)*1024/viewport_width)-512; same for y',
            'sprite_aspect': 'Square PNGs remain square: world_size*min(viewport_width,viewport_height)/1024',
            'original_town_geometry_modified': False,
            'native_hover_cache_fields_preserved': ['0x234:u8', '0x235:u8', '0x236:u8', '0x250:u32'],
            'native_avatar_tail': '0x9ee40d', 'native_travel': '0x889e5c',
            'gpu_filtering': filters.metadata(sys.modules[__name__]),
            'visual_wrappers': visual.metadata()}
