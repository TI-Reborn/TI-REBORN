"""Login window layout "B" with an Inter face, for the "new" interface only.

Silver's GUI3_CreateLoginWindow builds the native window; this adapter only
rearranges its controls afterwards (one wide panel: fields in a row, a link
bar, a framed reminder) and repaints the window's own render area. While the
login window's control tree renders, the Roboto Condensed glyph adapter takes
the native "pixel" role from a tenth table rasterized from Inter; its INIT and
UPLOAD loops load and pixel-snap that table exactly like the nine others.

The barracks interface flag (MODE, zero = "new") gates everything: with the
original interface the window, its paint and every font draw stay native.
Unknown control trees (e.g. the multi-server combobox variant) are left native.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import pefile

from .client_equipment_batch import Code

BASE = 0x400000
SOURCE_SHA = 'cae8fe433d8fd9be70600e0695ad033d388bd2c2d01c513d95b9e16dae4a81c5'
SIGNATURE = b'TIO-login-window-B-inter-v1'

REGION = 0x88a000
REGION_SIZE = 0x4000
RELAYOUT = REGION
LAYOUT = REGION + 0x100
PAINT_ENTRY = REGION + 0x600
PAINT = REGION + 0x680
RENDER_WRAP = REGION + 0xb00
DESTROY_WRAP = REGION + 0xb80
FONT_STUB = REGION + 0xc00
PLACEMENTS = REGION + 0x1d00
STATE = REGION + 0x1e00
LOGIN_WINDOW = STATE
INTER_ON = STATE + 4
APPLIED = STATE + 8
ABORTED = STATE + 0xc
SEPARATORS = STATE + 0x10
LINK_WIDTHS = STATE + 0x20
COUNTS = STATE + 0x40
EDITS = STATE + 0x60
LABELS = STATE + 0x70
CHECKS = STATE + 0x90
AREAS = STATE + 0x94
BUTTONS = STATE + 0x98
STRINGS = REGION + 0x1a00
SIGNATURE_RVA = REGION + 0x1f00
GLYPHS = REGION + 0x2000

MODE = 0x89ff04  # barracks A2 interface flag; the launcher writes 1 for "original".
CREATE_HOOK = 0x87f268      # after the "Вход" button, before the RTK warning window
CREATE_BYTES = bytes.fromhex('8b4dec8b09')
PAINT_HOOK = 0x87e900       # login render-area paint (divider + reminder text)
PAINT_BYTES = bytes.fromhex('558bec6a00')
WINDOW_VMT = 0xa31a40
RENDER_SLOT = WINDOW_VMT + 0x50
DESTROY_SLOT = WINDOW_VMT - 4
RENDER_TREE = 0xa42a34
WINDOW_DESTROY = 0xa420a8

FONT_TABLE = 0x832000
FONT_HEADER = 0x80
PIXEL_HEADER = FONT_TABLE + FONT_HEADER
INTER_HEADER = FONT_TABLE + 9 * FONT_HEADER
DRAW_TABLE = 0x82ef8b       # lea esi,[ebx+TABLE] inside the glyph draw adapter
DRAW_TABLE_BYTES = bytes.fromhex('8db300208300')
INIT_COUNT = 0x82e13f       # mov ebp,9 (startup texture loading loop)
UPLOAD_COUNT = 0x82f694     # mov ecx,9 (vertex snapping loop)
PIXEL_GLOBAL = 0x76df40
GLYPH_SIZE = 0x2c

CLASS_EDIT = 0xa2fb7c
CLASS_LABEL = 0xa30e38
CLASS_CHECK = 0xa30420
CLASS_AREA = 0xa2c1b0
CLASS_BUTTON = 0xa2ecdc
CHILDREN = 13  # close button, 2 edits, 7 labels, checkbox, render area, "Вход"

SET_BOUNDS = 0xa439d8
CENTER = 0xa43748
SET_CAPTION = 0xa42b04
LOCALIZE = 0x6675e0
TEXT_WIDTH = 0x675528
DRAW_TEXT = 0x675790
DRAW_LINE = 0x675130
STRING_CLEAR = 0x40b09c

WIDTH, HEIGHT = 576, 192    # multiples of the 32-pixel window frame tile
MARGIN = 24
LINK_Y = 96
LINE = 0xff626234           # native divider colour (ABGR)
LAMP = 0xff2c96f0           # orange lamp strips of the frame
TITLE = 0xffe6e6e6
REMINDER = 0xffb1efdb       # native reminder colour
PIXEL_FONT = 1

# (control slot, x, y, width or -1 to keep): login/password label + edit,
# remember checkbox, "Вход" button, render area at the window origin.
LAYOUT_B = (
    (EDITS, 22, 54, 180), (EDITS + 4, 214, 54, 180),
    (LABELS, 24, 36, -1), (LABELS + 4, 216, 36, -1),
    (CHECKS, 414, 36, -1), (BUTTONS + 4, 410, 52, 142), (AREAS, 0, 0, -1),
)
BOX = (16, 118, WIDTH - 16, HEIGHT - 12)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def rva(va: int) -> int:
    return va - BASE


def unicode_constant(text: str) -> bytes:
    """Delphi UnicodeString literal: header then characters; points past the header."""
    return struct.pack('<HHiI', 1200, 2, -1, len(text)) + text.encode('utf-16le') + b'\0\0'


class Strings:
    """Constant strings placed at STRINGS; offsets returned as RVAs of the characters."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.offsets: dict[str, int] = {}

    def add(self, text: str) -> int:
        if text not in self.offsets:
            self.data.extend(b'\0' * (-len(self.data) % 4))
            self.offsets[text] = STRINGS + len(self.data) + 12
            self.data.extend(unicode_constant(text))
        return self.offsets[text]


def state(c: Code, opcode: str, offset: int) -> None:
    c.emit(opcode); c.word(offset)


def set_state(c: Code, offset: int, value: int) -> None:
    state(c, 'c783', offset); c.word(value)


def relayout_code() -> bytes:
    """Called in place of `mov ecx,[ebp-14h]; mov ecx,[ecx]`; EBP is the constructor frame."""
    c = Code(BASE + RELAYOUT); c.emit('9c60'); c.base()
    state(c, '83bb', MODE); c.emit('00'); c.branch('0f85', 'done')
    c.emit('8b75e8')            # window = [ebp-18h]
    c.call(BASE + LAYOUT)
    c.label('done'); c.emit('619d 8b4dec 8b09 c3')
    return c.finish(0x100)


def layout_code() -> bytes:
    """ESI = login window, EBX = image base. Leaves the window native on any surprise."""
    c = Code(BASE + LAYOUT)
    for offset in range(0, 0x20, 4):
        set_state(c, COUNTS + offset, 0)
    c.emit('8b462c 8b4808 8b5004')   # list, count, items
    c.emit('83f9'); c.emit(f'{CHILDREN:02x}'); c.branch('0f85', 'abort')
    c.emit('31ff')
    c.label('child')
    c.emit('8b04ba 8b08')            # child, its VMT
    classes = ((CLASS_EDIT, EDITS, 0, 2), (CLASS_LABEL, LABELS, 4, 7), (CLASS_CHECK, CHECKS, 8, 1),
               (CLASS_AREA, AREAS, 12, 1), (CLASS_BUTTON, BUTTONS, 16, 2))
    for index, (cls, array, counter, limit) in enumerate(classes):
        state(c, '3b8b', rva(cls)); c.branch('0f84', f'class{index}')
    c.branch('e9', 'abort')
    for index, (cls, array, counter, limit) in enumerate(classes):
        c.label(f'class{index}')
        state(c, '8b8b', COUNTS + counter)
        c.emit('83f9'); c.emit(f'{limit:02x}'); c.branch('0f83', 'abort')
        c.emit('89848b'); c.word(array)   # mov [ebx+ecx*4+array],eax
        state(c, 'ff83', COUNTS + counter)
        c.branch('e9', 'next')
    c.label('next'); c.emit('47 83ff'); c.emit(f'{CHILDREN:02x}'); c.branch('0f82', 'child')
    for _, _, counter, limit in classes:
        state(c, '83bb', COUNTS + counter); c.emit(f'{limit:02x}'); c.branch('0f85', 'abort')

    # Fixed controls.
    c.emit('8dbb'); c.word(PLACEMENTS); c.emit('b9'); c.word(len(LAYOUT_B))
    c.label('place')
    c.emit('8b07 8b0403 8b5704 895030 8b5708 895034 8b570c 85d2'); c.branch('0f88', 'keep_width')
    c.emit('895038')
    c.label('keep_width'); c.emit('83c710 49'); c.branch('0f85', 'place')
    # "Сервисы" heading disappears; the links form one bar.
    state(c, '8b83', LABELS + 8); c.emit('c6404900')
    for k in range(4):
        state(c, '8b83', LABELS + 12 + 4 * k)
        c.emit('8b405c ba'); c.word(PIXEL_FONT); c.call(TEXT_WIDTH)
        state(c, '8983', LINK_WIDTHS + 4 * k)
    c.emit('b8'); c.word(WIDTH - 2 * MARGIN)
    for k in range(4):
        state(c, '2b83', LINK_WIDTHS + 4 * k)
    c.emit('99 b903000000 f7f9 83f80c'); c.branch('0f8d', 'gap_ok')
    c.emit('b80c000000')
    c.label('gap_ok'); c.emit('89c1 bf'); c.word(MARGIN)   # ECX = gap, EDI = x
    for k in range(4):
        state(c, '8b83', LABELS + 12 + 4 * k)
        c.emit('897830 c74034'); c.word(LINK_Y)
        state(c, '8b93', LINK_WIDTHS + 4 * k); c.emit('895038')
        c.emit('01d7')                                  # x += width
        if k < 3:
            c.emit('89c8 d1f8 01f8')                    # separator = x + gap/2
            state(c, '8983', SEPARATORS + 4 * k)
        c.emit('01cf')                                  # x += gap
    # Caption is drawn centred by the render area instead of the frame corner.
    c.emit('89f0 31d2'); c.call(SET_CAPTION)
    c.emit('68'); c.word(WIDTH); c.emit('68'); c.word(HEIGHT)
    c.emit('89f0 8b5630 8b4e34'); c.call(SET_BOUNDS)
    c.emit('89f0'); c.call(CENTER)
    state(c, '89b3', LOGIN_WINDOW); state(c, 'ff83', APPLIED); c.emit('c3')
    c.label('abort'); state(c, 'ff83', ABORTED); c.emit('c3')
    return c.finish(0x500)


def paint_entry_code() -> bytes:
    """Replaces the paint prologue; EDX/ECX = render-area origin as in the original."""
    c = Code(BASE + PAINT_ENTRY); c.emit('60'); c.base()
    state(c, '83bb', MODE); c.emit('00'); c.branch('0f85', 'stock')
    state(c, '83bb', LOGIN_WINDOW); c.emit('00'); c.branch('0f84', 'stock')
    c.call(BASE + PAINT); c.emit('61 c3')
    c.label('stock'); c.emit('61 55 8bec 6a00'); c.jump(PAINT_HOOK + len(PAINT_BYTES))
    return c.finish(0x80)


def _line(c: Code, x: int, y: int, length: int, horizontal: bool, colour: int) -> None:
    c.emit('68'); c.word(colour); c.emit('6a01' if horizontal else '6a00')
    c.emit('b9'); c.word(length)
    c.emit('8d97'); c.word(y); c.emit('8d86'); c.word(x)
    c.call(DRAW_LINE)


def _localize(c: Code, key: int) -> None:
    c.emit('8d83'); c.word(key); c.emit('8d55fc'); c.call(LOCALIZE)


def _draw_local(c: Code, y: int, colour: int) -> None:
    """Draw [ebp-4] at x=[ebp-8] (absolute) with wrap width in [ebp-0Ch]."""
    c.emit('8d87'); c.word(y); c.emit('50 68'); c.word(colour)
    c.emit('6a'); c.emit(f'{PIXEL_FONT:02x}'); c.emit('6a00')
    c.emit('8b45f4 8b55fc 8b4df8'); c.call(DRAW_TEXT)


def paint_code(strings: Strings) -> bytes:
    """ESI = x0, EDI = y0 of the window; EBX = image base."""
    title, reminder = strings.add('mn15'), strings.add('m566')
    c = Code(BASE + PAINT)
    c.emit('89d6 89cf 55 89e5 6a00 6a00 6a00')    # [ebp-4] text, [ebp-8] x, [ebp-0Ch] width
    _localize(c, title)
    c.emit('8b45fc ba'); c.word(PIXEL_FONT); c.call(TEXT_WIDTH)
    c.emit('89c1 b8'); c.word(WIDTH); c.emit('29c8 d1f8 01f0 8945f8')   # x = x0 + (W - w)/2
    c.emit('83c108 894df4')                        # wrap width = text width + 8
    _draw_local(c, 6, TITLE)
    for dy in (13, 14):
        # Left lamp: MARGIN .. title-10; right lamp: title+w+2 .. W-MARGIN.
        c.emit('68'); c.word(LAMP); c.emit('6a01')
        c.emit('8b4df8 29f1 83e9'); c.emit(f'{MARGIN + 10:02x}')
        c.emit('8d97'); c.word(dy); c.emit('8d86'); c.word(MARGIN); c.call(DRAW_LINE)
        c.emit('68'); c.word(LAMP); c.emit('6a01')
        c.emit('8b45f8 0345f4 83c002')             # right start = x + w + 2
        c.emit('8d8e'); c.word(WIDTH - MARGIN); c.emit('29c1')
        c.emit('8d97'); c.word(dy); c.call(DRAW_LINE)
    c.emit('8d45fc'); c.call(STRING_CLEAR)
    for y in (28, 88):
        _line(c, 16, y, WIDTH - 32, True, LINE)
    for k in range(3):
        c.emit('68'); c.word(LINE); c.emit('6a00 b90c000000')
        c.emit('8d97'); c.word(LINK_Y + 2)
        state(c, '8b83', SEPARATORS + 4 * k); c.emit('01f0'); c.call(DRAW_LINE)
    left, top, right, bottom = BOX
    _line(c, left, top, right - left, True, LINE)
    _line(c, left, bottom, right - left, True, LINE)
    _line(c, left, top, bottom - top, False, LINE)
    _line(c, right, top, bottom - top + 1, False, LINE)
    for dx in (2, 3):
        _line(c, left + dx, top + 6, bottom - top - 12, False, LAMP)
    _localize(c, reminder)
    c.emit('c745f4'); c.word(right - left - 28)
    c.emit('8d86'); c.word(left + 14); c.emit('8945f8')
    _draw_local(c, top + 14, REMINDER)
    c.emit('8d45fc'); c.call(STRING_CLEAR)
    c.emit('89ec 5d c3')
    return c.finish(0x480)


def render_wrap_code() -> bytes:
    """TGUIWindow.RenderTree: the login window's subtree draws the pixel role in Inter."""
    c = Code(BASE + RENDER_WRAP); c.emit('53'); c.base()
    state(c, '3b83', LOGIN_WINDOW); c.branch('0f85', 'other')
    set_state(c, INTER_ON, 1); c.emit('5b'); c.call(RENDER_TREE)
    c.emit('53'); c.base(); set_state(c, INTER_ON, 0); c.emit('5b c3')
    c.label('other'); c.emit('5b'); c.jump(RENDER_TREE)
    return c.finish(0x80)


def destroy_wrap_code() -> bytes:
    c = Code(BASE + DESTROY_WRAP); c.emit('53'); c.base()
    state(c, '3b83', LOGIN_WINDOW); c.branch('0f85', 'other')
    set_state(c, LOGIN_WINDOW, 0); set_state(c, INTER_ON, 0)
    c.label('other'); c.emit('5b'); c.jump(WINDOW_DESTROY)
    return c.finish(0x80)


def font_stub_code() -> bytes:
    """EAX = native font record, EBX = image base (glyph adapter state)."""
    c = Code(BASE + FONT_STUB); c.emit(DRAW_TABLE_BYTES.hex())
    state(c, '83bb', INTER_ON); c.emit('00'); c.branch('0f84', 'back')
    state(c, '3b83', PIXEL_HEADER + 4); c.branch('0f85', 'back')
    for density in range(4):
        state(c, '83bb', INTER_HEADER + 0x18 + 4 * density); c.emit('00'); c.branch('0f84', 'back')
    c.emit('8db3'); c.word(INTER_HEADER)
    c.label('back'); c.jump(BASE + DRAW_TABLE + len(DRAW_TABLE_BYTES))
    return c.finish(0x100)


def placements() -> bytes:
    raw = bytearray()
    for slot, x, y, width in LAYOUT_B:
        raw += struct.pack('<Iiii', slot, x, y, width)
    return bytes(raw)


def load_inter(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['result'] != 'PASS' or manifest['family'] != 'Inter' or [f['font'] for f in manifest['fonts']] != ['pixel']:
        raise ValueError('Inter login font package differs')
    for asset in manifest['assets']:
        source = manifest_path.parent / asset['path']
        if not source.is_file() or sha(source.read_bytes()) != asset['sha256']:
            raise ValueError('Inter login font resource differs')
    return manifest


def inter_header(font: dict, paths: list[int]) -> bytes:
    raw = bytearray(FONT_HEADER)
    struct.pack_into('<IIII', raw, 0, PIXEL_GLOBAL, 0, len(font['glyphs']), GLYPHS)
    for density, atlas in enumerate(font['density_sets']):
        struct.pack_into('<I', raw, 0x28 + 4 * density, atlas['width'] | (atlas['height'] << 16))
        struct.pack_into('<I', raw, 0x38 + 4 * density, paths[density])
    return bytes(raw)


def glyph_table(font: dict) -> bytes:
    raw = bytearray()
    for glyph in font['glyphs']:
        dx, dy, w, h = glyph['visual_logical_box']
        record = struct.pack('<IhhHH', glyph['codepoint'], dx, dy, w, h)
        for rect in glyph['source_rects']:
            record += struct.pack('<4H', *rect)
        if len(record) != GLYPH_SIZE:
            raise ValueError('Glyph record layout differs')
        raw += record
    return bytes(raw)


def _relocated(pe: pefile.PE) -> set[int]:
    return {e.rva for block in pe.DIRECTORY_ENTRY_BASERELOC for e in block.entries if e.type == 3}


def patch(data: bytes, inter_manifest: Path) -> bytes:
    if sha(data) != SOURCE_SHA:
        raise ValueError('Login window layout requires the reviewed 2026.11.19.3 Silver')
    pe = pefile.PE(data=data)
    relocated = _relocated(pe)
    result = bytearray(data)

    def offset(address: int) -> int:
        return pe.get_offset_from_rva(address)

    def guarded(address: int, expected: bytes, replacement: bytes) -> None:
        at = offset(address)
        if result[at:at + len(expected)] != expected or len(expected) != len(replacement):
            raise ValueError(f'Silver bytes changed at {address:#x}')
        if any(address - 3 <= r < address + len(expected) for r in relocated):
            raise ValueError(f'Relocated bytes at {address:#x}')
        result[at:at + len(expected)] = replacement

    def slot(address: int, expected: int, target: int) -> None:
        if rva(address) not in relocated:
            raise ValueError(f'VMT slot {address:#x} has no relocation')
        at = offset(rva(address))
        if struct.unpack_from('<I', result, at)[0] != expected:
            raise ValueError(f'VMT slot {address:#x} changed')
        struct.pack_into('<I', result, at, target)

    def zero(start: int, size: int) -> int:
        at = offset(start)
        if any(result[at:at + size]):
            raise ValueError(f'Region {start:#x} is not free')
        return at

    region = zero(REGION, REGION_SIZE)
    header_at = zero(INTER_HEADER, FONT_HEADER)
    if result[offset(PIXEL_HEADER):offset(PIXEL_HEADER) + 4] != struct.pack('<I', PIXEL_GLOBAL):
        raise ValueError('Pixel font role moved')

    manifest = load_inter(inter_manifest)
    font = manifest['fonts'][0]
    strings = Strings()
    paths = [strings.add(atlas['path'].replace('/', '\\')) - 12 for atlas in font['density_sets']]
    # The adapter's INIT expects the header's path RVA to point at the string header (+0Ch = text).
    glyphs = glyph_table(font)
    paint = paint_code(strings)
    if STRINGS + len(strings.data) > PLACEMENTS:
        raise ValueError('Strings overflow')
    blocks = ((RELAYOUT, relayout_code()), (LAYOUT, layout_code()), (PAINT_ENTRY, paint_entry_code()),
              (PAINT, paint), (RENDER_WRAP, render_wrap_code()), (DESTROY_WRAP, destroy_wrap_code()),
              (FONT_STUB, font_stub_code()), (PLACEMENTS, placements()),
              (SIGNATURE_RVA, SIGNATURE), (STRINGS, bytes(strings.data)), (GLYPHS, glyphs))
    for address, raw in blocks:
        start = region + address - REGION
        if address + len(raw) > REGION + REGION_SIZE or any(result[start:start + len(raw)]):
            raise ValueError(f'Block {address:#x} overlaps')
        result[start:start + len(raw)] = raw
    result[header_at:header_at + FONT_HEADER] = inter_header(font, paths)

    guarded(rva(CREATE_HOOK), CREATE_BYTES, b'\xe8' + struct.pack('<i', RELAYOUT - rva(CREATE_HOOK) - 5))
    guarded(rva(PAINT_HOOK), PAINT_BYTES, b'\xe9' + struct.pack('<i', PAINT_ENTRY - rva(PAINT_HOOK) - 5))
    guarded(DRAW_TABLE, DRAW_TABLE_BYTES, b'\xe9' + struct.pack('<i', FONT_STUB - DRAW_TABLE - 5) + b'\x90')
    guarded(INIT_COUNT, bytes.fromhex('bd09000000'), bytes.fromhex('bd0a000000'))
    guarded(UPLOAD_COUNT, bytes.fromhex('b909000000'), bytes.fromhex('b90a000000'))
    slot(RENDER_SLOT, RENDER_TREE, BASE + RENDER_WRAP)
    slot(DESTROY_SLOT, WINDOW_DESTROY, BASE + DESTROY_WRAP)
    return bytes(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('inter_manifest', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    data = args.source.read_bytes()
    candidate = patch(data, args.inter_manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(candidate)
    changed = sum(a != b for a, b in zip(data, candidate))
    print(json.dumps({'source_sha256': sha(data), 'candidate_sha256': sha(candidate), 'changed_bytes': changed}))


if __name__ == '__main__':
    main()
