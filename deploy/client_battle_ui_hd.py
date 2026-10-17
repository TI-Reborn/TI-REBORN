"""Bounded item/battle icon source-density extension for the reviewed client.

Original image records, layout, callbacks and resource names remain intact.
Known loaders register original texture handles and load separate HD resources.
Only the two native image drawing APIs use source/destination separation; all
unmatched calls retain the existing PDA HD adapter or the original renderer.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

import pefile
from .client_equipment_batch import Code

ROOT = Path(__file__).resolve().parents[1]
IMAGE_BASE = 0x400000
BASE_RVA = 0x84d000
SIZE = 0xd000
DRAW = IMAGE_BASE + BASE_RVA
DRAW_SCALED = DRAW + 0x600
LOAD_ONE = DRAW + 0xc00
LOAD_ONE_NATIVE = DRAW + 0xe00
INITIALIZE = DRAW + 0xf00
LOAD_TWO = DRAW + 0x1100
DRAW_SCALED_NATIVE = DRAW + 0x1400
REGISTER = DRAW + 0x1500
ROWS = BASE_RVA + 0x2000
ROW_SIZE = 0x40
NAMES = BASE_RVA + 0x4000
STATE = BASE_RVA + 0x3f00
SIGNATURE_RVA = BASE_RVA + 0xcf00
SIGNATURE = b'TIO-battle-item-icon-density-v1'
ORIGINAL_HD_DRAW = 0xc46000
DENSITY = 4


def sha(data):
    return hashlib.sha256(data).hexdigest()


def resources():
    tasks = json.loads((ROOT / 'assets/equipment-textures-v1/tasks.json').read_text(encoding='utf-8'))
    result = []
    for task in tasks:
        if task['kind'] != 'icon':
            continue
        name = Path(task['path']).name
        w, h = task['source_size']
        result.append({'native_path': 'items\\' + name, 'logical_size': [w, h],
                       'hd_path': 'ui-hd\\battle-items\\hd4-' + task['id'] + '.png',
                       'columns': 1, 'frames': 1, 'kind': 'item', 'id': task['id']})
    result.extend([
        {'native_path': 'pda\\bui_controls_btn.png', 'logical_size': [46, 46],
         'hd_path': 'ui-hd\\battle-controls\\hd4-bui-plates.png', 'columns': 4,
         'frames': 4, 'kind': 'battle', 'load_hook': 0xa6b834, 'id': 'battle-plates'},
        {'native_path': 'pda\\bui_controls_btn2.png', 'logical_size': [46, 46],
         'hd_path': 'ui-hd\\battle-controls\\hd4-bui-glyphs.png', 'columns': 6,
         'frames': 15, 'kind': 'battle', 'load_hook': 0xa6b852, 'id': 'battle-glyphs'},
    ])
    assert len(result) == 117
    assert len({r['hd_path'].rsplit('\\', 1)[-1] for r in result}) == len(result)
    return result


RESOURCES = resources()
ITEM_COUNT = sum(r['kind'] == 'item' for r in RESOURCES)


def initialize_code():
    # EBX=image base, ESI=matching row. Native managed loader owns the path.
    c = Code(INITIALIZE)
    c.emit('9c60 837e1400'); c.branch('0f85', 'done')
    c.emit('ff83'); c.word(STATE)
    c.emit('6a00 6a00 6a02 8d4614 50 8b4e30 8b562c 8b4628 01d8')
    c.call(0x4f2cb4)
    c.emit('837e1400'); c.branch('0f84', 'failed')
    c.emit('ff83'); c.word(STATE + 4); c.branch('e9', 'done')
    c.label('failed'); c.emit('ff83'); c.word(STATE + 8)
    c.label('done'); c.emit('619d c3')
    return c.finish(0x200)


def register_code():
    # Match the complete managed native path, using ASCII case folding. HD
    # paths cannot match. Each original texture remains its native manager's.
    # EAX=path; EDX=native output record; EBX=base. Scratch registers allowed.
    c = Code(REGISTER)
    c.emit('85c0'); c.branch('0f84', 'done')
    c.emit('85d2'); c.branch('0f84', 'done')
    c.emit('833a00'); c.branch('0f84', 'done')
    c.emit('89c7 89d5 8db3'); c.word(ROWS)
    c.emit('b9'); c.word(ITEM_COUNT)
    c.label('row'); c.emit('8b47fc 3b4624'); c.branch('0f85', 'next')
    c.emit('51 56 57 8b4620 01d8 89c6 8b4ffc')
    c.label('letter'); c.emit('0fb706 0fb717 83f841'); c.branch('0f82', 'left_ready')
    c.emit('83f85a'); c.branch('0f87', 'left_ready'); c.emit('83c820')
    c.label('left_ready'); c.emit('83fa41'); c.branch('0f82', 'right_ready')
    c.emit('83fa5a'); c.branch('0f87', 'right_ready'); c.emit('83ca20')
    c.label('right_ready'); c.emit('39d0'); c.branch('0f85', 'different')
    c.emit('83c602 83c702 49'); c.branch('0f85', 'letter')
    c.emit('5f 5e 59 0fb74508 3b4604'); c.branch('0f85', 'done')
    c.emit('0fb7450a 3b4608'); c.branch('0f85', 'done')
    c.emit('8b4500 8906'); c.call(INITIALIZE); c.branch('e9', 'done')
    c.label('different'); c.emit('5f 5e 59')
    c.label('next'); c.emit('83c640 49'); c.branch('0f85', 'row')
    c.label('done'); c.emit('c3')
    return c.finish(0x500)


def load_one_code():
    c = Code(LOAD_ONE)
    c.emit('55 89e5 83ec08 8945fc 894df8')
    c.call(LOAD_ONE_NATIVE)
    c.emit('9c60'); c.base()
    c.emit('8b45fc 8b55f8'); c.call(REGISTER)
    c.emit('619d 89ec 5d c3')
    return c.finish(0x200)


def load_two_code(index):
    c = Code(LOAD_TWO + index * 0x100)
    c.emit('55 89e5 ff7514 ff7510 ff750c ff7508'); c.call(0x4f2cb4)
    c.emit('9c60'); c.base()
    c.emit('8d b3'); c.word(ROWS + (ITEM_COUNT + index) * ROW_SIZE)
    c.emit('8b4508 85c0'); c.branch('0f84', 'done')
    c.emit('8b00 85c0'); c.branch('0f84', 'done')
    c.emit('8906'); c.call(INITIALIZE)
    c.label('done'); c.emit('619d 5d c21000')
    return c.finish(0x100)


def draw_code(scaled=False):
    c = Code(DRAW_SCALED if scaled else DRAW)
    c.emit('55 89e5 83ec20 53 56 57 8945fc 8955f8 894df4'); c.base()
    c.emit('85c0'); c.branch('0f84', 'stock')
    c.emit('8b00 85c0'); c.branch('0f84', 'stock')
    c.emit('8db3'); c.word(ROWS); c.emit('b9'); c.word(len(RESOURCES))
    c.label('find'); c.emit('3b06'); c.branch('0f84', 'matched')
    c.emit('83c640 49'); c.branch('0f85', 'find'); c.branch('e9', 'stock')
    c.label('matched')
    c.emit('8b45fc 0fb75008 3b5604'); c.branch('0f85', 'stock')
    c.emit('0fb7500a 3b5608'); c.branch('0f85', 'stock')
    if not scaled:
        # Effect-bearing default draws retain their complete original path.
        c.emit('837d0800'); c.branch('0f85', 'stock')
    else:
        # Original TI741370 ignores flags for its rectangular thumbnail path;
        # only the observed plain/default item form is routed here. Preserve
        # unreviewed modes even though this original renderer ignores them.
        c.emit('837d0800'); c.branch('0f84', 'scaled_flags_ready')
        c.emit('817d0802010000'); c.branch('0f85', 'stock')
        c.label('scaled_flags_ready')
    c.emit('8b4510' if scaled else '8b450c')
    c.emit('3b4610'); c.branch('0f83', 'stock')
    c.emit('837e1400'); c.branch('0f84', 'stock')
    c.emit('8b83'); c.word(0x6cc3fc); c.emit('85c0'); c.branch('0f84', 'stock')
    c.emit('8138558bec51'); c.branch('0f85', 'stock')
    c.emit('2d'); c.word(0x31bbe0); c.emit('8945f0')
    # Explicit original destination dimensions prevent UI layout inflation.
    c.emit('ff762c ff7630 ff75f8 ff75f4')
    if scaled:
        c.emit('ff7518 ff7514')
    else:
        c.emit('ff7604 ff7608')
    # Native EffectCol_1's bridge first converts colour through TI5f33c4;
    # TextureMapRect_2 supplies GPU colour words directly. Both retain the
    # caller's colour after the explicit primitive's TI749a3c conversion when
    # we use the original colour converter here. All alpha bits survive.
    # Silver scaled args are flags,tint,frame,height,width (not EffectCol order).
    c.emit('8b450c' if scaled else '8b4510')
    c.emit('8b7df0 81c7'); c.word(0x1f33c4); c.emit('ffd7 50 6a00')
    # Atlas source uses its own column count; item icons have one frame.
    c.emit('8b4510' if scaled else '8b450c')
    c.emit('31d2 f7760c 0faf562c 0faf4630 89c1 8b4614')
    c.emit('ff83'); c.word(STATE + (16 if scaled else 12)); c.emit('ff4638')
    c.emit('8b7df0 81c7'); c.word(0x340610); c.emit('ffd7')
    c.emit('b801000000 5f5e5b 89ec 5d')
    c.emit('c21400' if scaled else 'c20c00')
    c.label('stock'); c.emit('8b45fc 8b55f8 8b4df4 5f5e5b 89ec 5d')
    c.jump(DRAW_SCALED_NATIVE if scaled else ORIGINAL_HD_DRAW)
    return c.finish(0x600)


def extension():
    result = bytearray(SIZE)
    result[:0x600] = draw_code()
    result[0x600:0xc00] = draw_code(True)
    result[0xc00:0xe00] = load_one_code()
    c = Code(LOAD_ONE_NATIVE); c.emit('558bec515356'); c.jump(0x4f2c56)
    result[0xe00:0xe20] = c.finish(0x20)
    result[0xf00:0x1100] = initialize_code()
    for i in range(2): result[0x1100 + i * 0x100:0x1200 + i * 0x100] = load_two_code(i)
    c = Code(DRAW_SCALED_NATIVE); c.emit('558bec83c4f4'); c.jump(0x4f2916)
    result[0x1400:0x1420] = c.finish(0x20)
    result[0x1500:0x1a00] = register_code()
    for i, resource in enumerate(RESOURCES):
        row = ROWS - BASE_RVA + i * ROW_SIZE
        w, h = resource['logical_size']
        struct.pack_into('<IIII', result, row + 4, w, h, resource['columns'], resource['frames'])
        for name, at in [('native_path', 0), ('hd_path', 0x80)]:
            value = resource[name]
            header_rva = NAMES + i * 0x100 + at
            raw = struct.pack('<HHiI', 1200, 2, -1, len(value)) + value.encode('utf-16le') + b'\0\0'
            assert len(raw) <= 0x80, value
            off = header_rva - BASE_RVA
            result[off:off + len(raw)] = raw
            struct.pack_into('<I', result, row + (0x20 if name == 'native_path' else 0x28), header_rva + 12)
        struct.pack_into('<I', result, row + 0x24, len(resource['native_path']))
        struct.pack_into('<II', result, row + 0x2c, w * DENSITY, h * DENSITY)
    off = SIGNATURE_RVA - BASE_RVA
    result[off:off + len(SIGNATURE)] = SIGNATURE
    return bytes(result)


def patch(data, *, expected_sha):
    if sha(data) != expected_sha:
        raise ValueError('Battle UI HD requires the exact reviewed tooltip candidate')
    p = pefile.PE(data=data)
    if p.FILE_HEADER.Machine != 0x14c or p.OPTIONAL_HEADER.ImageBase != IMAGE_BASE:
        raise ValueError('Unexpected native image')
    if p.OPTIONAL_HEADER.SizeOfImage != BASE_RVA:
        raise ValueError('Unexpected battle UI HD append boundary')
    last = p.sections[-1]
    if (last.VirtualAddress + last.Misc_VirtualSize != BASE_RVA or
            last.PointerToRawData + last.SizeOfRawData != len(data) or
            last.Misc_VirtualSize != last.SizeOfRawData or len(data) % 0x200):
        raise ValueError('Native final section is not safely appendable')
    def branch(va, target): return b'\xe9' + struct.pack('<i', target - va - 5) + b'\x90'
    def call(va, target): return b'\xe8' + struct.pack('<i', target - va - 5)
    edits = [
        (0x4f27fc, branch(0x4f27fc, ORIGINAL_HD_DRAW), branch(0x4f27fc, DRAW)),
        (0x4f2910, bytes.fromhex('558bec83c4f4'), branch(0x4f2910, DRAW_SCALED)),
        (0x4f2c50, bytes.fromhex('558bec515356'), branch(0x4f2c50, LOAD_ONE)),
    ]
    for i, resource in enumerate(RESOURCES[ITEM_COUNT:]):
        va = resource['load_hook']
        edits.append((va, call(va, 0x4f2cb4), call(va, LOAD_TWO + i * 0x100)))
    out = bytearray(data)
    for va, before, after in edits:
        offset = p.get_offset_from_rva(va - IMAGE_BASE)
        if data[offset:offset + len(before)] != before:
            raise ValueError(f'Battle icon native hook differs at {va:#x}')
        out[offset:offset + len(after)] = after
    relocations = [e.rva for block in p.DIRECTORY_ENTRY_BASERELOC for e in block.entries if e.type == 3]
    if any(va - IMAGE_BASE <= r < va - IMAGE_BASE + len(before)
           for va, before, _ in edits for r in relocations):
        raise ValueError('Battle icon hook overlaps an absolute relocation')
    for field in ('Misc_VirtualSize', 'SizeOfRawData'):
        struct.pack_into('<I', out, last.get_field_absolute_offset(field), getattr(last, field) + SIZE)
    struct.pack_into('<I', out, p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), BASE_RVA + SIZE)
    struct.pack_into('<I', out, p.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 0)
    out.extend(extension())
    return bytes(out)


def metadata():
    return {'scope': 'Native item and battle icon source density', 'region_rva': hex(BASE_RVA),
            'region_size': SIZE, 'rows_rva': hex(ROWS), 'row_stride': ROW_SIZE,
            'state_rva': hex(STATE), 'item_count': ITEM_COUNT, 'battle_resources': 2,
            'density': DENSITY, 'resources': RESOURCES,
            'native_image_records_preserved': True, 'existing_pda_hd_adapter_preserved': True,
            'original_resource_files_preserved': True, 'native_tint_preserved': True,
            'renderer_variants': ['Image_RenderEffect', 'TextureMapRect_2'],
            'graphical_validation': False, 'published': False}


def repair_published(data, *, expected_sha):
    """Replace only the reviewed draw code in the exact v1 published image."""
    if sha(data) != expected_sha:
        raise ValueError('Battle icon API repair requires the exact published source SHA')
    p = pefile.PE(data=data)
    if (p.FILE_HEADER.Machine != 0x14c or p.OPTIONAL_HEADER.ImageBase != IMAGE_BASE or
            p.OPTIONAL_HEADER.SizeOfImage != BASE_RVA + SIZE or
            p.get_data(SIGNATURE_RVA, len(SIGNATURE)) != SIGNATURE):
        raise ValueError('Published battle icon density region differs')
    last = p.sections[-1]
    if (last.VirtualAddress + last.Misc_VirtualSize != BASE_RVA + SIZE or
            last.PointerToRawData + last.SizeOfRawData != len(data)):
        raise ValueError('Published battle icon region is not exactly mapped')
    out = bytearray(data)
    at = p.get_offset_from_rva(BASE_RVA)
    out[at:at + 0x600] = draw_code()
    out[at + 0x600:at + 0xc00] = draw_code(True)
    return bytes(out)
