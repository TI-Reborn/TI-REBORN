"""Selected classic-A icon density adapter composed after the font adapter.

Native image objects, control geometry, callbacks and state indices are kept.
Each known resource-load call first loads its original texture, then eagerly
loads four unique density resources through the same native resource manager.
Only matching original texture handles/tiles use a separate source/destination
quad. The launcher-pinned TI executable is never modified.
"""
from __future__ import annotations

import hashlib
import struct

import pefile
from .client_equipment_batch import Code

IMAGE_BASE = 0x400000
LIVE_SHA = '87645b946317a645552c3c2a5fcf586784d3920548288e2312dfb9ace065df4d'
TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
SECTION_RVA = 0x846000
SIZE = 0x7000
DRAW = IMAGE_BASE + SECTION_RVA
INITIALIZE = DRAW + 0x600
DRAW_NATIVE = DRAW + 0xc00
LOAD_WRAPPERS = DRAW + 0x1000
ROWS = SECTION_RVA + 0x2000
NAMES = SECTION_RVA + 0x3000
STATE = SECTION_RVA + 0x2f00
SIGNATURE_RVA = SECTION_RVA + 0x2e00
SIGNATURE = b'TIO-native-classic-A-icon-density-v1'
UI_SCALE_STATE = 0x828f00
DENSITIES = (100, 125, 150, 200)
# Resource, symbol, logical width/height, exact CALL Image_LoadFromFile_2.
RESOURCES = (
    ('pda_btn_1.png', 'map', 40, 40, 0xa62f84),
    ('pda_btn_2.png', 'soldier', 40, 40, 0xa62fa2),
    ('pda_btn_3.png', 'ratings', 40, 40, 0xa62fc0),
    ('pda_btn_4.png', 'money', 40, 40, 0xa62fde),
    ('squad_page_info_button.tga', 'info', 88, 31, 0xa6bdd4),
    ('squad_page_inventory_button.tga', 'rifle', 88, 31, 0xa6be10),
    ('squad_page_inventory_opts_button.png', 'wrench', 31, 31, 0xa6be2e),
    ('squad_page_mail_button.tga', 'mail', 88, 31, 0xa6bdf2),
    ('squad_page_clan_button.tga', 'squad', 88, 31, 0xa6be4c),
    ('squad_page_ally_button.tga', 'handshake', 88, 31, 0xa6be6a),
    ('squad_page_filters_button.tga', 'filter', 32, 32, 0xa6bea6),
    ('squad_page_refresh_button.tga', 'refresh', 32, 32, 0xa6bec4),
    ('squad_page_toggle_compact_one_button.tga', 'zoom-minus', 32, 32, 0xa6c02c),
    ('squad_page_toggle_compact_two_button.tga', 'zoom-plus', 32, 32, 0xa6c04a),
    ('btn_search.png', 'search', 16, 16, 0xa6b906),
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def path_for(symbol, density):
    # Native TI7492cc strips directories before the resource manager cache
    # lookup. Density must be part of the basename as well as the directory.
    return f'ui-hd\\icons\\a\\{density}\\a-{symbol}-{density}.png'


def physical(logical, density):
    # Native UV dimensions are whole source texels. Destination stays logical.
    return (logical * density + 50) // 100


def call_bytes(site, target):
    return b'\xe8' + struct.pack('<i', target - site - 5)


def inc(c, offset):
    c.emit('ff83'); c.word(STATE + offset)


def set_state(c, offset, value):
    c.emit('c783'); c.word(STATE + offset); c.word(value)


def initializer_code():
    # ESI=row, EBX=Silver base. Every native loader owns its own managed path
    # reference and uses the existing manager/Reset lifecycle, with flags2.
    c = Code(INITIALIZE); c.emit('9c60 837e0c00'); c.branch('0f85', 'done')
    inc(c, 4)
    for index in range(4):
        c.emit('6a00 6a00 6a02 8d46'); c.emit(f'{0x10 + index * 12:02x}'); c.emit('50')
        c.emit('8b4e'); c.emit(f'{0x70 + index * 4:02x}')
        c.emit('8b56'); c.emit(f'{0x60 + index * 4:02x}')
        c.emit('8b46'); c.emit(f'{0x50 + index * 4:02x}'); c.emit('01d8')
        c.call(0x4f2cb4)
    for index in range(4):
        c.emit('837e'); c.emit(f'{0x10 + index * 12:02x}'); c.emit('00')
        c.branch('0f84', 'partial')
    c.emit('c7460c01000000'); inc(c, 0x20)
    c.emit('83bb'); c.word(STATE); c.emit('00'); c.branch('0f85', 'done')
    set_state(c, 0, 1); c.branch('e9', 'done')
    c.label('partial'); c.emit('c7460cffffffff'); set_state(c, 0, -1); inc(c, 0x24)
    c.label('done'); c.emit('619d c3')
    return c.finish(0x500)


def load_code(index):
    c = Code(LOAD_WRAPPERS + index * 0x80)
    c.emit('55 89e5 ff7514 ff7510 ff750c ff7508')
    c.call(0x4f2cb4)
    # Preserve the complete native result context while adding owned resources.
    c.emit('9c60'); c.base(); c.emit('8d b3'); c.word(ROWS + index * 0x80)
    c.emit('8b4508 85c0'); c.branch('0f84', 'done')
    c.emit('8b00 8906 85c0'); c.branch('0f84', 'done')
    c.call(INITIALIZE)
    c.label('done'); c.emit('619d 5d c21000')
    return c.finish(0x80)


def draw_code():
    c = Code(DRAW)
    c.emit('55 89e5 83ec20 53 56 57 8945fc 8955f8 894df4'); c.base()
    c.emit('85c0'); c.branch('0f84', 'stock')
    c.emit('8b00 85c0'); c.branch('0f84', 'stock')
    c.emit('8db3'); c.word(ROWS); c.emit('b9'); c.word(len(RESOURCES))
    c.label('find'); c.emit('3b06'); c.branch('0f84', 'matched')
    c.emit('81c680000000 49'); c.branch('0f85', 'find'); c.branch('e9', 'stock')
    c.label('matched')
    # Match both native logical tile words; unrelated frames and effect flags
    # use the original render function with its exact incoming context.
    c.emit('8b45fc 0fb75008 3b5604'); c.branch('0f85', 'fallback')
    c.emit('0fb7500a 3b5608'); c.branch('0f85', 'fallback')
    c.emit('837d0800'); c.branch('0f85', 'fallback')
    c.emit('8b450c 83f803'); c.branch('0f87', 'fallback')
    c.emit('8b8b'); c.word(UI_SCALE_STATE); c.emit('31d2')
    for density, index in ((100, 0), (125, 1), (150, 2), (200, 3)):
        c.emit('81f9'); c.word(density); c.branch('0f84', 'density' + str(index))
    c.emit('b964000000'); c.branch('e9', 'density0')
    for index in range(4):
        c.label('density' + str(index)); c.emit('ba'); c.word(index); c.branch('e9', 'chosen')
    c.label('chosen'); c.emit('898b'); c.word(STATE + 0x10); c.emit('894e48')
    c.emit('89f0 29d8 2d'); c.word(ROWS); c.emit('c1e807 8983'); c.word(STATE + 0x14)
    c.emit('8d3c52 8d7cbe10 833f00'); c.branch('0f84', 'fallback')
    # Registered native RenderEffect derives the immutable host image base.
    c.emit('8b83'); c.word(0x6cc3fc); c.emit('85c0'); c.branch('0f84', 'fallback')
    c.emit('8138558bec51'); c.branch('0f85', 'fallback')
    c.emit('2d'); c.word(0x31bbe0); c.emit('8983'); c.word(STATE + 0x1c)
    c.emit('8945f0')
    # EDX=density index. Select physical tile sizes without changing controls.
    c.emit('8b449660 8945ec 8b449670 8945e8')
    # Allocate explicit source/destination primitive args in native push order.
    c.emit('ff75ec ff75e8 ff75f8 ff75f4 ff7604 ff7608')
    c.emit('8b4510 25000000ff 0dffffff00 50 6a00')
    c.emit('8b450c 83e001 0faf45ec 89c2')
    c.emit('8b450c d1e8 0faf45e8 89c1 8b07')
    # Increment only observed matched-render attempts and retain native frame.
    inc(c, 8); c.emit('ff4644')
    c.emit('8b7d0c 89bb'); c.word(STATE + 0x18)
    c.emit('8b7df0 81c7'); c.word(0x340610); c.emit('ffd7')
    c.emit('b801000000 5f5e5b 89ec 5d c20c00')
    c.label('fallback'); inc(c, 0xc); c.emit('ff464c')
    c.label('stock'); c.emit('8b45fc 8b55f8 8b4df4 5f5e5b 89ec 5d'); c.jump(DRAW_NATIVE)
    return c.finish(0x600)


def extension():
    result = bytearray(SIZE)
    result[:0x600] = draw_code()
    result[0x600:0xb00] = initializer_code()
    trampoline = Code(DRAW_NATIVE); trampoline.emit('558bec83c4f4'); trampoline.jump(0x4f2802)
    result[0xc00:0xc20] = trampoline.finish(0x20)
    for index, (_, symbol, width, height, _) in enumerate(RESOURCES):
        result[0x1000 + index * 0x80:0x1080 + index * 0x80] = load_code(index)
        row = ROWS - SECTION_RVA + index * 0x80
        struct.pack_into('<III', result, row + 4, width, height, 0)
        for density_index, density in enumerate(DENSITIES):
            text = path_for(symbol, density)
            header_rva = NAMES + index * 0x300 + density_index * 0xc0
            raw = struct.pack('<HHiI', 1200, 2, -1, len(text)) + text.encode('utf-16le') + b'\0\0'
            assert len(raw) <= 0xc0
            offset = header_rva - SECTION_RVA
            result[offset:offset + len(raw)] = raw
            struct.pack_into('<I', result, row + 0x50 + density_index * 4, header_rva + 12)
            struct.pack_into('<I', result, row + 0x60 + density_index * 4, physical(width, density))
            struct.pack_into('<I', result, row + 0x70 + density_index * 4, physical(height, density))
    result[SIGNATURE_RVA - SECTION_RVA:SIGNATURE_RVA - SECTION_RVA + len(SIGNATURE)] = SIGNATURE
    return bytes(result)


def patch(data, *, expected_sha):
    if sha(data) != expected_sha:
        raise ValueError('Icons require the exact reviewed font-adapter candidate')
    pe = pefile.PE(data=data)
    if pe.FILE_HEADER.Machine != 0x14c or pe.OPTIONAL_HEADER.ImageBase != IMAGE_BASE:
        raise ValueError('Unexpected native PE target')
    if pe.OPTIONAL_HEADER.SizeOfImage != SECTION_RVA:
        raise ValueError('Icons must compose after fonts at RVA846000')
    last = pe.sections[-1]
    if (last.VirtualAddress + last.Misc_VirtualSize != SECTION_RVA or
            last.PointerToRawData + last.SizeOfRawData != len(data) or
            last.Misc_VirtualSize != last.SizeOfRawData or len(data) % 0x200):
        raise ValueError('Native final section is not safely appendable')
    edits = [(0x4f27fc, bytes.fromhex('558bec83c4f4'),
              b'\xe9' + struct.pack('<i', DRAW - 0x4f27fc - 5) + b'\x90')]
    for index, (_, _, _, _, site) in enumerate(RESOURCES):
        edits.append((site, call_bytes(site, 0x4f2cb4), call_bytes(site, LOAD_WRAPPERS + index * 0x80)))
    result = bytearray(data)
    for va, before, after in edits:
        offset = pe.get_offset_from_rva(va - IMAGE_BASE)
        if data[offset:offset + len(before)] != before:
            raise ValueError(f'Native icon hook differs at {va:#x}')
        result[offset:offset + len(after)] = after
    relocated = [entry.rva for block in pe.DIRECTORY_ENTRY_BASERELOC for entry in block.entries
                 if entry.type == 3]
    if any(va - IMAGE_BASE <= rva < va - IMAGE_BASE + len(before)
           for va, before, _ in edits for rva in relocated):
        raise ValueError('Icon hook unexpectedly overlaps an absolute relocation')
    for field in ('Misc_VirtualSize', 'SizeOfRawData'):
        struct.pack_into('<I', result, last.get_field_absolute_offset(field), getattr(last, field) + SIZE)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), SECTION_RVA + SIZE)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 0)
    result.extend(extension())
    return bytes(result)


def metadata():
    return {'scope': 'Classic A native icon density adapter', 'region_rva': hex(SECTION_RVA),
            'region_size': SIZE, 'state_rva': hex(STATE), 'rows_rva': hex(ROWS), 'row_stride': 0x80,
            'state_fields': {'status': 0, 'load_rows': 4, 'draws': 8, 'matched_stock_fallback': 12,
                             'last_density': 16, 'last_resource_index': 20,
                             'last_frame': 24, 'native_ti_base': 28, 'ready_rows': 32, 'failed_rows': 36},
            'resources': [{'native_resource': 'base/pda/' + name, 'symbol': symbol,
                           'logical_size': [width, height], 'load_hook': hex(site),
                           'row_rva': hex(ROWS + index * 0x80),
                           'density_assets': ['base/' + path_for(symbol, density).replace('\\', '/')
                                              for density in DENSITIES]}
                          for index, (name, symbol, width, height, site) in enumerate(RESOURCES)],
            'native_controls_and_callbacks_unchanged': True, 'eager_load_only': True,
            'ti_binary_unchanged': True, 'graphical_validation': False, 'published': False}
