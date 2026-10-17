"""Guarded Silver-only Roboto Condensed density adapter for published .12.

Native font records, pen advances, pair kerning, layout and input stay native.
Only approved screen-GUI glyph draws select separately rasterized atlas crops
and natural ink bounds. Copied font GPU vertices snap to physical pixels.
TI on disk remains byte-identical; startup installs four guarded in-memory calls.
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
BASE_SHA = '87645b946317a645552c3c2a5fcf586784d3920548288e2312dfb9ace065df4d'
TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
RVA = 0x82e000
SIZE = 0x18000
STARTUP = BASE + RVA
INIT = STARTUP + 0x100
INSTALL = STARTUP + 0x600
DRAW = STARTUP + 0xf00
UPLOAD = STARTUP + 0x1600
STATE = RVA + 0x1c00
STRINGS = RVA + 0x2000
TABLE = RVA + 0x4000
GLYPHS = RVA + 0x4800
HEADER_SIZE = 0x80
GLYPH_SIZE = 0x2c
FONT_COUNT = 9
CORE_STATE = 0x828f00
CORE_UPLOAD = 0xc25a00
FONT_QUAD = 0x7406a8
TI_UPLOAD_CALL = 0x6508be
FONT_CALLS = ((0x6fceba, bytes.fromhex('e8e9370400')),
              (0x6fcbc0, bytes.fromhex('e8e33a0400')),
              (0x6fcd40, bytes.fromhex('e863390400')))
HOOK = 0xc178d8
HOOK_BEFORE = bytes.fromhex('619d6a006a00')
ASSET_MANIFEST = Path(__file__).resolve().parents[1] / 'reports/ui-hd-assets/selected-fonts/manifest.json'
ASSET_MANIFEST_SHA = '85ed0c1421ed284a77a17e1f9e7f19761955a0cebb44b750827d5fef2d8a2393'
SIGNATURE = b'TIO-RobotoCondensed-density-v1'
SIGNATURE_RVA = RVA + 0x1b00
FONT_GLOBALS = (0x76e0c0, 0x76df40, 0x76e1e4, 0x76e688, 0x76dffc,
                0x76e4e4, 0x76e1e0, 0x76df3c, 0)
FONTS = ('font1', 'pixel', 'pixelb', 'nice', 'mini', 'big', 'pixel13', 'pixel14', 'menu')
PERCENTS = (100, 125, 150, 200)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def state_get(c, reg, offset):
    c.emit({'eax':'8b83','edx':'8b93','ecx':'8b8b'}[reg]); c.word(STATE+offset)


def state_put(c, offset):
    c.emit('8983'); c.word(STATE+offset)


def state_set(c, offset, value):
    c.emit('c783'); c.word(STATE+offset); c.word(value)


def increment(c, offset):
    c.emit('ff83'); c.word(STATE+offset)


def native(c, va):
    c.emit('b8'); c.word(va); c.emit('ffd0')


def iat(c, rva):
    c.emit('ff93'); c.word(rva)


def core_guard(c, fail):
    c.emit('83bb'); c.word(CORE_STATE+0x14); c.emit('00')
    c.branch('0f84', fail)
    c.emit('8b83'); c.word(CORE_STATE+4); c.emit('85c0'); c.branch('0f8e', fail)
    c.emit('8b0d0cde7600 85c9'); c.branch('0f84', fail)
    c.emit('8b09 85c9'); c.branch('0f84', fail)
    c.emit('3b8199020000'); c.branch('0f87', fail)
    c.emit('8b83'); c.word(CORE_STATE+8); c.emit('85c0'); c.branch('0f8e', fail)
    c.emit('3b819d020000'); c.branch('0f87', fail)


def startup_code():
    c=Code(STARTUP); c.call(INIT)
    c.emit(HOOK_BEFORE.hex()); c.jump(HOOK+len(HOOK_BEFORE))
    return c.finish(0x100)


def init_code():
    c=Code(INIT); c.emit('9c60'); c.base(); increment(c,0x64)
    state_get(c,'eax',0); c.emit('85c0'); c.branch('0f85','done')
    c.emit('8b0d80e17600 85c9'); c.branch('0f84','unavailable')
    c.emit('833900'); c.branch('0f84','unavailable')
    c.emit('8d b3'); c.word(TABLE)
    c.emit('bd'); c.word(FONT_COUNT)  # EBP is saved by pushad; no native static link is used here.
    c.label('font')
    c.emit('8b06 85c0'); c.branch('0f84','menu')
    c.emit('8b00 85c0'); c.branch('0f84','next_font')
    c.emit('8b10'); c.branch('e9','resolve')
    c.label('menu'); c.emit('8b93'); c.word(0x817bf0)
    c.label('resolve'); c.emit('85d2'); c.branch('0f88','next_font')
    c.emit('a180e17600 8b00 bf'); c.word(0x6fe910); c.emit('ffd7')
    c.emit('894604 85c0'); c.branch('0f84','next_font')
    c.emit('8b800c011c00 894648 31ff')
    c.label('density')
    c.emit('8b44be38 01d8 83c00c 50'); iat(c,0x77a190)
    c.emit('83f8ff'); c.branch('0f84','load_failed')
    c.emit('a810'); c.branch('0f85','load_failed')
    c.emit('6a00 6a00 a160e37600 8b00 50')
    c.emit('8b44be38 01d8 83c00c 31d2 31c9')
    # TI7404fc preserves EBX/ESI/EDI/EBP, cleans three stack arguments.
    # The tail trampoline preserves all register and stack arguments.
    c.call(STARTUP+0x1a00)
    c.emit('85c0'); c.branch('0f84','load_failed')
    # +0x60 classifies render targets; PNGs are managed textures (zero).
    # Readiness is the live D3D texture pointer, not this classification byte.
    c.emit('80786000'); c.branch('0f85','load_failed')
    c.emit('83780c00'); c.branch('0f84','load_failed')
    c.emit('8b54be28 0fb7ca 394814'); c.branch('0f85','load_failed')
    c.emit('c1ea10 395018'); c.branch('0f85','load_failed')
    c.emit('8944be18'); increment(c,8); c.branch('e9','next_density')
    c.label('load_failed'); increment(c,0x60)
    c.label('next_density'); c.emit('47 83ff04'); c.branch('0f82','density')
    c.label('next_font'); c.emit('81c680000000 4d'); c.branch('0f85','font')
    state_get(c,'eax',8); c.emit('85c0'); c.branch('0f84','unavailable')
    state_set(c,0,1); c.call(INSTALL); c.branch('e9','done')
    c.label('unavailable'); state_set(c,0,-1); state_set(c,4,5)
    c.label('done'); c.emit('619d c3')
    return c.finish(0x500)


def call_replacement(c, address, target):
    c.emit('8d83'); c.word(target-BASE)
    c.emit('2d'); c.word(address+5)
    c.emit('a3'); c.word(address+1)


def flush(c, page):
    iat(c,0x77a1b0); c.emit('6800100000 68'); c.word(page); c.emit('50')
    c.emit('ff93'); c.word(STATE+0x1c)


def protect_restore(c, page, old_offset):
    c.emit('8d83'); c.word(STATE+0x18); c.emit('50')
    state_get(c,'eax',old_offset); c.emit('50 6800100000 68'); c.word(page)
    iat(c,0x77a090)


def install_code(kernel_rva,flush_rva):
    c=Code(INSTALL); c.emit('9c60'); c.base()
    state_get(c,'eax',0xc); c.emit('85c0'); c.branch('0f85','done')
    c.emit('83bb'); c.word(CORE_STATE+0x28); c.emit('01'); c.branch('0f85','unavailable')
    for va,original in FONT_CALLS:
        c.emit('813d'); c.word(va); c.emit(original[:4].hex()); c.branch('0f85','unavailable')
        c.emit('803d'); c.word(va+4); c.emit(original[4:].hex()); c.branch('0f85','unavailable')
    c.emit('803d'); c.word(TI_UPLOAD_CALL); c.emit('e8'); c.branch('0f85','unavailable')
    c.emit('8d83'); c.word(CORE_UPLOAD-BASE); c.emit('2d'); c.word(TI_UPLOAD_CALL+5)
    c.emit('3b05'); c.word(TI_UPLOAD_CALL+1); c.branch('0f85','unavailable')
    for va in (FONT_QUAD,0x7404fc,0x6fe910,0x65085c):
        c.emit('813d'); c.word(va); c.emit('558bec83'); c.branch('0f85','unavailable')
    c.emit('8d83'); c.word(kernel_rva); c.emit('50'); iat(c,0x77a178)
    c.emit('85c0'); c.branch('0f84','unavailable')
    c.emit('8d93'); c.word(flush_rva); c.emit('52 50'); iat(c,0x77a170)
    c.emit('85c0'); c.branch('0f84','unavailable'); state_put(c,0x1c)
    c.emit('8d83'); c.word(STATE+0x10); c.emit('50 6a40 6800100000 6800c06f00')
    iat(c,0x77a090); c.emit('85c0'); c.branch('0f84','protect_failed')
    c.emit('8d83'); c.word(STATE+0x14); c.emit('50 6a40 6800100000 6800006500')
    iat(c,0x77a090); c.emit('85c0'); c.branch('0f84','protect_gpu_failed')
    for va,_ in FONT_CALLS: call_replacement(c,va,DRAW)
    call_replacement(c,TI_UPLOAD_CALL,UPLOAD)
    flush(c,0x6fc000); c.emit('85c0'); c.branch('0f84','rollback')
    flush(c,0x650000); c.emit('85c0'); c.branch('0f84','rollback')
    state_set(c,0xc,1); c.branch('e9','restore')
    c.label('rollback')
    for va,raw in FONT_CALLS:
        c.emit('c705'); c.word(va+1); c.emit(raw[1:].hex())
    call_replacement(c,TI_UPLOAD_CALL,CORE_UPLOAD)
    flush(c,0x6fc000); flush(c,0x650000)
    state_set(c,0xc,-1); state_set(c,4,3)
    c.label('restore')
    protect_restore(c,0x650000,0x14); c.emit('85c0'); c.branch('0f85','restore_font')
    state_set(c,4,4)
    c.label('restore_font')
    protect_restore(c,0x6fc000,0x10); c.emit('85c0'); c.branch('0f85','done')
    state_set(c,4,4); c.branch('e9','done')
    c.label('protect_gpu_failed'); protect_restore(c,0x6fc000,0x10)
    c.label('protect_failed'); state_set(c,0xc,-1); state_set(c,4,2); c.branch('e9','done')
    c.label('unavailable'); state_set(c,0xc,-1); state_set(c,4,1)
    c.label('done'); c.emit('619d c3')
    return c.finish(0x900)


def draw_code():
    c=Code(DRAW); c.emit('9c60'); c.base()
    state_set(c,0x6c,1)
    c.emit('83bb'); c.word(STATE); c.emit('01'); c.branch('0f85','stock')
    core_guard(c,'stock')
    state_set(c,0x6c,2)
    c.emit('8b45fc 8db3'); c.word(TABLE); c.emit('bf'); c.word(FONT_COUNT)
    c.label('font'); c.emit('394604'); c.branch('0f84','found_font')
    c.emit('81c680000000 4f'); c.branch('0f85','font'); c.branch('e9','stock')
    c.label('found_font'); c.emit('b8'); c.word(FONT_COUNT); c.emit('29f8'); state_put(c,0x30)
    c.emit('8b44241c'); state_put(c,0x38)
    c.emit('8b45e8'); state_put(c,0x34)
    state_set(c,0x6c,3)
    c.emit('8b7e0c 01df 8b4e08 85c9'); c.branch('0f84','stock')
    c.emit('81f900010000'); c.branch('0f87','stock')
    c.label('glyph'); c.emit('3907'); c.branch('0f84','found_glyph')
    c.emit('83c72c 49'); c.branch('0f85','glyph'); c.branch('e9','stock')
    c.label('found_glyph')
    # Reject an unsupported native rotation before changing any original
    # arguments; all stock fallback paths must retain the complete quad ABI.
    c.emit('0fbe4c2428 898b'); c.word(STATE+0x68)
    c.emit('85c9'); c.branch('0f84','valid_rotation')
    c.emit('83f95a'); c.branch('0f84','valid_rotation')
    c.emit('83f9a6'); c.branch('0f85','stock')
    c.label('valid_rotation')
    c.emit('8b83'); c.word(CORE_STATE); state_put(c,0x2c)
    c.emit('31c9')
    for index,percent in enumerate(PERCENTS):
        c.emit('3d'); c.word(percent); c.branch('0f84',f'density{index}')
    c.branch('e9','stock')
    for index in range(4):
        c.label(f'density{index}'); c.emit('b9'); c.word(index); c.branch('e9','texture')
    c.label('texture'); state_set(c,0x6c,4)
    c.emit('8b448e18 85c0'); c.branch('0f84','stock')
    c.emit('80786000'); c.branch('0f85','stock')
    c.emit('83780c00'); c.branch('0f84','stock')
    c.emit('8b548e28 0fb7ea 396814'); c.branch('0f85','stock')
    # EBP was saved by pushad but is the native caller's frame. After this
    # point no caller-frame access is needed; it is restored before the tail.
    c.emit('c1ea10 395018'); c.branch('0f85','stock')
    c.emit('8944241c'); state_put(c,0x3c)
    c.emit('8d4ccf0c')
    for source_offset,saved_offset,field in ((0,0x14,0x40),(2,0x18,0x44),(4,0x44,0x48),(6,0x40,0x4c)):
        c.emit('0fb741'); c.emit(f'{source_offset:02x}')
        c.emit('894424'); c.emit(f'{saved_offset:02x}'); state_put(c,field)
    c.emit('0fb74708 89442434 0fb7470a 89442430')
    c.emit('0fbf5704 0fbf4706 0fbe4c2428')
    c.emit('898b'); c.word(STATE+0x68)
    c.emit('85c9'); c.branch('0f84','normal')
    c.emit('83f95a'); c.branch('0f84','right')
    c.emit('83f9a6'); c.branch('0f84','left')
    c.branch('e9','stock')
    c.label('normal'); c.emit('0154243c 01442438'); c.branch('e9','adapted')
    c.label('right'); c.emit('2944243c 01542438'); c.branch('e9','adapted')
    c.label('left'); c.emit('0144243c 29542438')
    c.label('adapted'); increment(c,0x20); state_set(c,0x6c,0)
    for saved,field in ((0x3c,0x50),(0x38,0x54),(0x34,0x58),(0x30,0x5c)):
        c.emit('8b4424'); c.emit(f'{saved:02x}'); state_put(c,field)
    c.branch('e9','tail')
    c.label('stock'); increment(c,0x24)
    c.label('tail'); c.emit('619d 68'); c.word(FONT_QUAD); c.emit('c3')
    return c.finish(0x700)


def upload_code():
    c=Code(UPLOAD); c.call(CORE_UPLOAD); c.emit('9c60'); c.base(); core_guard(c,'done')
    c.emit('a170df7600 85c0'); c.branch('0f84','done')
    c.emit('8b00 85c0'); c.branch('0f84','done')
    c.emit('8b5010 85d2'); c.branch('0f84','done')
    c.emit('8db3'); c.word(TABLE); c.emit('b9'); c.word(FONT_COUNT)
    c.label('font')
    for offset in (0x18,0x1c,0x20,0x24):
        c.emit('3956'); c.emit(f'{offset:02x}'); c.branch('0f84','matched')
    c.emit('81c680000000 49'); c.branch('0f85','font'); c.branch('e9','done')
    c.label('matched'); c.emit('8b75fc 85f6'); c.branch('0f84','done')
    c.emit('8b4618 83e00e 83f804'); c.branch('0f85','done')
    c.emit('8b7e1c 83ff10'); c.branch('0f82','done')
    c.emit('81ff00010000'); c.branch('0f87','done')
    c.emit('8b442418 31d2 f7f7 85d2'); c.branch('0f85','done')
    c.emit('85c0'); c.branch('0f84','done')
    c.emit('3d00000100'); c.branch('0f87','done')
    c.emit('0183'); c.word(STATE+0x28)
    c.emit('89c1 8b742414 83ec08 d93c24 668b0424 6625fff3 6689442402 d96c2402')
    c.label('vertex')
    for offset in (0,4):
        c.emit('d946'); c.emit(f'{offset:02x}')
        c.emit('db5c2404 db442404 d95e'); c.emit(f'{offset:02x}')
    c.emit('01fe 49'); c.branch('0f85','vertex')
    c.emit('d92c24 83c408')
    c.label('done'); c.emit('619d c3')
    return c.finish(0x300)


def assets_manifest(path=ASSET_MANIFEST):
    path=Path(path)
    raw=path.read_bytes()
    if sha(raw)!=ASSET_MANIFEST_SHA:
        raise ValueError('Selected font package changed')
    manifest=json.loads(raw)
    if manifest['result']!='PASS' or manifest['family']!='Roboto Condensed' or manifest['scales']!=list(PERCENTS):
        raise ValueError('Unsupported font assets')
    if tuple(f['font'] for f in manifest['fonts'])!=FONTS:
        raise ValueError('Native font role order differs')
    for asset in manifest['assets']:
        source=path.parent/asset['path']
        if not asset['path'].startswith('base/ui-hd/') or not source.is_file() or sha(source.read_bytes())!=asset['sha256']:
            raise ValueError('Selected font resource integrity differs')
    return manifest


def extension(manifest):
    result=bytearray(SIZE)
    string_offset=STRINGS
    paths=[]
    for font in manifest['fonts']:
        row=[]
        for atlas in font['density_sets']:
            text=atlas['path'].replace('/','\\')
            # Texture filenames are UnicodeString (character count). The
            # separate legacy font-text WideString byte-count ABI does not
            # apply to TI7404fc / ExtractFileName's Unicode helpers.
            raw=struct.pack('<HHiI',1200,2,-1,len(text))+text.encode('utf-16le')+b'\0\0'
            row.append(string_offset)
            result[string_offset-RVA:string_offset-RVA+len(raw)]=raw
            string_offset=(string_offset+len(raw)+3)&~3
        paths.append(row)
    kernel_rva=string_offset; kernel='kernel32.dll'.encode('utf-16le')+b'\0\0'
    result[kernel_rva-RVA:kernel_rva-RVA+len(kernel)]=kernel
    flush_rva=(kernel_rva+len(kernel)+3)&~3
    result[flush_rva-RVA:flush_rva-RVA+22]=b'FlushInstructionCache\0'
    if flush_rva+22>TABLE:raise ValueError('Font paths exceed their region')
    glyph_rva=GLYPHS
    for index,font in enumerate(manifest['fonts']):
        header=TABLE+index*HEADER_SIZE
        struct.pack_into('<IIII',result,header-RVA,FONT_GLOBALS[index],0,len(font['glyphs']),glyph_rva)
        for density,atlas in enumerate(font['density_sets']):
            struct.pack_into('<I',result,header-RVA+0x28+density*4,atlas['width']|(atlas['height']<<16))
            struct.pack_into('<I',result,header-RVA+0x38+density*4,paths[index][density])
        for glyph in font['glyphs']:
            dx,dy,w,h=glyph['visual_logical_box']
            raw=struct.pack('<IhhHH',glyph['codepoint'],dx,dy,w,h)
            for rect in glyph['source_rects']:raw+=struct.pack('<4H',*rect)
            if len(raw)!=GLYPH_SIZE:raise ValueError('Native glyph record differs')
            result[glyph_rva-RVA:glyph_rva-RVA+len(raw)]=raw;glyph_rva+=GLYPH_SIZE
    if glyph_rva>RVA+SIZE:raise ValueError('Font table exceeds reserved region')
    for entry,code in ((STARTUP,startup_code()),(INIT,init_code()),
                       (INSTALL,install_code(kernel_rva,flush_rva)),(DRAW,draw_code()),
                       (UPLOAD,upload_code())):
        result[entry-BASE-RVA:entry-BASE-RVA+len(code)]=code
    # Absolute TI tail keeps all three register arguments and the three stack
    # parameters untouched; native7404fc returns directly to the INIT callsite.
    trampoline=bytes.fromhex('68')+struct.pack('<I',0x7404fc)+b'\xc3'
    result[0x1a00:0x1a00+len(trampoline)]=trampoline
    result[SIGNATURE_RVA-RVA:SIGNATURE_RVA-RVA+len(SIGNATURE)]=SIGNATURE
    return bytes(result)


def patch(data, *, expected_sha=BASE_SHA, assets_path=ASSET_MANIFEST):
    if expected_sha!=BASE_SHA or sha(data)!=BASE_SHA:
        raise ValueError('HD fonts require the exact published .12 Silver')
    pe=pefile.PE(data=data);last=pe.sections[-1]
    if pe.OPTIONAL_HEADER.ImageBase!=BASE or pe.OPTIONAL_HEADER.SizeOfImage!=RVA or pe.FILE_HEADER.Machine!=0x14c:
        raise ValueError('Unknown pre-font Silver layout')
    if (last.VirtualAddress+last.Misc_VirtualSize!=RVA or last.PointerToRawData+last.SizeOfRawData!=len(data)
            or last.SizeOfRawData!=last.Misc_VirtualSize or len(data)%0x200):
        raise ValueError('Silver is not safely appendable')
    offset=pe.get_offset_from_rva(HOOK-BASE)
    if data[offset:offset+len(HOOK_BEFORE)]!=HOOK_BEFORE:
        raise ValueError('Native font startup hook changed')
    if any(HOOK-BASE<=e.rva<HOOK-BASE+len(HOOK_BEFORE) and e.type==3
           for block in pe.DIRECTORY_ENTRY_BASERELOC for e in block.entries):
        raise ValueError('Unexpected font startup relocation')
    manifest=assets_manifest(assets_path)
    result=bytearray(data)
    result[offset:offset+len(HOOK_BEFORE)]=b'\xe9'+struct.pack('<i',STARTUP-HOOK-5)+b'\x90'
    for field in ('Misc_VirtualSize','SizeOfRawData'):
        struct.pack_into('<I',result,last.get_field_absolute_offset(field),getattr(last,field)+SIZE)
    struct.pack_into('<I',result,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),RVA+SIZE)
    struct.pack_into('<I',result,pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'),0)
    result.extend(extension(manifest))
    return bytes(result)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();data=args.source.read_bytes();candidate=patch(data)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_bytes(candidate)
    print(json.dumps({'source_sha256':sha(data),'candidate_sha256':sha(candidate),
                      'size_of_image':hex(RVA+SIZE),'font_state_rva':hex(STATE),
                      'assets_manifest_sha256':ASSET_MANIFEST_SHA,'graphical_validation':False}))


if __name__=='__main__':main()
