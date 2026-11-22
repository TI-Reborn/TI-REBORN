"""UI fonts with their own letter metrics and Tektur window titles, "new" interface only.

The Roboto density adapter (client_ui_hd_fonts) drew new ink inside the original
pixel-font cells, so native advances made letters collide or drift apart. This
patch keeps that adapter's draw/upload code and changes its data and startup:

* the nine text font headers point at IBM Plex Sans Condensed atlases (with a baked
  1 px shadow) and glyph boxes placed from the pen;
* a tenth font object for window titles is loaded with TI add_font (TI6fecc8) from
  the native pixel.xml/png, so captions keep the native line and baseline; the
  adapter's font count becomes 10 and that header carries Tektur;
* after the adapter installs, every glyph record (TI font +0x10c + cp*28) gets the
  face's advance with zero leading/trailing, extra letter spacing becomes 0, and the
  face's GPOS pairs go through TFontLetterGroups.Spec (TI6fc64c) - the native kerning
  table the measure (TI6fdcb4) and draw (TI6fcd84) loops already read;
* every window caption that is not the main-menu title (Silver 0xc17458, the
  TGUIWindow.Paint caption path) swaps the selector-1 font index for the title font
  around the native draw, the way the menu interface swaps selector 3;
* the main-menu title (menu interface, Silver 0xc17439: y = window top + 0x16) sits
  MENU_TITLE_DROP logical pixels lower, centred between the frame rail and the first button;
* with the "original" interface (launcher flag at Silver+0x89ff04, set when Silver
  loads) nothing is loaded or started, so ti.exe draws its own pixel fonts, and the
  main-menu title keeps its original place.

Line heights and glyph tops stay native: window layouts are built on them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import pefile

from .client_equipment_batch import Code
from .client_ui_hd_fonts import (BASE, FONT_GLOBALS, FONTS, GLYPH_SIZE, HEADER_SIZE, INIT, PERCENTS,
                                 SIGNATURE, SIGNATURE_RVA, STARTUP, STATE, TABLE)

SOURCE_SHA = 'cdaa45eff2df7d0cd64a93f82449a3157e6bfd2ff17d54e2a9c7f0e866842ced'  # published 2026.11.20.2
ASSET_MANIFEST = Path(__file__).resolve().parents[1] / 'reports/ui-fonts-titles-20261120/manifest.json'
ROLES = FONTS + ('title',)
TITLE = len(FONTS)         # header index of the window-title font
MODE = 0x89ff04            # Silver RVA; zero = "new" interface (launcher NativeInterfaceMode)
SPEC = 0x6fc64c            # TI TFontLetterGroups.Spec(EAX=self, EDX=code1, ECX=code2, [ESP+4]=shift); ret 4
ADD_FONT = 0x6fecc8        # TI add_font(EAX=manager, EDX=xml ShortString, ECX=png ShortString) -> index
PROLOGUE = bytes.fromhex('558bec83')
FONT_MANAGER = 0x76e180    # TI [[0x76e180]] = font manager
SELECTOR_1 = 0x76df40      # TI [[0x76df40]] = font index behind selector 1 ("pixel"), used by captions
# Immediates holding the adapter's font count (9): INIT loop, DRAW loop and index, UPLOAD loop.
FONT_COUNT_SITES = ((0x82e13f, 0xbd), (0x82ef91, 0xbf), (0x82efb1, 0xb8), (0x82f694, 0xb9))
CAPTION_JUMP = 0x817458    # Silver RVA: jmp TGUIWindow caption draw (non-menu windows)
CAPTION_DRAW = 0x4f29a8    # Silver VA of that draw (EAX=selector, EDX=text, ECX=x, 2 stack args, ret 8)
MENU_TITLE_SITE = 0x817439  # Silver RVA: add eax,16h; mov [esp+0Ch],eax (main-menu title y argument)
MENU_TITLE_BYTES = bytes.fromhex('83c0168944240c')
MENU_TITLE_DROP = 18       # logical px; measured on a 150 % client: rail ends 369, button starts 445
REGION = 0x8eb000          # appended after .tioscr (old SizeOfImage)
REGION_SIZE = 0x34000
ENTRY = REGION             # replaces STARTUP's call to the Roboto INIT
APPLY = REGION + 0x200
TITLE_DRAW = REGION + 0x600
SWAP = REGION + 0x680
MENU_TITLE_Y = REGION + 0x700
STATE_NEW = REGION + 0x800  # +0 applied (1) / skipped by mode (2), +4 native code changed, +8 pairs applied
SPEC_PTR = STATE_NEW + 0x20
TITLE_INDEX = STATE_NEW + 0x24  # title font index; -1 until loaded (the swap does nothing)
TITLE_PTR = STATE_NEW + 0x28    # -> TITLE_INDEX, the double indirection INIT expects of a font global
TITLE_LOADED = STATE_NEW + 0x2c
SIGNATURE_NEW = b'TIO-UI-fonts-metrics-titles-v2'
SIGNATURE_NEW_RVA = STATE_NEW + 0x40
TITLE_XML = STATE_NEW + 0x80    # ShortStrings, like the menu interface's base/fonts/menu.xml
TITLE_PNG = STATE_NEW + 0xa0
ROLE_TABLE = REGION + 0xa00
ROLE_SIZE = 0x20
DATA = REGION + 0x1000
TI_GLYPH = 0x10c           # font + 0x10c + codepoint*28: top, x, y, width, height, leading, trailing
TI_EXTRA_SPACING = 0x1c032c
TI_SPACE_ADVANCE = 0x1c032d
TI_KERNING = 0x108


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_assets(path: Path = ASSET_MANIFEST) -> dict:
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest['result'] != 'PASS' or manifest['schema'] != 2:
        raise ValueError('Unexpected font package')
    if manifest['scales'] != list(PERCENTS) or tuple(f['font'] for f in manifest['fonts']) != ROLES:
        raise ValueError('Font package roles or densities differ from the adapter')
    if manifest['fonts'][TITLE]['native_xml'] != 'pixel':
        raise ValueError('The title font must keep the native pixel line metrics')
    for asset in manifest['assets']:
        raw = (path.parent / asset['path']).read_bytes()
        if not asset['path'].startswith('base/ui-hd/') or sha(raw) != asset['sha256']:
            raise ValueError(f'Font resource differs: {asset["path"]}')
    return manifest


def entry_code() -> bytes:
    c = Code(BASE + ENTRY)
    c.emit('9c60'); c.base()
    c.emit('80bb'); c.word(MODE); c.emit('00'); c.branch('0f85', 'original')
    # Without the native setter or loader the new metrics would be half applied: keep stock fonts.
    for native in (SPEC, ADD_FONT):
        c.emit('813d'); c.word(native); c.emit(PROLOGUE.hex()); c.branch('0f85', 'native_changed')
    c.emit('83bb'); c.word(TITLE_LOADED); c.emit('00'); c.branch('0f85', 'init')
    c.emit('c783'); c.word(TITLE_LOADED); c.word(1)
    c.emit('a1'); c.word(FONT_MANAGER); c.emit('8b00')
    c.emit('8d93'); c.word(TITLE_XML); c.emit('8d8b'); c.word(TITLE_PNG)
    c.emit('bf'); c.word(ADD_FONT); c.emit('ffd7')
    c.emit('8983'); c.word(TITLE_INDEX)
    c.emit('8d83'); c.word(TITLE_INDEX); c.emit('8983'); c.word(TITLE_PTR)
    c.emit('8d83'); c.word(TITLE_PTR); c.emit('8983'); c.word(TABLE + TITLE * HEADER_SIZE)
    c.label('init')
    c.call(INIT)  # INIT and STARTUP are virtual addresses at the preferred base
    c.emit('83bb'); c.word(STATE); c.emit('01'); c.branch('0f85', 'done')
    c.emit('83bb'); c.word(STATE + 0xc); c.emit('01'); c.branch('0f85', 'done')
    c.emit('83bb'); c.word(STATE_NEW); c.emit('00'); c.branch('0f85', 'done')
    c.emit('c783'); c.word(STATE_NEW); c.word(1)
    c.call(BASE + APPLY); c.branch('e9', 'done')
    c.label('original'); c.emit('c783'); c.word(STATE_NEW); c.word(2); c.branch('e9', 'done')
    c.label('native_changed'); c.emit('c783'); c.word(STATE_NEW + 4); c.word(1)
    c.label('done'); c.emit('619d c3')
    return c.finish(0x200)


def apply_code() -> bytes:
    """EBX = Silver base. Writes metrics into each resolved TI font object."""
    c = Code(BASE + APPLY)
    c.emit('8db3'); c.word(ROLE_TABLE); c.emit('bd'); c.word(len(ROLES))
    c.label('role')
    c.emit('8b06 8b7c0304 85ff'); c.branch('0f84', 'next_role')       # EDI = header +4 font object
    c.emit('8b4e08 8b5604 01da 85c9'); c.branch('0f84', 'spacing')
    c.label('glyph')
    c.emit('51 0fb702 6bc01c 8d84070c010000')                          # EAX = glyph record
    c.emit('0fbf4a04 8908')                                            # top
    c.emit('0fb74a02 89480c')                                          # width = advance
    c.emit('0fb74a06 894810')                                          # height
    c.emit('31c9 894814 894818')                                       # leading = trailing = 0
    c.emit('83c208 59 49'); c.branch('0f85', 'glyph')
    c.label('spacing')
    c.emit('c687'); c.word(TI_EXTRA_SPACING); c.emit('00')
    c.emit('8a4614 8887'); c.word(TI_SPACE_ADVANCE)
    c.emit('8b4e10 8b560c 01da 85c9'); c.branch('0f84', 'next_role')
    c.label('pair')
    c.emit('51 52 ff7204 0fb74a02 0fb712 8b87'); c.word(TI_KERNING)
    c.emit('ff93'); c.word(SPEC_PTR)                                   # pops the shift (ret 4)
    c.emit('ff83'); c.word(STATE_NEW + 8)
    c.emit('5a 59 83c208 49'); c.branch('0f85', 'pair')
    c.label('next_role'); c.emit('83c620 4d'); c.branch('0f85', 'role')
    c.emit('c3')
    return c.finish(0x400)


def title_draw_code() -> bytes:
    """Caption draw with the title font behind selector 1; registers and stack ABI unchanged."""
    c = Code(BASE + TITLE_DRAW)
    c.call(BASE + SWAP)
    c.emit('ff742408 ff742408')  # the two stack arguments, as the menu caption path does
    c.call(CAPTION_DRAW)
    c.call(BASE + SWAP)
    c.emit('c20800')
    return c.finish(0x80)


def swap_code() -> bytes:
    """Exchange the selector-1 font index with TITLE_INDEX; a no-op until the title font loaded."""
    c = Code(BASE + SWAP)
    c.emit('60'); c.base()
    c.emit('8b83'); c.word(TITLE_INDEX); c.emit('83f8ff'); c.branch('0f84', 'out')
    c.emit('8b15'); c.word(SELECTOR_1); c.emit('85d2'); c.branch('0f84', 'out')
    c.emit('8702'); c.emit('8983'); c.word(TITLE_INDEX)
    c.label('out'); c.emit('61 c3')
    return c.finish(0x80)


def menu_title_y_code() -> bytes:
    """Replaces 'add eax,16h; mov [esp+0Ch],eax'; EAX = window top, flags are dead afterwards."""
    c = Code(BASE + MENU_TITLE_Y)
    c.emit('83c016 53'); c.base()
    c.emit('80bb'); c.word(MODE); c.emit('00 5b'); c.branch('0f85', 'store')
    c.emit('83c0'); c.emit(f'{MENU_TITLE_DROP:02x}')
    c.label('store'); c.emit('89442410 c3')  # the caller's [esp+0Ch] behind our return address
    return c.finish(0x40)


def unicode_string(text: str) -> bytes:
    # Same UnicodeString record the Roboto adapter passes to TI7404fc (INIT adds 0xc).
    return struct.pack('<HHiI', 1200, 2, -1, len(text)) + text.encode('utf-16le') + b'\0\0'


def short_string(text: str) -> bytes:
    raw = text.encode('ascii')
    return bytes([len(raw)]) + raw


def region(manifest: dict) -> tuple[bytes, list[dict]]:
    """New region bytes and, per font, the header fields the adapter reads."""
    data = bytearray(REGION_SIZE)
    cursor = DATA

    def put(raw: bytes, align: int = 4) -> int:
        nonlocal cursor
        at = cursor
        if at + len(raw) > REGION + REGION_SIZE:
            raise ValueError('Font metrics exceed the appended region')
        data[at - REGION:at - REGION + len(raw)] = raw
        cursor = (at + len(raw) + align - 1) & ~(align - 1)
        return at

    def place(at: int, raw: bytes) -> None:
        data[at - REGION:at - REGION + len(raw)] = raw

    headers = []
    for index, font in enumerate(manifest['fonts']):
        paths = [put(unicode_string(atlas['path'].replace('/', '\\'))) for atlas in font['density_sets']]
        table = bytearray()
        for glyph in font['glyphs']:
            dx, dy, w, h = glyph['visual_logical_box']
            raw = struct.pack('<IhhHH', glyph['codepoint'], dx, dy, w, h)
            for rect in glyph['source_rects']:
                raw += struct.pack('<4H', *rect)
            if len(raw) != GLYPH_SIZE:
                raise ValueError('Adapter glyph record differs')
            table += raw
        glyphs = put(bytes(table))
        metrics = put(b''.join(struct.pack('<HHhH', g['codepoint'], g['advance'], g['top'], g['height'])
                               for g in font['glyphs']))
        pairs = put(b''.join(struct.pack('<HHi', a, b, s) for a, b, s in font['kerning']))
        struct.pack_into('<IIIIIB', data, ROLE_TABLE - REGION + index * ROLE_SIZE,
                         TABLE + index * HEADER_SIZE, metrics, len(font['glyphs']), pairs,
                         len(font['kerning']), font['space_advance'])
        headers.append({'count': len(font['glyphs']), 'glyphs': glyphs, 'paths': paths,
                        'sizes': [a['width'] | (a['height'] << 16) for a in font['density_sets']]})
    for at, code in ((ENTRY, entry_code()), (APPLY, apply_code()), (TITLE_DRAW, title_draw_code()),
                     (SWAP, swap_code()), (MENU_TITLE_Y, menu_title_y_code())):
        place(at, code)
    place(SPEC_PTR, struct.pack('<I', SPEC))  # absolute TI address: ti.exe is never relocated
    place(TITLE_INDEX, struct.pack('<i', -1))
    place(SIGNATURE_NEW_RVA, SIGNATURE_NEW)
    place(TITLE_XML, short_string('base/fonts/pixel.xml'))
    place(TITLE_PNG, short_string('base/fonts/pixel.png'))
    return bytes(data), headers


def patch(source: bytes, assets: Path = ASSET_MANIFEST) -> bytes:
    if sha(source) != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.20.2 Silver')
    manifest = load_assets(assets)
    result = bytearray(source)
    with pefile.PE(data=source, fast_load=True) as pe:
        last, header = pe.sections[-1], pe.OPTIONAL_HEADER
        if (last.Name.rstrip(b'\0') != b'.tioscr' or header.SizeOfImage != REGION
                or last.VirtualAddress + last.Misc_VirtualSize != REGION
                or last.SizeOfRawData != last.Misc_VirtualSize
                or last.PointerToRawData + last.SizeOfRawData != len(source)):
            raise ValueError('Silver is not safely appendable')

        def offset(rva: int) -> int:
            return pe.get_offset_from_rva(rva)

        if source[offset(SIGNATURE_RVA):offset(SIGNATURE_RVA) + len(SIGNATURE)] != SIGNATURE:
            raise ValueError('Roboto font adapter is missing')
        stub = offset(STARTUP - BASE)
        if source[stub] != 0xe8 or STARTUP + 5 + struct.unpack_from('<i', source, stub + 1)[0] != INIT:
            raise ValueError('Font adapter startup call changed')
        for index, global_va in enumerate(FONT_GLOBALS):
            if struct.unpack_from('<I', source, offset(TABLE + index * HEADER_SIZE))[0] != global_va:
                raise ValueError('Font adapter header changed')
        title_header = offset(TABLE + TITLE * HEADER_SIZE)
        if any(source[title_header:title_header + HEADER_SIZE]):
            raise ValueError('The tenth font header is occupied')
        for rva, opcode in FONT_COUNT_SITES:
            if source[offset(rva):offset(rva) + 5] != bytes([opcode]) + struct.pack('<I', len(FONTS)):
                raise ValueError(f'Font count immediate changed at {rva:#x}')
        caption = offset(CAPTION_JUMP)
        if source[caption] != 0xe9 or BASE + CAPTION_JUMP + 5 + struct.unpack_from('<i', source, caption + 1)[0] != CAPTION_DRAW:
            raise ValueError('Window caption path changed')
        menu_title = offset(MENU_TITLE_SITE)
        if source[menu_title:menu_title + len(MENU_TITLE_BYTES)] != MENU_TITLE_BYTES:
            raise ValueError('Main-menu title position changed')
        new_region, headers = region(manifest)
        result[menu_title:menu_title + 7] = (b'\xe8' + struct.pack('<i', MENU_TITLE_Y - MENU_TITLE_SITE - 5)
                                             + b'\x90\x90')
        struct.pack_into('<i', result, stub + 1, ENTRY - (STARTUP - BASE) - 5)
        for rva, _ in FONT_COUNT_SITES:
            struct.pack_into('<I', result, offset(rva) + 1, len(ROLES))
        struct.pack_into('<i', result, caption + 1, TITLE_DRAW - CAPTION_JUMP - 5)
        for index, fields in enumerate(headers):
            at = offset(TABLE + index * HEADER_SIZE)
            struct.pack_into('<II', result, at + 8, fields['count'], fields['glyphs'])
            struct.pack_into('<4I', result, at + 0x28, *fields['sizes'])
            struct.pack_into('<4I', result, at + 0x38, *fields['paths'])
        for field in ('Misc_VirtualSize', 'SizeOfRawData'):
            struct.pack_into('<I', result, last.get_field_absolute_offset(field), REGION_SIZE + getattr(last, field))
        struct.pack_into('<I', result, header.get_field_absolute_offset('SizeOfImage'), REGION + REGION_SIZE)
        struct.pack_into('<I', result, header.get_field_absolute_offset('CheckSum'), 0)
    return bytes(result) + new_region


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    source = args.source.read_bytes()
    candidate = patch(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(candidate)
    print(json.dumps({'source_sha256': sha(source), 'candidate_sha256': sha(candidate),
                      'region_rva': hex(REGION), 'region_size': hex(REGION_SIZE)}))


if __name__ == '__main__':
    main()
