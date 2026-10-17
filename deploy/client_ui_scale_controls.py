"""SHA-guarded Screen scale controls and native client preference persistence.

Composes after client_ui_scale's core. Does not touch an installed client,
player configuration, process, database, or publication. Uses native radio
controls and the existing cvar/archive writer; scale-only Apply needs no Reset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import pefile

from .client_equipment_batch import Code
from .client_screen_resolution_ui import section_payload as resolution_payload

BASE = 0x400000
RVA = 0x829000
SIZE = 0x2000
CREATE = BASE + RVA
LOAD = CREATE + 0x400
APPLY = CREATE + 0x800
EARLY = CREATE + 0xb00
TRAMPOLINE = CREATE + 0xd00
SAVE = CREATE + 0xe00
DATA = RVA + 0x1000
STATE = RVA + 0x1f00
SIGNATURE_RVA = RVA + 0x1fc0
SIGNATURE = b'TIO-ui-scale-controls-v1'
CORE_STATE = 0x828f00
CORE_SET = 0xc25000
PERCENTS = (100, 125, 150, 200)
APPLY_PROLOGUE = bytes.fromhex('55 8bec b908000000')
EARLY_TAIL = bytes.fromhex('5d c20400 90')


def address(c, reg, rva):
    c.emit({'eax': '8d83', 'edx': '8d93', 'ecx': '8d8b'}[reg]); c.word(rva)


def static_strings(payload):
    strings = {}
    at = DATA - RVA
    for value in ('ui_scale', '0', '100', '125', '150', '200'):
        # Delphi UnicodeString, used by the original cvar read wrappers.
        raw = struct.pack('<HHiI', 1200, 2, -1, len(value)) + value.encode('utf-16le') + b'\0\0'
        strings[value] = RVA + at + 12
        payload[at:at+len(raw)] = raw
        at = (at + len(raw) + 3) & ~3
    for value in ('100%', '125%', '150%', '200%', 'Интерфейс:', 'Доступный масштаб зависит от разрешения'):
        encoded = value.encode('utf-16le')
        raw = struct.pack('<I', len(encoded)) + encoded + b'\0\0'
        strings[value] = RVA + at + 4
        payload[at:at+len(raw)] = raw
        at = (at + len(raw) + 3) & ~3
    if RVA + at > STATE:
        raise ValueError('UI preference constants overflow')
    return strings


def save_code(strings):
    """EAX=requested percent; native stdcall CVar_Set(name,value,archive=1)."""
    c = Code(SAVE); c.emit('9c60'); c.base()
    for percent in PERCENTS:
        c.emit('3d'); c.word(percent); c.branch('0f84', 'value_'+str(percent))
    c.jump(SAVE + 0x1f0)  # Invalid callers cannot persist arbitrary values.
    for percent in PERCENTS:
        c.label('value_'+str(percent)); address(c, 'edx', strings[str(percent)])
        c.branch('e9', 'write')
    c.label('write')
    c.emit('6a01 52'); address(c, 'eax', strings['ui_scale']); c.emit('50')
    c.call(0x688420)
    c.emit('619d c3')
    raw = c.finish(0x1f0) + bytes.fromhex('619d c3')
    return raw.ljust(0x200, b'\0')


def load_code(strings):
    """Read after physical size exists; normalise missing/auto/invalid values."""
    c = Code(LOAD); c.emit('9c60 89e5'); c.base()
    address(c, 'eax', strings['ui_scale']); c.call(0x688328)
    for percent in PERCENTS:
        c.emit('3d'); c.word(percent); c.branch('0f84', 'done')
    c.emit('b864000000')
    c.emit('81bb'); c.word(CORE_STATE+4); c.word(2400)
    c.branch('0f8c', 'save_default')
    c.emit('81bb'); c.word(CORE_STATE+8); c.word(1250)
    c.branch('0f8c', 'save_default')
    c.emit('b896000000')
    c.emit('81bb'); c.word(CORE_STATE+4); c.word(3600)
    c.branch('0f8c', 'save_default')
    c.emit('81bb'); c.word(CORE_STATE+8); c.word(2000)
    c.branch('0f8c', 'save_default')
    c.emit('b8c8000000')
    c.label('save_default'); c.call(SAVE)
    c.label('done'); c.emit('89451c 619d c3')
    return c.finish(0x300)


def early_code(strings):
    # Runs after RegisterCVar_Set stores its callback, before config execution.
    # Its exact original tail has no relocation and uses RET4.
    c = Code(EARLY); c.emit('9c60'); c.base()
    c.emit('833d8867780000'); c.branch('0f84', 'done')
    c.emit('8b83'); c.word(0xac5b40-BASE)
    c.emit('85c0'); c.branch('0f84', 'done')
    c.emit('833800'); c.branch('0f84', 'done')
    address(c, 'eax', strings['ui_scale']); c.call(0x6882f0)
    c.emit('84c0'); c.branch('0f85', 'done')
    c.emit('6a01'); address(c, 'eax', strings['0']); c.emit('50')
    address(c, 'eax', strings['ui_scale']); c.emit('50'); c.call(0x688420)
    c.label('done'); c.emit('619d 5d c20400')
    return c.finish(0x200)


def create_code(strings):
    # This call replaces the existing presets' final call to the caption helper.
    c = Code(CREATE); c.call(0x884688)
    c.emit('9c60 89e5 83ec08'); c.base()
    c.call(LOAD); c.emit('8945fc')
    # Display the effective value after a smaller window temporarily caps it.
    c.emit('8b83'); c.word(CORE_STATE)
    c.emit('83f864'); c.branch('0f8c', 'selection_ready')
    c.emit('8945fc'); c.label('selection_ready')

    def label(text, x, y):
        c.emit('89f1 b201 8b83'); c.word(0xa30e38-BASE); c.call(0xa47d78)
        c.emit('89c7 c74730'); c.word(x)
        c.emit('c74734'); c.word(y)
        # TLabel+284 is RightAlign; +28c is the native font index.
        c.emit('c6878402000000 c7878c02000001000000')
        address(c, 'edx', strings[text]); c.emit('89f8'); c.call(0xa42b04)

    label('Интерфейс:', 32, 320)
    label('Доступный масштаб зависит от разрешения', 32, 360)
    for index, percent in enumerate(PERCENTS):
        c.emit('56 31c9 b201 8b83'); c.word(0xa309f4-BASE); c.call(0xa44c9c)
        c.emit('89c7 c78778020000'); c.word(percent)
        c.emit('c7878402000004000000 c74730'); c.word(128+96*(index%2))
        c.emit('c74734'); c.word(320+16*(index//2))
        c.emit('c747385c000000')
        address(c, 'edx', strings[str(percent)+'%']); c.emit('89f8'); c.call(0xa42b04)
        c.emit('817dfc'); c.word(percent); c.emit('0f94c2 89f8'); c.call(0xa44eac)
    c.emit('89ec 619d c3')
    return c.finish(0x400)


def apply_code():
    c = Code(APPLY); c.emit('9c60'); c.base()
    c.emit('c783'); c.word(STATE); c.word(0)
    c.emit('8d93'); c.word(0x883970-BASE)
    c.emit('8b83'); c.word(0xb76650-BASE); c.call(0xa3fca8)
    c.emit('83f8ff'); c.branch('0f84', 'native')
    c.emit('89c2 8b83'); c.word(0xb76650-BASE); c.call(0xa3f2a0)
    c.emit('89c6 31ff')
    c.label('next'); c.emit('89f0'); c.call(0xa424d4)
    c.emit('39c7'); c.branch('0f8d', 'native')
    c.emit('89f0 89fa'); c.call(0xa424c4)
    c.emit('50 8b93'); c.word(0xa309f4-BASE); c.call(0x4095ac)
    c.emit('84c0 58'); c.branch('0f84', 'advance')
    c.emit('83b88402000004'); c.branch('0f85', 'advance')
    c.emit('80b88002000000'); c.branch('0f84', 'advance')
    c.emit('8b8078020000 8983'); c.word(STATE)
    c.branch('e9', 'native')
    c.label('advance'); c.emit('47'); c.branch('e9', 'next')
    c.label('native'); c.emit('619d'); c.call(TRAMPOLINE)
    c.emit('9c60'); c.base()
    c.emit('8b83'); c.word(STATE)
    c.emit('85c0'); c.branch('0f84', 'done')
    # A total D3D rollback failure must keep the original failure dialog/path.
    c.emit('83bb'); c.word(0x823c30); c.emit('04')
    c.branch('0f84', 'done')
    c.call(SAVE); c.call(CORE_SET)
    # Screen is a cached native window. Reflect a capped effective scale in
    # its existing radios while the archived request remains available for a
    # later, larger display. Constructor-only selection cannot do this.
    c.emit('89c5 8d93'); c.word(0x883970-BASE)
    c.emit('8b83'); c.word(0xb76650-BASE); c.call(0xa3fca8)
    c.emit('83f8ff'); c.branch('0f84', 'done')
    c.emit('89c2 8b83'); c.word(0xb76650-BASE); c.call(0xa3f2a0)
    c.emit('89c6 31ff')
    c.label('sync_next'); c.emit('89f0'); c.call(0xa424d4)
    c.emit('39c7'); c.branch('0f8d', 'done')
    c.emit('89f0 89fa'); c.call(0xa424c4)
    c.emit('50 8b93'); c.word(0xa309f4-BASE); c.call(0x4095ac)
    c.emit('84c0 58'); c.branch('0f84', 'sync_advance')
    c.emit('83b88402000004'); c.branch('0f85', 'sync_advance')
    c.emit('39a878020000 0f94c2'); c.call(0xa44eac)
    c.label('sync_advance'); c.emit('47'); c.branch('e9', 'sync_next')
    c.label('done'); c.emit('619d c3')
    return c.finish(0x300)


def extension():
    payload = bytearray(SIZE)
    strings = static_strings(payload)
    for address_, raw in ((CREATE, create_code(strings)), (LOAD, load_code(strings)),
                          (APPLY, apply_code()), (EARLY, early_code(strings)),
                          (SAVE, save_code(strings))):
        at = address_-BASE-RVA; payload[at:at+len(raw)] = raw
    c = Code(TRAMPOLINE); c.emit(APPLY_PROLOGUE.hex()); c.jump(0x8834f8)
    payload[TRAMPOLINE-BASE-RVA:TRAMPOLINE-BASE-RVA+0x100] = c.finish(0x100)
    at = SIGNATURE_RVA-RVA; payload[at:at+len(SIGNATURE)] = SIGNATURE
    return bytes(payload)


def constructor_site():
    original, _ = resolution_payload()
    needle = b'\x89\xec\x61\x9d'
    at = original.find(needle)
    if at < 5 or original.find(needle, at+1) != -1:
        raise ValueError('Unknown resolution constructor epilogue')
    site = 0xc22000+at-5
    expected = b'\xe8'+struct.pack('<i', 0x884688-site-5)
    if original[at-5:at] != expected:
        raise ValueError('Unknown constructor caption call')
    return site, expected


def patch(data, *, expected_sha):
    if hashlib.sha256(data).hexdigest() != expected_sha:
        raise ValueError('Exact reviewed UI core candidate is required')
    pe = pefile.PE(data=data)
    last = pe.sections[-1]
    if (pe.FILE_HEADER.Machine != 0x14c or pe.OPTIONAL_HEADER.ImageBase != BASE
            or pe.OPTIONAL_HEADER.SizeOfImage != RVA or last.Name.rstrip(b'\0') != b'.tioscr'
            or last.VirtualAddress != 0x823000 or last.PointerToRawData+last.SizeOfRawData != len(data)
            or last.Misc_VirtualSize != last.SizeOfRawData):
        raise ValueError('Unexpected sequential UI core layout')
    result = bytearray(data)
    site, expected = constructor_site()
    hooks = ((site, expected, CREATE), (0x8834f0, APPLY_PROLOGUE, APPLY),
             (0x4f255f, EARLY_TAIL, EARLY))
    for address_, before, destination in hooks:
        offset = pe.get_offset_from_rva(address_-BASE)
        if data[offset:offset+len(before)] != before:
            raise ValueError(f'Unexpected UI preference hook {address_:#x}')
        if any(e.type == 3 and address_-BASE <= e.rva < address_-BASE+len(before)
               for block in pe.DIRECTORY_ENTRY_BASERELOC for e in block.entries):
            raise ValueError('UI preference hook overlaps a relocation')
        result[offset:offset+len(before)] = b'\xe9'+struct.pack('<i', destination-address_-5)+b'\x90'*(len(before)-5) if address_ != site else b'\xe8'+struct.pack('<i', destination-address_-5)
    bounds = pe.get_offset_from_rva(0x8867bd-BASE)
    if data[bounds:bounds+5] != bytes.fromhex('6880010000'):
        raise ValueError('Unexpected Screen panel height')
    result[bounds:bounds+5] = bytes.fromhex('68c0010000')  # Height448; native buttons Height-48.
    bootstrap = pe.get_offset_from_rva(CORE_STATE+0x24)
    if data[bootstrap:bootstrap+4] != b'\0'*4:
        raise ValueError('UI core bootstrap already bound')
    struct.pack_into('<I', result, bootstrap, LOAD-BASE)
    struct.pack_into('<I', result, last.get_field_absolute_offset('Misc_VirtualSize'), last.Misc_VirtualSize+SIZE)
    struct.pack_into('<I', result, last.get_field_absolute_offset('SizeOfRawData'), last.SizeOfRawData+SIZE)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), RVA+SIZE)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 0)
    result.extend(extension())
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path); parser.add_argument('output', type=Path)
    parser.add_argument('--expected-sha', required=True); parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    source = args.source.read_bytes(); candidate = patch(source, expected_sha=args.expected_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_bytes(candidate)
    report = dict(source_sha256=hashlib.sha256(source).hexdigest(), candidate_sha256=hashlib.sha256(candidate).hexdigest(),
                  source_bytes=len(source), candidate_bytes=len(candidate), scales=list(PERCENTS),
                  native_archive_preference='ui_scale', panel_height=448, bootstrap_rva=hex(LOAD-BASE),
                  native_radio_group=4, scale_only_reset=False, graphical_validation=False, published=False)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
