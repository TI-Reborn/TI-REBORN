"""Road-layout global map (v3) inside the existing native map region.

Pure byte transformer for the published 2026.10.28.2 Silver. Only code and
data that the full-viewport map patch (client_global_map.py) appended are
replaced, plus one call in the original 1D reader:

* the baked v3 map replaces the v2 terrain and its 22 object sprites;
* the hovered location gets its lit, glowing sprite over a dimmed map; the
  current town and the journey's final location get a dashed outline;
* the squad marker is a gold arrow, one of 32 headings picked from the
  rendered motion on screen;
* native labels of the 22 baked locations are skipped (their names are part
  of the image); hover tooltips, clan badges, contract markers and clicks
  stay native;
* the 1D reader keeps its second, otherwise discarded Z field: the server
  puts the journey's final location there (tio.locations.movement_packet).

The straight native path line is no longer drawn: the server drives the
squad along roads one leg at a time; the dashed route replaces it.
"""
from __future__ import annotations

import hashlib
import math
import struct

import pefile

from .client_equipment_batch import Code
from . import client_global_map as v2
from . import client_global_map_filter as filters
from . import client_global_map_visual as visual

BASE_SHA = '3f0f31f04e6300b57a8bf519899b84e1e26573e915251b58f37f19b003d65e8d'
IMAGE_BASE, REGION, DRAW, STATE = v2.IMAGE_BASE, v2.REGION, v2.DRAW, v2.STATE
MAP_WIDTH, MAP_HEIGHT = 1819, 865
LOCATION_IDS = range(1, 23)
# Per location id 0..22: map-pixel rect x0,y0,x1,y1, hover row RVA, selected row RVA.
LOCATIONS = REGION + 0x2900
LOCATION_SIZE = 0x20
NAMES = REGION + 0x3000
NAME_STRIDE = 0x60
NAMES_END = REGION + 0x5000
ROWS = REGION + 0x13600
ROW_SIZE = 0x20
MAX_ROWS = 0x50
CODE = DRAW + 0x14000
HIGHLIGHT = CODE
MARKER = CODE + 0x400
FINAL_READ = CODE + 0x800
MAP_X = CODE + 0x880
MAP_Y = CODE + 0x8c0
CONSTANTS = CODE + 0x900
CODE_END = CODE + 0x980
ROUTE_READ = CODE + 0x980
ROUTE_DRAW = CODE + 0xa00
TIP_TOWN = CODE + 0xd00
TIP_BASE = CODE + 0xe80
ROUTE = REGION + 0x15000  # Route words (runtime), up to MAX_ROUTE dwords.
MAX_ROUTE = 400  # tio.protocol.map_route.MAX_DASHES
SIGNATURE_RVA = REGION + 0x15e00
SIGNATURE = b'TIO-native-global-map-roads-v1'
FINAL_HOOK = 0x88b19c
ROUTE_HOOK = 0x88b172
READ_DWORD = 0x605db8
TEXT_DRAW = 0x4f2a0c
LINE = 0x6750e4
TOWN_TIP, BASE_TIP = 0x9e8374, 0x9e8e70
TIP_SITES = ((0x9ec2b5, TOWN_TIP, TIP_TOWN), (0x9ec2ca, BASE_TIP, TIP_BASE), (0x9ec2df, TOWN_TIP, TIP_TOWN))
CAMERA = 0xac60a4

# New state words after the v2 ones (v2 uses 0..0x3c).
HOVER, HOVER_NEXT, FINAL, FRAME, TURN = 0x40, 0x44, 0x48, 0x4c, 0x50
ROUTE_COUNT, X0, Y0, X1, Y1, CAMERA_X = 0x54, 0x58, 0x5c, 0x60, 0x64, 0x68
# The map is always a little dimmed so lit locations and outlines stand out
# on its sand; around the hovered location it dims to half.
BASE_COLOR = 0xffdadada
DIM_COLOR = 0xff808080
ROUTE_COLOR, ROUTE_SHADOW = 0xffffc04c, 0xb0100a04
# Native tooltips are drawn next to the cursor; these sizes keep them inside
# the map (town info / base and mine info, logical pixels).
TIP_SIZES = {TIP_TOWN: (300, 160), TIP_BASE: (330, 250)}
MARKER_FRAMES = 32
# Heading needs half a screen pixel of motion: (512 = 0.5 * 1024)^2 in
# world-delta * viewport-size units.
TURN_THRESHOLD = 512.0 ** 2
FRAMES_PER_RADIAN = MARKER_FRAMES / (2 * math.pi)

GAME_CHARACTER, MOUSE_X, MOUSE_Y = 0xac5b7c, 0xac5b70, 0xac5a04
CURRENT_TOWN, TOOLTIP_BLOCKED = 0xac5d58, 0xac57ac


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def state(c, op, offset):
    c.emit(op); c.word(STATE + offset)


def pointer(c, va, register='eax'):
    v2.global_pointer(c, va, register)


def map_axis(address, origin, extent, pixels):
    """eax = map pixel -> eax = viewport coordinate (same scale as the map draw)."""
    c = Code(address)
    state(c, '0faf83', extent); c.emit('99 b9'); c.word(pixels); c.emit('f7f9')
    state(c, '0383', origin); c.emit('c3')
    return c.finish(0x40)


def rows(manifest: dict) -> list[str]:
    """Client paths in row order: map, (hover, selected) per location id, marker frames."""
    by_id = {location['id']: location for location in manifest['locations']}
    if sorted(by_id) != [i for i in LOCATION_IDS if i != 1]:
        raise ValueError('The v3 manifest must cover every public location except Texas')
    out = [manifest['map']['path']]
    for town in sorted(by_id):
        out += [by_id[town]['hover']['path'], by_id[town]['selected']['path']]
    frames = [frame['path'] for frame in manifest['marker']['frames']]
    if len(frames) != MARKER_FRAMES:
        raise ValueError('The v3 manifest needs 32 marker headings')
    return out + frames


def marker_row(manifest: dict) -> int:
    return 1 + 2 * len(manifest['locations'])


def initializer_code(count: int):
    c = Code(v2.INITIALIZE); c.emit('9c60'); c.base()
    v2.set_state(c, v2.READY, 0); state(c, 'ff83', v2.LOADS)
    c.emit('8db3'); c.word(ROWS); c.emit('bf'); c.word(count)
    c.label('load'); c.emit('8b4614 01d8 ba03000000 89f1')
    # Row id 0 is the map: plain loader. Sprites get the checked mip chain.
    c.emit('837e0c00'); c.branch('0f84', 'map')
    c.call(DRAW + filters.LOAD_OFFSET); c.branch('e9', 'loaded')
    c.label('map'); c.call(0x4f2c50)
    c.label('loaded')
    c.emit('833e00'); c.branch('0f84', 'failed')
    c.emit('83c620 4f'); c.branch('0f85', 'load')
    v2.set_state(c, v2.READY, 1); c.branch('e9', 'done')
    c.label('failed'); v2.set_state(c, v2.READY, -1)
    c.label('done'); c.emit('619d c3')
    return c.finish(0x400)


def draw_code():
    c = Code(DRAW); c.emit('9c60'); c.base()
    c.emit('f644241c01'); c.branch('0f85', 'update_only')
    state(c, '83bb', v2.READY); c.emit('01'); c.branch('0f85', 'stock')
    c.call(v2.VIEWPORT)
    for offset in (v2.WIDTH, v2.HEIGHT):
        state(c, '83bb', offset); c.emit('00'); c.branch('0f8e', 'stock')
    pointer(c, 0xb749e4); c.emit('85c0'); c.branch('0f84', 'stock')
    state(c, '8983', v2.OLD_TABLE); c.emit('8b40fc 83f840'); c.branch('0f87', 'stock')
    c.emit('85c0'); c.branch('0f84', 'stock')
    state(c, '8983', v2.LENGTH); v2.mem(c, '8983', v2.TABLE - 4)
    c.call(0x9edef4); state(c, 'ff83', v2.DRAWS)
    pointer(c, 0xac5a4c); c.call(0x4f2eb4)
    c.emit('b802000000'); c.call(0x4f2998)
    # The map itself, dimmed while a location is hovered (previous frame).
    state(c, 'ffb3', v2.WIDTH); state(c, 'ffb3', v2.HEIGHT); c.emit('6a00')
    c.emit('b8'); c.word(BASE_COLOR)
    state(c, '83bb', HOVER); c.emit('00'); c.branch('0f84', 'bright')
    c.emit('b8'); c.word(DIM_COLOR)
    c.label('bright'); c.emit('50 6a00 8d83'); c.word(ROWS)
    state(c, '8b93', v2.LEFT); state(c, '8b8b', v2.TOP); c.call(0x4f2910)
    c.call(DRAW + filters.BEGIN_OFFSET)
    v2.set_state(c, HOVER_NEXT, 0)
    c.emit('31ed')
    c.label('clone')
    state(c, '8b83', v2.OLD_TABLE); c.emit('8b34a8 89e8 69c0'); c.word(v2.TOWN_SIZE)
    c.emit('8dbc03'); c.word(v2.TOWNS)
    c.emit('89bcab'); c.word(v2.TABLE)
    c.emit('56 b9'); c.word(v2.TOWN_SIZE // 4); c.emit('fc f3a5 5e')
    c.emit('89e8 69c0'); c.word(v2.TOWN_SIZE); c.emit('8dbc03'); c.word(v2.TOWNS)
    for offset, function in ((0x210, v2.PROJECT_X), (0x214, v2.PROJECT_Y),
                             (0x218, v2.PROJECT_X), (0x21c, v2.PROJECT_Y)):
        c.emit('8b86'); c.word(offset); c.call(function); c.emit('8987'); c.word(offset)
    c.call(HIGHLIGHT)
    c.emit('45'); state(c, '3bab', v2.LENGTH); c.branch('0f82', 'clone')
    state(c, '8b83', HOVER_NEXT); state(c, '8983', HOVER)
    c.call(DRAW + filters.END_OFFSET)
    c.call(ROUTE_DRAW)
    # Scope only the original renderer. Original game objects are never written.
    for va, offset in ((0xb749ec, v2.OLD_X), (0xb749f0, v2.OLD_Y)):
        pointer(c, va); state(c, '8983', offset)
        v2.mem(c, 'c783', va - IMAGE_BASE); c.word(0)
    c.emit('8d83'); c.word(v2.TABLE); v2.mem(c, '8983', 0xb749e4 - IMAGE_BASE)
    c.call(0x9ebda4)
    # Native hover may start a town-info request. Preserve its four cache fields
    # so the borrowed copy does not discard the original ten-second throttle.
    c.emit('31ed')
    c.label('cache')
    state(c, '8b83', v2.OLD_TABLE); c.emit('8b34a8 89e8 69c0'); c.word(v2.TOWN_SIZE)
    c.emit('8dbc03'); c.word(v2.TOWNS)
    c.emit('8b8750020000 898650020000')
    c.emit('668b8734020000 66898634020000 8a8736020000 888636020000')
    c.emit('45'); state(c, '3bab', v2.LENGTH); c.branch('0f82', 'cache')
    state(c, '8b83', v2.OLD_TABLE); v2.mem(c, '8983', 0xb749e4 - IMAGE_BASE)
    c.call(MARKER)
    for va, offset in ((0xb749ec, v2.OLD_X), (0xb749f0, v2.OLD_Y)):
        state(c, '8b83', offset); v2.mem(c, '8983', va - IMAGE_BASE)
    c.emit('619d c3')
    c.label('update_only'); c.call(0x9edef4); c.emit('619d c3')
    c.label('stock'); c.emit('619d'); c.jump(v2.STOCK_DRAW)
    return c.finish(0x1000)


def highlight_code():
    """ESI: real town, EDI: projected copy. Records hover; draws one sprite."""
    c = Code(HIGHLIGHT); c.emit('60'); c.base()
    c.emit('0fb64608 85c0'); c.branch('0f84', 'done')
    c.emit('83f816'); c.branch('0f87', 'done')
    c.emit('807e0400'); c.branch('0f84', 'done')
    c.emit('89c5')
    # Same hover rule as the native tooltip: inside the viewport and the
    # projected rectangle, and no GUI capture.
    pointer(c, TOOLTIP_BLOCKED); c.emit('803800'); c.branch('0f85', 'pick')
    pointer(c, MOUSE_X); c.emit('8b08')
    pointer(c, MOUSE_Y); c.emit('8b10')
    state(c, '3b8b', v2.LEFT); c.branch('0f8c', 'pick')
    state(c, '8b83', v2.LEFT); state(c, '0383', v2.WIDTH); c.emit('39c1'); c.branch('0f8d', 'pick')
    state(c, '3b93', v2.TOP); c.branch('0f8c', 'pick')
    state(c, '8b83', v2.TOP); state(c, '0383', v2.HEIGHT); c.emit('39c2'); c.branch('0f8d', 'pick')
    c.emit('3b8f10020000'); c.branch('0f8c', 'pick')
    c.emit('3b8f18020000'); c.branch('0f8f', 'pick')
    c.emit('3b9714020000'); c.branch('0f8c', 'pick')
    c.emit('3b971c020000'); c.branch('0f8f', 'pick')
    state(c, '89ab', HOVER_NEXT)
    c.label('pick')
    c.emit('89e8 c1e005 8db403'); c.word(LOCATIONS)
    # While a location is hovered only it is lit; otherwise the current
    # town and the journey's final location get the dashed outline.
    state(c, '83bb', HOVER); c.emit('00'); c.branch('0f84', 'not_hovered')
    state(c, '3bab', HOVER); c.branch('0f85', 'done')
    c.emit('8b7e10'); c.branch('e9', 'draw')
    c.label('not_hovered')
    c.emit('8b7e14')
    pointer(c, CURRENT_TOWN); c.emit('3b28'); c.branch('0f84', 'draw')
    pointer(c, GAME_CHARACTER); c.emit('83b82402000000'); c.branch('0f84', 'done')
    state(c, '3bab', FINAL); c.branch('0f85', 'done')
    c.label('draw')
    c.emit('85ff'); c.branch('0f84', 'done')
    c.emit('01df')
    # Viewport rect of the sprite: x0,y0 kept in ESI/EBP; width/height pushed.
    c.emit('8b4608'); c.call(MAP_X); c.emit('50')
    c.emit('8b460c'); c.call(MAP_Y); c.emit('50')
    c.emit('8b06'); c.call(MAP_X); c.emit('89c5')
    c.emit('8b4604'); c.call(MAP_Y); c.emit('89c6')
    c.emit('5a 29f2 58 29e8')  # EDX = height, EAX = width
    c.emit('50 52 6a00 6aff 6a00')
    c.emit('89f8 89ea 89f1'); c.call(0x4f2910)
    c.label('done'); c.emit('61 c3')
    return c.finish(0x400)


def marker_code(first_row: int):
    """Draw the squad marker at the rendered position, turned along its motion."""
    c = Code(MARKER); c.emit('60'); c.base()
    pointer(c, GAME_CHARACTER, 'esi')
    c.emit('d9461c'); c.call(0x40742c); c.call(v2.PROJECT_X); c.emit('89c5')
    c.emit('d94620'); c.call(0x40742c); c.call(v2.PROJECT_Y); c.emit('89c7')
    c.emit('83be2402000000'); c.branch('0f84', 'draw')
    # Motion = stepped position - rendered position; at a stop the native
    # interpolation has caught up, so fall back to the destination.
    for first, second in ((0x0c, 0x10), (0x14, 0x18)):
        c.emit(f'db46{first:02x} d8661c'); state(c, 'da8b', v2.WIDTH)
        c.emit(f'db46{second:02x} d86620'); state(c, 'da8b', v2.HEIGHT)
        c.emit('d9c0 d8c8 d9c2 d8c8 dec1')
        c.emit('d983'); c.word(CONSTANTS - IMAGE_BASE)
        c.emit('dff1 ddd8'); c.branch('0f82', 'turn')
        c.emit('ddd8 ddd8')
    c.branch('e9', 'draw')
    c.label('turn')
    c.emit('d9c9 d9f3 d88b'); c.word(CONSTANTS - IMAGE_BASE + 4)
    state(c, 'db9b', TURN); state(c, '8b83', TURN); c.emit('83e01f'); state(c, '8983', FRAME)
    c.label('draw')
    # Side in viewport pixels: the marker scales with the map width.
    c.emit('8b83'); c.word(CONSTANTS - IMAGE_BASE + 8); state(c, '0faf83', v2.WIDTH)
    c.emit('99 b9'); c.word(MAP_WIDTH); c.emit('f7f9 89c1 d1f9 29cd 29cf')
    c.emit('50 50 6a00 6aff 6a00')
    state(c, '8b83', FRAME); c.emit('c1e005 8d8403'); c.word(ROWS + first_row * ROW_SIZE)
    c.emit('89ea 89f9')
    # Same reversible linear filtering as the location sprites.
    c.call(DRAW + filters.BEGIN_OFFSET)
    c.call(0x4f2910)
    c.call(DRAW + filters.END_OFFSET)
    c.call(0x4f2ee8)
    c.emit('61 c3')
    return c.finish(0x400)


def final_read_code():
    """Replaces the discarded read of the 1D second Z field; keeps EBX."""
    c = Code(FINAL_READ); c.call(READ_DWORD)
    c.emit('53'); c.base(); state(c, '8983', FINAL); c.emit('5b c3')
    return c.finish(0x80)


def route_read_code():
    """Replaces the discarded read of the 1D first Z field: route words."""
    c = Code(ROUTE_READ); c.call(READ_DWORD)
    c.emit('85c0'); c.branch('0f84', 'done')
    c.emit('53 51'); c.base()
    c.emit('85c0'); c.branch('0f88', 'header')
    state(c, '8b8b', ROUTE_COUNT); c.emit('81f9'); c.word(MAX_ROUTE); c.branch('0f83', 'out')
    c.emit('89848b'); c.word(ROUTE); c.emit('41'); state(c, '898b', ROUTE_COUNT)
    c.branch('e9', 'out')
    c.label('header'); v2.set_state(c, ROUTE_COUNT, 0)
    c.label('out'); c.emit('59 5b')
    c.label('done'); c.emit('c3')
    return c.finish(0x80)


def _line(c, color, offset=None):
    """One route line (X0,Y0)-(X1,Y1), shifted by constants or by ESI/EDI."""
    state(c, '8b83', Y1)
    c.emit('01f8' if offset is None else f'83c0{offset[1]:02x}'); c.emit('50 68'); c.word(color)
    state(c, '8b8b', X1); c.emit('01f1' if offset is None else f'83c1{offset[0]:02x}')
    state(c, '8b93', Y0); c.emit('01fa' if offset is None else f'83c2{offset[1]:02x}')
    state(c, '8b83', X0); c.emit('01f0' if offset is None else f'83c0{offset[0]:02x}')
    c.call(LINE)


def route_draw_code():
    """Dashed route of the journey being driven: a shadow and a 2-px gold line."""
    c = Code(ROUTE_DRAW); c.emit('60'); c.base()
    pointer(c, GAME_CHARACTER); c.emit('83b82402000000'); c.branch('0f84', 'done')
    state(c, '83bb', ROUTE_COUNT); c.emit('00'); c.branch('0f84', 'done')
    c.emit('31ed')
    c.label('dash')
    c.emit('8bb4ab'); c.word(ROUTE)
    c.emit('89f0 25ff070000'); c.call(MAP_X); state(c, '8983', X0)
    c.emit('89f0 c1e80b 25ff030000'); c.call(MAP_Y); state(c, '8983', Y0)
    c.emit('89f0 c1e006 c1f81b 89f1 81e1ff070000 01c8'); c.call(MAP_X); state(c, '8983', X1)
    c.emit('89f0 d1e0 c1f81b 89f1 c1e90b 81e1ff030000 01c8'); c.call(MAP_Y); state(c, '8983', Y1)
    # Thicken across the dash: down for flat dashes, right for steep ones.
    state(c, '8b83', X1); state(c, '2b83', X0); c.emit('99 31d0 29d0')
    state(c, '8b8b', Y1); state(c, '2b8b', Y0); c.emit('89ca c1fa1f 31d1 29d1')
    c.emit('31f6 31ff 39c8'); c.branch('0f8c', 'steep')
    c.emit('47'); c.branch('e9', 'lines')
    c.label('steep'); c.emit('46')
    c.label('lines')
    _line(c, ROUTE_SHADOW, (1, 1))
    _line(c, ROUTE_COLOR, (0, 0))
    _line(c, ROUTE_COLOR)
    c.emit('45'); state(c, '3bab', ROUTE_COUNT); c.branch('0f82', 'dash')
    c.label('done'); c.emit('61 c3')
    return c.finish(0x300)


def tip_code(address: int, original: int, width: int, height: int):
    """Native town/base tooltip next to the cursor, kept inside the map."""
    c = Code(address); visual.scope(c, v2)
    pointer(c, MOUSE_X); c.emit('8b00 83c012')
    pointer(c, MOUSE_Y, 'edx'); c.emit('8b12 83c216')
    # The chat panel covers the bottom of the map rectangle: in the lower
    # half the box opens above the cursor, so it stays on the visible map.
    state(c, '8b8b', v2.HEIGHT); c.emit('d1f9'); state(c, '038b', v2.TOP); c.emit('83c116')
    c.emit('39ca'); c.branch('0f8e', 'below')
    c.emit('81ea'); c.word(44 + height)
    c.label('below')
    state(c, '8b8b', v2.LEFT); state(c, '038b', v2.WIDTH); c.emit('81e9'); c.word(width)
    c.emit('39c8'); c.branch('0f8e', 'x_fits')
    c.emit('2d'); c.word(36 + width)
    c.label('x_fits')
    state(c, '3b83', v2.LEFT); c.branch('0f8d', 'x_left')
    state(c, '8b83', v2.LEFT)
    c.label('x_left')
    state(c, '8b8b', v2.TOP); state(c, '038b', v2.HEIGHT); c.emit('81e9'); c.word(height)
    c.emit('39ca'); c.branch('0f8e', 'y_fits')
    c.emit('89ca')
    c.label('y_fits')
    state(c, '3b93', v2.TOP); c.branch('0f8d', 'y_top')
    state(c, '8b93', v2.TOP)
    c.label('y_top')
    # The native box is drawn 8 px above-left of its anchor.
    c.emit('83c008 83c208 8944241c 89542414')
    # Park the camera far away so the native "do not cover the squad" shift
    # (half a viewport) never moves the box away from the cursor.
    pointer(c, CAMERA); c.emit('8b4808'); state(c, '898b', CAMERA_X)
    c.emit('c7400800000040')
    c.emit('619d ff742404'); c.call(original)
    c.emit('9c60'); c.base()
    pointer(c, CAMERA); state(c, '8b8b', CAMERA_X); c.emit('894808')
    c.emit('619d c20400')
    c.label('stock'); c.emit('619d'); c.jump(original)
    return c.finish(0x180)


def name_code():
    """Skip native labels of the baked locations; others (contract markers) stay."""
    c = Code(DRAW + visual.NAME_OFFSET); visual.scope(c, v2)
    c.emit('8b83'); c.word(0xb749e4 - IMAGE_BASE)
    c.emit('8b542404 8b12 85d2'); c.branch('0f88', 'stock')
    c.emit('3b50fc'); c.branch('0f83', 'stock')
    c.emit('8b0490 0fb64008 85c0'); c.branch('0f84', 'stock')
    c.emit('83f816'); c.branch('0f87', 'stock')
    c.emit('619d c20800')
    c.label('stock'); c.emit('619d'); c.jump(TEXT_DRAW)
    return c.finish(0x200)


def constants(marker_pixels: int) -> bytes:
    return struct.pack('<ffi', TURN_THRESHOLD, FRAMES_PER_RADIAN, marker_pixels).ljust(CODE_END - CONSTANTS, b'\0')


def name_record(path: str) -> bytes:
    raw = struct.pack('<HHiI', 1200, 2, -1, len(path)) + path.encode('utf-16le') + b'\0\0'
    if len(raw) > NAME_STRIDE:
        raise ValueError(f'Texture path too long for the name table: {path}')
    return raw.ljust(NAME_STRIDE, b'\0')


def tables(manifest: dict) -> dict[int, bytes]:
    """RVA -> bytes for rows, names and the per-location rectangle table."""
    paths = rows(manifest)
    if len(paths) > MAX_ROWS or len(paths) * NAME_STRIDE > NAMES_END - NAMES:
        raise ValueError('Too many map textures for the native tables')
    names = b''.join(name_record(path) for path in paths).ljust(NAMES_END - NAMES, b'\0')
    row_table = bytearray(len(paths) * ROW_SIZE)
    for index in range(len(paths)):
        # Row id 0 selects the plain loader (map); every sprite gets mips.
        struct.pack_into('<III', row_table, index * ROW_SIZE + 12, index, 0, NAMES + index * NAME_STRIDE + 12)
    locations = bytearray(23 * LOCATION_SIZE)
    for order, location in enumerate(sorted(manifest['locations'], key=lambda item: item['id'])):
        hover_row = ROWS + (1 + 2 * order) * ROW_SIZE
        struct.pack_into('<4iII', locations, location['id'] * LOCATION_SIZE,
                         *location['rect'], hover_row, hover_row + ROW_SIZE)
    return {NAMES: names, ROWS: bytes(row_table), LOCATIONS: bytes(locations)}


def code_blocks(manifest: dict) -> dict[int, bytes]:
    """VA -> bytes of every replaced or new code block."""
    marker_pixels = manifest['marker']['pixels'][0]
    return {v2.INITIALIZE: initializer_code(len(rows(manifest))), DRAW: draw_code(),
            DRAW + visual.NAME_OFFSET: name_code(), HIGHLIGHT: highlight_code(),
            MARKER: marker_code(marker_row(manifest)), FINAL_READ: final_read_code(),
            MAP_X: map_axis(MAP_X, v2.LEFT, v2.WIDTH, MAP_WIDTH),
            MAP_Y: map_axis(MAP_Y, v2.TOP, v2.HEIGHT, MAP_HEIGHT),
            CONSTANTS: constants(marker_pixels), ROUTE_READ: route_read_code(),
            ROUTE_DRAW: route_draw_code(),
            **{address: tip_code(address, original, *TIP_SIZES[address])
               for _, original, address in TIP_SITES}}


def _previous(va: int) -> bytes | None:
    """Exact v2 bytes expected where a block is replaced in place."""
    return {v2.INITIALIZE: v2.initializer_code(), DRAW: v2.draw_code(),
            DRAW + visual.NAME_OFFSET: visual.name_code(v2)}.get(va)


def patch(data: bytes, manifest: dict) -> bytes:
    if sha(data) != BASE_SHA:
        raise ValueError('Road map requires the published 2026.10.28.2 Silver')
    image = pefile.PE(data=data, fast_load=True)
    result = bytearray(data)

    def place(rva: int, blob: bytes, before: bytes | None):
        offset = image.get_offset_from_rva(rva)
        current = bytes(data[offset:offset + len(blob)])
        if before is not None and current[:len(before)] != before:
            raise ValueError(f'Unexpected native map bytes at {rva + IMAGE_BASE:#x}')
        if before is None and rva not in (NAMES, LOCATIONS) and any(current):
            raise ValueError(f'Native map space at {rva + IMAGE_BASE:#x} is not free')
        result[offset:offset + len(blob)] = blob

    for va, blob in code_blocks(manifest).items():
        place(va - IMAGE_BASE, blob, _previous(va))
    for rva, blob in tables(manifest).items():
        place(rva, blob, None)
    place(SIGNATURE_RVA, SIGNATURE, None)
    for site, native, target in ((ROUTE_HOOK, READ_DWORD, ROUTE_READ), (FINAL_HOOK, READ_DWORD, FINAL_READ),
                                 *TIP_SITES):
        offset = image.get_offset_from_rva(site - IMAGE_BASE)
        if bytes(data[offset:offset + 5]) != b'\xe8' + struct.pack('<i', native - site - 5):
            raise ValueError(f'Unexpected original call at {site:#x}')
        result[offset:offset + 5] = b'\xe8' + struct.pack('<i', target - site - 5)
    return bytes(result)


def metadata(manifest: dict) -> dict:
    return {'scope': 'Road-layout global map v3 in the native map region',
            'baseline_sha256': BASE_SHA, 'rows': rows(manifest), 'row_rva': hex(ROWS),
            'locations_rva': hex(LOCATIONS), 'names_rva': hex(NAMES), 'code_rva': hex(CODE - IMAGE_BASE),
            'original_hooks': [hex(site) for site in (ROUTE_HOOK, FINAL_HOOK, *(s for s, _, _ in TIP_SITES))], 'dim_color': hex(DIM_COLOR), 'marker_frames': MARKER_FRAMES,
            'native_labels_skipped_ids': [LOCATION_IDS.start, LOCATION_IDS.stop - 1],
            'native_path_line': False}
