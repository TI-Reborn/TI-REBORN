"""Compile incremental warehouse descriptions; never edit an installed client.

Only the shop's numeric description call is redirected. Native paid-service
status and authoritative total powers retain their original representation.
"""
from __future__ import annotations

import hashlib
import struct

import pefile

from .client_equipment_batch import Code

BASE = 0x400000
BASE_SHA = '87d54db3ae2d20d2065b0ecee9fe728c294f170b2cd6f11ba818c01d655bc5ed'
HOOK, ORIGINAL = 0x848ead, 0x84861c
RVA, SIZE = 0x8d8000, 0x1000
LOOKUP, TOTALS = RVA+0x180, RVA+0x300


def payload() -> bytes:
    """Use XML total powers, with compiled policy for missing cached records."""
    from tio.services import OFFERS

    totals = tuple(power for power, _ in OFFERS[1])
    if not totals or len(totals) > 255 or any(a <= b for a, b in zip(totals, (0,)+totals)):
        raise ValueError('Strictly increasing warehouse total powers required')
    c = Code(BASE+RVA)
    # The original nested helper receives its paint caller's frame on stack.
    c.emit('8b4c2404 8b49fc 833901'); c.branch('0f85', 'original')
    c.emit('55 53 56 57 89c6 89d7'); c.base()
    c.emit('4e 81fe'); c.word(len(totals)-1); c.branch('0f87', 'invalid')
    c.emit('46 89f0'); c.call(BASE+LOOKUP)
    c.emit('85c0'); c.branch('0f8e', 'fallback')
    c.emit('89c5 89f0 48'); c.branch('0f84', 'render')
    c.call(BASE+LOOKUP)
    c.emit('85c0'); c.branch('0f8e', 'fallback')
    c.emit('29c5 85ed'); c.branch('0f8f', 'render')
    c.label('fallback')
    # shortcut: cached XML uses compiled tiers; rebuild when adding levels.
    c.emit('8bacb3'); c.word(TOTALS-4)
    c.emit('83fe01'); c.branch('0f84', 'render')
    c.emit('2bacb3'); c.word(TOTALS-8)
    c.label('render')
    c.emit('89e8 89fa'); c.call(0x4244b4)
    c.branch('e9', 'done')
    c.label('invalid')
    c.emit('89f8'); c.call(0x40b09c)
    c.label('done'); c.emit('5f5e5b5dc3')
    c.label('original'); c.jump(ORIGINAL)
    main = c.finish(0x180)

    c = Code(BASE+LOOKUP)
    c.emit('56 89c6 8b8b'); c.word(0xacefb0-BASE)
    c.emit('85c9'); c.branch('0f84', 'missing')
    c.emit('8b51fc 85d2'); c.branch('0f8e', 'missing')
    c.label('next')
    c.emit('833901'); c.branch('0f85', 'advance')
    c.emit('397104'); c.branch('0f85', 'advance')
    c.emit('8b4108 5ec3')
    c.label('advance'); c.emit('83c118 4a'); c.branch('0f85', 'next')
    c.label('missing'); c.emit('31c0 5ec3')
    raw = main+c.finish(0x180)+struct.pack('<'+'I'*len(totals), *totals)
    return raw.ljust(SIZE, b'\0')


def patch(source: bytes) -> bytes:
    """Append PIC code to the pinned release, preserving every other byte."""
    if hashlib.sha256(source).hexdigest() != BASE_SHA:
        raise ValueError('Unknown published Silver build')
    with pefile.PE(data=source) as pe:
        last = pe.sections[-1]
        if (pe.OPTIONAL_HEADER.ImageBase != BASE or pe.OPTIONAL_HEADER.SizeOfImage != RVA
                or last.Name != b'.tioscr\0' or last.VirtualAddress != 0x823000
                or last.Misc_VirtualSize != 0xb5000 or last.SizeOfRawData != 0xb5000
                or last.PointerToRawData != 0x76b200
                or last.PointerToRawData+last.SizeOfRawData != len(source)):
            raise ValueError('Silver final section cannot be safely extended')
        offset = pe.get_offset_from_rva(HOOK-BASE)
        if source[offset:offset+5] != b'\xe8'+struct.pack('<i', ORIGINAL-HOOK-5):
            raise ValueError('Services description call changed')
        result = bytearray(source)
        result[offset:offset+5] = b'\xe8'+struct.pack('<i', BASE+RVA-HOOK-5)
        for field in ('Misc_VirtualSize', 'SizeOfRawData'):
            struct.pack_into('<I', result, last.get_field_absolute_offset(field), getattr(last, field)+SIZE)
        struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), RVA+SIZE)
        result.extend(payload())
        return bytes(result)


def review(source: bytes, candidate: bytes) -> dict:
    """Return the complete allowlist of changed original file ranges."""
    if patch(source) != candidate:
        raise ValueError('Candidate differs from the checked description patch')
    with pefile.PE(data=source) as pe:
        changes = [(pe.get_offset_from_rva(HOOK-BASE), 5, 'Incremental warehouse description call')]
        changes.extend((pe.sections[-1].get_field_absolute_offset(field), 4, 'Extend final PIC section')
                       for field in ('Misc_VirtualSize', 'SizeOfRawData'))
        changes.append((pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), 4, 'Map appended PIC code'))
    return dict(changes=[dict(offset=offset, size=size, purpose=purpose)
                         for offset, size, purpose in sorted(changes)],
                appended_size=SIZE, source_sha256=BASE_SHA,
                candidate_sha256=hashlib.sha256(candidate).hexdigest())
