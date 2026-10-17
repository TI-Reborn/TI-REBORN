"""Checked native sampler filtering for the original 0.1.6 client.

The launcher-pinned TI executable and image resources stay byte-identical on
disk. At native Silver startup, exact original TI setter bytes are checked
before installing three small in-memory entry wrappers. MAG/MIN NONE or POINT
become LINEAR; MIP POINT becomes LINEAR, while MIP NONE stays disabled. Native
cache writes, device gates, sampler stages and device reset paths still execute.
No global mip generation is added to glyph/sprite atlases; UVs and alpha remain
owned by the original engine. Existing burn/flash/postprocessing remains intact.
"""
from __future__ import annotations

import hashlib
import struct

import pefile

from .client_equipment_batch import Code

IMAGE_BASE = 0x400000
BASE_SHA = '5afcac81549ac2ca5e6ceb9a015a075c3a986f6fbda24d0a90a4ad407f066d17'
TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
REGION = 0x874000
SIZE = 0x2000
STARTUP_HOOK = 0x4f255f
PREVIOUS_STARTUP = 0xc2d000
STARTUP = IMAGE_BASE + REGION
INSTALL = STARTUP + 0x100
MAG = STARTUP + 0xc00
MIN = STARTUP + 0xd00
MIP = STARTUP + 0xe00
STATE = REGION + 0x1100
KERNEL = REGION + 0x1200
FLUSH_NAME = REGION + 0x1240
SIGNATURE_RVA = REGION + 0x1300
SIGNATURE = b'TIO-native-texture-linear-v1'
VP_RVA, GET_MODULE_RVA, GET_PROC_RVA, PROCESS_RVA = 0x77a090, 0x77a178, 0x77a170, 0x77a1b0
PAGE, PAGE_SIZE = 0x65a000, 0x2000
# Full setter bodies, excluding following methods, contain no TI relocations.
SETTERS = ((0x65a934, MAG, 94), (0x65aa00, MIN, 97), (0x65aad0, MIP, 97))
PROLOGUE = bytes.fromhex('558bec83c4f4')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def field(c, op, offset):
    c.emit(op); c.word(STATE + offset)


def set_field(c, offset, value):
    field(c, 'c783', offset); c.word(value)


def iat(c, rva):
    c.emit('ff93'); c.word(rva)


def flush(c):
    iat(c, PROCESS_RVA)
    c.emit('68'); c.word(PAGE_SIZE)
    c.emit('68'); c.word(PAGE)
    c.emit('50'); field(c, 'ff93', 12)


def protect_restore(c):
    c.emit('8d83'); c.word(STATE + 16); c.emit('50')
    field(c, 'ffb3', 8)
    c.emit('68'); c.word(PAGE_SIZE)
    c.emit('68'); c.word(PAGE)
    iat(c, VP_RVA)


def rollback(c):
    for address, _, _ in SETTERS:
        c.emit('c705'); c.word(address); c.emit(PROLOGUE[:4].hex())
        c.emit('66c705'); c.word(address+4); c.emit(PROLOGUE[4:].hex())
    flush(c)


def filter_code(address, target, *, mip=False):
    c = Code(address)
    c.emit('83f901')
    c.branch('0f85' if mip else '0f87', 'stock')
    c.emit('b902000000')
    c.label('stock'); c.emit(PROLOGUE.hex())
    # TI is the launcher's fixed-base, SHA-pinned executable. PUSH/RET leaves
    # EAX(self), DL(stage), ECX(filter), EBX/ESI/EDI and the native frame intact.
    c.emit('68'); c.word(target+len(PROLOGUE)); c.emit('c3')
    return c.finish(0x100)


def startup_code():
    c = Code(STARTUP); c.emit('9c60'); c.call(INSTALL); c.emit('619d')
    c.jump(PREVIOUS_STARTUP)
    return c.finish(0x100)


def install_code(ti):
    pe = pefile.PE(data=ti)
    c = Code(INSTALL); c.emit('9c60'); c.base()
    field(c, '83bb', 0); c.emit('00'); c.branch('0f85', 'done')
    # Verify every instruction of all three original methods before making
    # any runtime write, including their cache layout and D3D device calls.
    for address, _, length in SETTERS:
        raw = pe.get_data(address-IMAGE_BASE, length)
        if raw[:6] != PROLOGUE:
            raise ValueError('Unexpected native TI sampler prologue')
        for offset in range(0, length-length % 4, 4):
            c.emit('813d'); c.word(address+offset); c.emit(raw[offset:offset+4].hex())
            c.branch('0f85', 'unknown')
        for offset in range(length-length % 4, length):
            c.emit('803d'); c.word(address+offset); c.emit(raw[offset:offset+1].hex())
            c.branch('0f85', 'unknown')
    c.emit('8d83'); c.word(KERNEL); c.emit('50'); iat(c, GET_MODULE_RVA)
    c.emit('85c0'); c.branch('0f84', 'unknown')
    c.emit('8d93'); c.word(FLUSH_NAME); c.emit('52 50'); iat(c, GET_PROC_RVA)
    c.emit('85c0'); c.branch('0f84', 'unknown'); field(c, '8983', 12)
    c.emit('8d83'); c.word(STATE+8); c.emit('50 6a40 68'); c.word(PAGE_SIZE)
    c.emit('68'); c.word(PAGE); iat(c, VP_RVA)
    c.emit('85c0'); c.branch('0f84', 'denied')
    for address, wrapper, _ in SETTERS:
        c.emit('8d83'); c.word(wrapper-IMAGE_BASE)
        c.emit('2d'); c.word(address+5)
        c.emit('a3'); c.word(address+1)
        c.emit('c605'); c.word(address); c.emit('e9')
        c.emit('c605'); c.word(address+5); c.emit('90')
    flush(c); c.emit('85c0'); c.branch('0f84', 'flush_failed')
    protect_restore(c); c.emit('85c0'); c.branch('0f84', 'restore_failed')
    set_field(c, 0, 1); c.branch('e9', 'done')
    c.label('flush_failed'); rollback(c); protect_restore(c)
    set_field(c, 4, 4); c.branch('e9', 'failed')
    c.label('restore_failed'); rollback(c); protect_restore(c)
    set_field(c, 4, 3); c.branch('e9', 'failed')
    c.label('unknown'); set_field(c, 4, 1); c.branch('e9', 'failed')
    c.label('denied'); set_field(c, 4, 2)
    c.label('failed'); set_field(c, 0, -1)
    c.label('done'); c.emit('619d c3')
    return c.finish(0xb00)


def payload(ti):
    result = bytearray(SIZE)
    for offset, raw in ((0, startup_code()), (0x100, install_code(ti)),
                        (0xc00, filter_code(MAG, SETTERS[0][0])),
                        (0xd00, filter_code(MIN, SETTERS[1][0])),
                        (0xe00, filter_code(MIP, SETTERS[2][0], mip=True)),
                        (0x1200, 'kernel32.dll\0'.encode('utf-16le')),
                        (0x1240, b'FlushInstructionCache\0'),
                        (0x1300, SIGNATURE+b'\0')):
        result[offset:offset+len(raw)] = raw
    return bytes(result)


def patch(data, *, expected_sha, ti):
    if sha(data) != expected_sha or sha(ti) != TI_SHA:
        raise ValueError('Texture quality requires reviewed Silver and original launcher-compatible TI')
    pe = pefile.PE(data=data)
    last = pe.sections[-1]
    if (pe.FILE_HEADER.Machine != 0x14c or pe.OPTIONAL_HEADER.ImageBase != IMAGE_BASE
            or pe.OPTIONAL_HEADER.SizeOfImage != REGION
            or last.VirtualAddress+last.Misc_VirtualSize != REGION
            or last.Misc_VirtualSize != last.SizeOfRawData
            or last.PointerToRawData+last.SizeOfRawData != len(data)
            or last.Characteristics & 0xe0000000 != 0xe0000000
            or len(data) % 0x200):
        raise ValueError('Unknown safely appendable Silver layout')
    old_hook = b'\xe9'+struct.pack('<i', PREVIOUS_STARTUP-STARTUP_HOOK-5)
    at = pe.get_offset_from_rva(STARTUP_HOOK-IMAGE_BASE)
    if data[at:at+5] != old_hook:
        raise ValueError('Existing portrait/UI startup chain differs')
    result = bytearray(data)
    result[at:at+5] = b'\xe9'+struct.pack('<i', STARTUP-STARTUP_HOOK-5)
    for name in ('Misc_VirtualSize', 'SizeOfRawData'):
        struct.pack_into('<I', result, last.get_field_absolute_offset(name), getattr(last,name)+SIZE)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), REGION+SIZE)
    # Preserve the baseline zero checksum. Other PE headers stay exact.
    if pe.OPTIONAL_HEADER.CheckSum:
        raise ValueError('Unexpected nonzero original Silver checksum')
    result.extend(payload(ti))
    return bytes(result)


def review(source, candidate):
    pe = pefile.PE(data=source)
    spans = [(pe.get_offset_from_rva(STARTUP_HOOK-IMAGE_BASE), 5,
              'Chain guarded native texture sampler installation before existing UI/portrait startup')]
    for name in ('Misc_VirtualSize', 'SizeOfRawData'):
        spans.append((pe.sections[-1].get_field_absolute_offset(name), 4,
                      'Extend existing executable writable native runtime section'))
    spans.append((pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), 4,
                  'Map appended guarded sampler runtime'))
    return {'changes': [{'offset':at,'size':size,'source_sha256':sha(source[at:at+size]),
                         'candidate_sha256':sha(candidate[at:at+size]),'purpose':purpose}
                        for at,size,purpose in sorted(spans)],
            'appended_size':len(candidate)-len(source),
            'appended_sha256':sha(candidate[len(source):])}
