"""Known-build local-only native city controls for cooperative Contracts.

The extension uses the game's own child constructor, caption and click-event
registration, and its existing chat sender.  It does not own account state or
transport.  All newly written native addresses are position independent.
"""
from __future__ import annotations

import hashlib
import struct

import pefile

from .client_menu_interface import Assembler

BASE_SHA = '2d9e0f83b3ff94ef2c7ac5df2d396cd7b7a55a7ac03168c0ef252e977b75b359'
IMAGE_BASE = 0x400000
SECTION_RVA = 0x818000
SECTION_SIZE = 0x1000
SECTION_NAME = b'.tiocity'
SIGNATURE = b'TIO-contracts-city-field-hq-v1'
ENTRIES = {name: IMAGE_BASE + SECTION_RVA + offset for name, offset in {
    'construct': 0x000, 'layout': 0x280, 'contracts': 0x580,
    'party': 0x600, 'refresh': 0x680}.items()}
DATA = {name: SECTION_RVA + offset for name, offset in {
    'button_name': 0x80c, 'frame_name': 0x86c, 'contracts_caption': 0x8cc,
    'party_caption': 0x90c, 'contracts_command': 0x94c,
    'party_command': 0x9ac, 'button_resource': 0xae0,
    'frame_resource': 0xaf0, 'city': 0xb00,
    'contracts_button': 0xb04, 'party_button': 0xb08}.items()}
CITY_IDS = (2, 3, 5, 8)
NEW_BUTTON_IDS = (0x701, 0x702)


def _city_guard(a: Assembler, target: str):
    # Import variable -> integer storage. The server remains authoritative.
    a.emit('8b83'); a.word(0xac5d58-IMAGE_BASE)
    a.emit('85c0'); a.branch('0f84', target)
    a.emit('8b00')
    for city in CITY_IDS:
        a.emit('83f8'); a.emit(f'{city:02x}')
        a.branch('0f84', 'city_allowed')
    a.branch('e9', target)
    a.label('city_allowed')


def thunks() -> dict[int, bytes]:
    result = {}
    a = Assembler(ENTRIES['construct'])
    # The replaced call is a five-argument native constructor. Forward its
    # original stack directly, then retain its return value and all registers.
    a.emit('ff742414 ff742414 ff742414 ff742414 ff742414')
    a.relative('e8', 0x8d3604)
    a.emit('9c60 89de'); a.base()
    a.emit('89b3'); a.word(DATA['city'])
    for name, size in (('button', 25), ('frame', 32)):
        a.emit('83bb'); a.word(DATA[name+'_resource']); a.emit('00')
        a.branch('0f85', name+'_loaded')
        a.emit('6a00 6a00 6a02 8d83'); a.word(DATA[name+'_resource']); a.emit('50')
        a.emit('b9'); a.word(size); a.emit('ba'); a.word(size)
        a.emit('8d83'); a.word(DATA[name+'_name'])
        a.relative('e8', 0x4f2cb4)
        a.label(name+'_loaded')
    # Scope the new frame to the real city service window, never shared GUI.
    for offset in range(0, 12, 4):
        a.emit('8b83'); a.word(DATA['frame_resource']+offset)
        a.emit('8986'); a.word(0x338+offset)
    a.emit('c686ad02000001')
    for name, identifier in zip(('contracts', 'party'), NEW_BUTTON_IDS):
        a.emit('56 8d8b'); a.word(DATA['button_resource'])
        a.emit('b201 8b83'); a.word(0xa2ecdc-IMAGE_BASE)
        a.relative('e8', 0xa4517c)
        a.emit('89c7 8983'); a.word(DATA[name+'_button'])
        a.emit('c78778020000'); a.word(identifier)
        a.emit('c7878401000002000000 c7473020000000 c7473420000000')
        a.emit('c74738e8000000 c7473c19000000')
        a.emit('89f8 8d93'); a.word(DATA[name+'_caption'])
        a.relative('e8', 0xa42b04)
        a.emit('8d87a0020000 8d93'); a.word(ENTRIES[name]-IMAGE_BASE)
        a.relative('e8', 0xa55038)
    a.relative('e8', ENTRIES['layout'])
    a.emit('619d c21400')
    result[ENTRIES['construct']] = a.finish()

    a = Assembler(ENTRIES['layout'])
    a.emit('9c60'); a.base()
    a.emit('8bb3'); a.word(DATA['city'])
    a.emit('85f6'); a.branch('0f84', 'done')
    a.emit('31ff')
    _city_guard(a, 'visibility')
    a.emit('bf01000000')
    a.label('visibility')
    for name in ('contracts', 'party'):
        a.emit('8b83'); a.word(DATA[name+'_button'])
        a.emit('85c0'); a.branch('0f84', name+'_visibility_done')
        a.emit('89fa 885049 88504a')
        a.label(name+'_visibility_done')
    # Iterate native child ownership, not persistent pointers to pre-existing
    # services. Hidden controls retain their ordinary callback and geometry.
    a.emit('89f0'); a.relative('e8', 0xa424d4)
    a.emit('50 31ff bd20000000')
    a.label('loop')
    a.emit('3b3c24'); a.branch('0f8d', 'fitted')
    a.emit('89f0 89fa'); a.relative('e8', 0xa424c4)
    a.emit('50 8b93'); a.word(0xa2ecdc-IMAGE_BASE)
    a.relative('e8', 0x4095ac)
    a.emit('84c0 58'); a.branch('0f84', 'next')
    a.emit('80784900'); a.branch('0f84', 'next')
    # The city skin applies to every visible service button, while fields for
    # transport, service tags and event callbacks stay original.
    for offset in range(0, 12, 4):
        a.emit('8b93'); a.word(DATA['button_resource']+offset)
        a.emit('8990'); a.word(0x294+offset)
    a.emit('c7403010000000 896834 c74038f8000000 c7403c19000000 83c520')
    a.label('next'); a.emit('47'); a.branch('e9', 'loop')
    a.label('fitted'); a.emit('83c404 83c510 896e3c c7463818010000')
    a.label('done'); a.emit('619d c3')
    result[ENTRIES['layout']] = a.finish()

    for name in ('contracts', 'party'):
        a = Assembler(ENTRIES[name])
        a.emit('9c60'); a.base()
        _city_guard(a, 'done')
        a.emit('8d93'); a.word(DATA[name+'_command'])
        a.emit('31c9 31c0')
        a.relative('e8', 0x9ff3e4)
        a.label('done'); a.emit('619d c3')
        result[ENTRIES[name]] = a.finish()

    a = Assembler(ENTRIES['refresh'])
    a.relative('e8', 0x9e3c88)
    a.relative('e9', ENTRIES['layout'])
    result[ENTRIES['refresh']] = a.finish()
    return result


def section_payload() -> bytes:
    out = bytearray(SECTION_SIZE)
    occupied = []
    def put(offset, raw):
        if offset < 0 or offset+len(raw) > SECTION_SIZE:
            raise ValueError('City extension exceeds its bounded section')
        if any(offset < end and start < offset+len(raw) for start, end in occupied):
            raise ValueError('City extension payload overlaps')
        occupied.append((offset, offset+len(raw)))
        out[offset:offset+len(raw)] = raw
    for va, code in thunks().items():
        put(va-IMAGE_BASE-SECTION_RVA, code)
    for name, caption in (
        ('button_name', 'pda\\contracts_button.png'),
        ('frame_name', 'pda\\contracts_frame.png'),
        ('contracts_caption', 'Контракты'), ('party_caption', 'Группа'),
        ('contracts_command', '!contracts list'), ('party_command', '!party status')):
        # Resource paths are Delphi UnicodeString literals (unit count), while
        # Caption and the chat sender require BSTR/WideString (byte count).
        # Both have a real terminating NUL; the extra immutable metadata before
        # BSTR's length field is never accessed by its native allocator.
        raw = caption.encode('utf-16le')
        length = len(raw)//2 if name.endswith('_name') else len(raw)
        put(DATA[name]-SECTION_RVA-12,
            struct.pack('<III', 0x000204b0, 0xffffffff, length)+raw+b'\0\0')
    put(0xe00, SIGNATURE)
    return bytes(out)


def edit_specifications() -> list[tuple[int, bytes, bytes, str]]:
    changes = []
    def call(site, before, after, why):
        changes.append((site,
            b'\xe8'+struct.pack('<i', before-site-5),
            b'\xe8'+struct.pack('<i', after-site-5), why))
    call(0x85c9ef, 0x8d3604, ENTRIES['construct'],
         'Add two genuine city child controls after the existing decoration')
    for site in (0x7d2af3, 0x7d307b, 0x7d30b7, 0x7d30df,
                 0x8596ea, 0x873e89, 0x873ebb, 0x9e5130):
        # All native refresh calls are checked against this exact release.
        call(site, 0x9e3c88, ENTRIES['refresh'],
             'Reflow the city services after native visibility refresh')
    return changes


def _patch_known(data: bytes) -> bytes:
    pe = pefile.PE(data=data)
    if (pe.OPTIONAL_HEADER.ImageBase != IMAGE_BASE or
        pe.FILE_HEADER.Machine != 0x14c or
        pe.OPTIONAL_HEADER.SizeOfImage != SECTION_RVA or
        pe.sections[-1].Name.rstrip(b'\0') != b'.tiochar' or
        pe.sections[-1].PointerToRawData+pe.sections[-1].SizeOfRawData != len(data)):
        raise ValueError('Unexpected published native client layout')
    header = pe.sections[-1].get_file_offset()+40
    if header+40 > pe.OPTIONAL_HEADER.SizeOfHeaders or any(data[header:header+40]):
        raise ValueError('No verified room for the city extension section header')
    result = bytearray(data)
    for va, old, new, _ in edit_specifications():
        offset = pe.get_offset_from_rva(va-IMAGE_BASE)
        if data[offset:offset+len(old)] != old:
            raise ValueError('Unexpected city native hook bytes at '+hex(va))
        result[offset:offset+len(new)] = new
    raw_offset = len(result)
    if raw_offset % pe.OPTIONAL_HEADER.FileAlignment:
        raise ValueError('Unexpected native file alignment')
    result.extend(section_payload())
    result[header:header+40] = struct.pack('<8sIIIIIIHHI', SECTION_NAME,
        SECTION_SIZE, SECTION_RVA, SECTION_SIZE, raw_offset, 0, 0, 0, 0, 0xe0000020)
    struct.pack_into('<H', result, pe.FILE_HEADER.get_field_absolute_offset('NumberOfSections'), len(pe.sections)+1)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), SECTION_RVA+SECTION_SIZE)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 0)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfCode'), pe.OPTIONAL_HEADER.SizeOfCode+SECTION_SIZE)
    return bytes(result)


def patch(data: bytes) -> bytes:
    if hashlib.sha256(data).hexdigest() == BASE_SHA:
        return _patch_known(data)
    # Idempotence is an exact forward reconstruction, including PE headers and
    # every original byte; a signature alone never authorizes a binary.
    try:
        pe = pefile.PE(data=data)
        section = pe.sections[-1]
        if (section.Name.rstrip(b'\0') != SECTION_NAME or section.VirtualAddress != SECTION_RVA or
            section.SizeOfRawData != SECTION_SIZE or
            section.PointerToRawData+SECTION_SIZE != len(data)):
            raise ValueError('Unknown native city section')
        restored = bytearray(data[:section.PointerToRawData])
        restored[section.get_file_offset():section.get_file_offset()+40] = bytes(40)
        struct.pack_into('<H', restored, pe.FILE_HEADER.get_field_absolute_offset('NumberOfSections'), len(pe.sections)-1)
        struct.pack_into('<I', restored, pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), SECTION_RVA)
        struct.pack_into('<I', restored, pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfCode'), pe.OPTIONAL_HEADER.SizeOfCode-SECTION_SIZE)
        for va, old, _new, _ in edit_specifications():
            offset = pe.get_offset_from_rva(va-IMAGE_BASE)
            restored[offset:offset+len(old)] = old
        if hashlib.sha256(restored).hexdigest() == BASE_SHA and _patch_known(bytes(restored)) == data:
            return data
    except (ValueError, pefile.PEFormatError, struct.error):
        pass
    raise ValueError('Expected the exact published 2026.10.07.4 silver.dll or this complete local city extension')


def patch_plan(previous: bytes, updated: bytes) -> dict:
    if hashlib.sha256(previous).hexdigest() != BASE_SHA or patch(previous) != updated:
        raise ValueError('City patch plan requires the exact source and payload')
    pe = pefile.PE(data=previous)
    return dict(schema=1, overlay_id='contracts-city-field-hq-v1',
        source_sha256=hashlib.sha256(previous).hexdigest(),
        payload_sha256=hashlib.sha256(updated).hexdigest(),
        source_size=len(previous), payload_size=len(updated),
        section=dict(name=SECTION_NAME.decode(), rva=hex(SECTION_RVA), size=SECTION_SIZE),
        changes=[dict(native_va=hex(va), offset=pe.get_offset_from_rva(va-IMAGE_BASE),
            previous_hex=old.hex(), updated_hex=new.hex(), reason=why)
            for va, old, new, why in edit_specifications()],
        city_ids=list(CITY_IDS), commands=['!contracts list', '!party status'],
        graphical_clients=0, network_connections=0)
