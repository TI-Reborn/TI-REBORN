"""Reflow the active A2 barracks on the published 2026.11.20.12 client."""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pefile

from .client_barracks_a2 import BASE, LEFT, STATE, TABS, Rect
from .client_barracks_navigation import ARROWS
from .client_barracks_skin import _rectangle, _text, native_colour
from .client_equipment_batch import Code

SOURCE_SHA = '53887cb39a53930bd026621db10a29839f8efbc088608ea3c66ec20458068454'
LAYOUT_EXIT = 0xce922b
LAYOUT_ENTRY = 0xce9230
LAYOUT_TABLE = 0xce9400
SKIN = 0x8b0000
CAPTIONS = BASE + SKIN + 0xc000
ICON_SIZE = BASE + SKIN + 0xc300
ICON_RADII = BASE + SKIN + 0xc400
NAVIGATION = 0xcc8000
ARROW_DX = 0x89ff0c
ART_ROWS = 0x8a3000
ART_STATE = 0x8a9000
ART_COUNT = 146
SLOT_CHILDREN = ((8, 9), (10, 11), (12, 13), (14, 15, 17, 18),
                 (16, 19, 20), (21, 22, 23, 24))


def slot_rects(left: int, height: int) -> tuple[Rect, ...]:
    """Return child bounds relative to the existing equipment panel owner."""
    full = left == 430
    tall = height >= 640
    armor_width = 124 if full else 104
    armor_height = (90 if full else 86) + (16 if tall else 0)
    armor_top = 34 if tall else (18 if full else 28)
    armor = tuple(Rect(left + 28, armor_top + i * (armor_height + 23), armor_width, armor_height)
                  for i in range(3))
    weapon_height = 88 if full else 62
    top, second, device_top, device_height = (42, 153, 263, 42) if full else (35, 115, 196, 32)
    return (*armor, Rect(18, top, left - 36, weapon_height),
            Rect(18, second, left - 36, weapon_height),
            Rect(18, device_top, left - 36, device_height))


def _layout_table(left: int, height: int) -> bytes:
    slots = slot_rects(left, height)
    rows = [(child, slot) for indices, slot in zip(SLOT_CHILDREN, slots, strict=True)
            for child in indices]
    device = slots[-1]
    size = 32
    rows.append((25, Rect(device.x + 14, device.y + (device.height - size) // 2, size, size)))
    return b''.join(struct.pack('<Bhhhh', child, slot.x, slot.y, slot.width, slot.height)
                    for child, slot in rows) + b'\xff'


def _layout_code() -> tuple[bytes, bytes]:
    c = Code(LAYOUT_ENTRY)
    c.emit('83bb'); c.word(STATE); c.emit('01'); c.branch('0f85', 'done')
    c.emit('8bbb'); c.word(LEFT - BASE); c.emit('85ff'); c.branch('0f84', 'done')
    c.emit('8b572c 85d2'); c.branch('0f84', 'done')
    c.emit('837a081a'); c.branch('0f8c', 'done')
    c.emit('8b7204 85f6'); c.branch('0f84', 'done')
    c.emit('8b574c 85d2'); c.branch('0f84', 'done')
    tables = [_layout_table(left, height) for left in (330, 430) for height in (544, 640)]
    stride = len(tables[0])
    c.emit('8d8b'); c.word(LAYOUT_TABLE - BASE)
    c.emit('817a3840060000'); c.branch('0f8c', 'height')
    c.emit('81c1'); c.word(2 * stride)
    c.label('height')
    c.emit('817a3c80020000'); c.branch('0f8c', 'slot')
    c.emit('81c1'); c.word(stride)
    c.label('slot')
    c.emit('0fb611 81faff000000'); c.branch('0f84', 'model')
    c.emit('8b0496 85c0'); c.branch('0f84', 'next')
    for source, destination in ((1, 0x30), (3, 0x34), (5, 0x38), (7, 0x3c)):
        c.emit(f'0fbf51{source:02x} 8950{destination:02x}')
    c.label('next')
    c.emit('83c109'); c.branch('e9', 'slot')
    c.label('model')
    c.emit('8b4608 85c0'); c.branch('0f84', 'done')
    c.emit('8b4e20 85c9'); c.branch('0f84', 'done')
    # Centre the actor in the remaining stage, shrinking its viewport on narrow pages.
    c.emit('8b5138 035130 83c20e 89d1 8b5738 83ea0c 29ca')
    c.emit('85d2'); c.branch('0f8e', 'done')
    c.emit('395038 0f4e5038 895038')
    c.emit('8b7738 83ee0c 01ce 29d6 d1fe 897030')
    c.label('done')
    c.emit('619dc3')
    return c.finish(LAYOUT_TABLE - LAYOUT_ENTRY), b''.join(tables)


def _captions() -> bytes:
    c = Code(CAPTIONS)
    c.emit('55 89e5 83ec04 9c60 89c6'); c.base()
    c.emit('83bb'); c.word(STATE); c.emit('01'); c.branch('0f85', 'done')
    c.emit('8b464c 85c0'); c.branch('0f84', 'done')
    c.emit('3b83'); c.word(LEFT - BASE); c.branch('0f85', 'done')
    c.emit('8b402c 85c0'); c.branch('0f84', 'done')
    c.emit('83780811'); c.branch('0f8c', 'done')
    c.emit('8b4004 85c0'); c.branch('0f84', 'done')
    for child, caption in ((8, 2), (10, 3), (12, 4), (14, 5), (16, 6)):
        c.emit('8dbb'); c.word(SKIN + 0xe000 + 0x100 * caption + 12)
        c.emit('3970'); c.emit(f'{4 * child:02x}'); c.branch('0f84', 'caption')
    c.branch('e9', 'done')
    c.label('caption')
    c.emit('89f0'); c.call(0xa4211c)
    c.emit('8b5638 d1fa 01d0 8945fc 89fa 31c0'); c.call(0x4f2ba8)
    # shortcut: the pinned Font1 renderer covers 2/3 of measured width here, recalibrate on a font change.
    c.emit('31d2 b903000000 f7f1 2945fc 89f0'); c.call(0xa42140)
    c.emit('8d4806 034e3c 8b55fc 89f8 68'); c.word(native_colour(0xfff1e8c4))
    c.emit('6a00 6a00'); c.call(0x67571c)
    c.label('done'); c.emit('619d 89ec5dc3')
    return c.finish(ICON_SIZE - CAPTIONS)


def _device_skin(address: int, rect: Rect) -> bytes:
    c = Code(address)
    x, y = 12 + rect.x, 112 + rect.y
    _rectangle(c, (x, y, rect.width, rect.height), 0xff233e50)
    _rectangle(c, (x + 1, y + 1, rect.width - 2, rect.height - 2), 0xff13202a)
    _text(c, SKIN, 7, x + 63, y + (rect.height - 14) // 2, 0xffa4c6da)
    return c.finish(0x86)


def _rotation_arrow(index: int) -> bytes:
    """Anchor both arrow artwork and hit rectangles to the navigation row."""
    site, stock, _ = ARROWS[index]
    c = Code(NAVIGATION + index * 0x100)
    c.emit('9c 51 52 50 53'); c.base()
    c.emit('83bb'); c.word(STATE); c.emit('01'); c.branch('0f85', 'stock')
    c.emit('8b470c 8b404c 3b83'); c.word(LEFT - BASE); c.branch('0f85', 'stock')
    c.emit('8b83'); c.word(TABS - BASE); c.emit('85c0'); c.branch('0f84', 'stock')
    c.emit('8b5038 d1fa 52'); c.call(0xa4211c)
    c.emit('5a 01d0')
    right = index in (0, 2)
    c.emit('0383' if right else '2b83'); c.word(ARROW_DX)
    c.emit('89442404 5b58 5a59 9d')
    if right:
        c.emit('b920000000')
    if index == 3:
        c.emit('83e820')
    end = site + len(bytes.fromhex(stock))
    c.jump(end)
    c.label('stock')
    c.emit('5b58 5a59 9d')
    c.emit(stock)
    c.jump(end)
    return c.finish(0x100)


def _icon_size() -> bytes:
    c = Code(ICON_SIZE)
    c.emit('ba48000000 83bb'); c.word(ART_STATE); c.emit('01'); c.branch('0f84', 'done')
    c.emit('8b93'); c.word(ART_STATE + 8); c.emit('83ea04')
    c.emit('83bb'); c.word(ART_STATE); c.emit('02'); c.branch('0f85', 'compact')
    # Fit the visible alpha bounds of square HD artwork without stretching it.
    c.emit('50 51 8b83'); c.word(ART_STATE + 12)
    c.emit('29d8 2d'); c.word(ART_ROWS)
    c.emit('c1e805 0fb78c43'); c.word(ICON_RADII - BASE)
    c.emit('8d42fc c1e008 31d2 f7f1 89c2')
    c.emit('8b83'); c.word(ART_STATE + 4); c.emit('83e808 39c2 0f4fd0')
    c.emit('b8'); c.word(244)
    c.emit('39c2 0f4fd0 83e2fe 59 58 c3')
    c.label('compact')
    c.emit('83fa48'); c.branch('0f8e', 'done'); c.emit('ba48000000')
    c.label('done'); c.emit('c3')
    return c.finish(ICON_RADII - ICON_SIZE)


def _art_radii(pe: pefile.PE, art: Path) -> bytes:
    from PIL import Image

    radii = bytearray()
    for index in range(ART_COUNT):
        raw = pe.get_data(ART_ROWS + index * 32, 4)
        identity = struct.unpack('<I', raw)[0]
        with Image.open(art / f'tio_ii_{identity}.png') as image:
            bounds = image.getchannel('A').getbbox()
            if image.size != (512, 512) or bounds is None:
                raise ValueError(f'Unexpected HD artwork for item {identity}')
        radius = max(256 - bounds[1], bounds[3] - 256)
        radii.extend(struct.pack('<H', radius))
    return bytes(radii)


def _transfer(address: int, target: int, end: int, *, tile_loop: bool = False) -> bytes:
    c = Code(address)
    if tile_loop:
        c.emit('52')
    c.call(target)
    if tile_loop:
        c.emit('89d6 5a')
    c.jump(end)
    return bytes(c.data).ljust(end - address, b'\x90')


def patch(source: bytes, art: Path) -> bytes:
    """Patch only the reviewed client and leave the installed game untouched."""
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Unknown published Silver build')
    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        def write(address: int, payload: bytes, *, unused: bool = False) -> None:
            offset = pe.get_offset_from_rva(address - BASE)
            if unused and any(source[offset:offset + len(payload)]):
                raise ValueError(f'Reserved barracks space is in use at {address:#x}')
            result[offset:offset + len(payload)] = payload

        jump = Code(LAYOUT_EXIT)
        jump.jump(LAYOUT_ENTRY)
        code, table = _layout_code()
        write(LAYOUT_EXIT, bytes(jump.data))
        write(LAYOUT_ENTRY, code, unused=True)
        write(LAYOUT_TABLE, table, unused=True)
        write(CAPTIONS, _captions())
        write(ICON_SIZE, _icon_size(), unused=True)
        write(ICON_RADII, _art_radii(pe, art), unused=True)
        write(0xca0b30, _transfer(0xca0b30, ICON_SIZE, 0xca0b59, tile_loop=True))
        write(0xca182c, _transfer(0xca182c, ICON_SIZE, 0xca1855))
        for address, left in ((0xcb0b46, 430), (0xcb1b16, 430), (0xcb2ae6, 430),
                              (0xcb3aae, 330), (0xcb4a76, 330)):
            write(address, _device_skin(address, slot_rects(left, 544)[-1]))
        for index in range(len(ARROWS)):
            write(NAVIGATION + index * 0x100, _rotation_arrow(index))
    return bytes(result)
