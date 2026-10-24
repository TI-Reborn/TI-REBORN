"""Bounded presentation-only medkit-tooltip adapter for the published client.

Keeps item classes, metadata, use routes and ordinary healing text intact.
Only known nonmedical effect descriptions bypass the generic healing/AP rows.
"""
import hashlib
import struct
from pathlib import Path

import pefile

from .client_equipment_batch import Code
from .item_effect_descriptions import language_key, load_descriptions

BASE_SHA = '7fd0a3b221e6bd967faed999de90b77b54f04ec16864fc4ea85d19b6d68fbe96'
IMAGE_BASE = 0x400000
HOOK = 0x80d59f
LOOKUP = 0xa7b030
CONTINUE = 0x80d748
RVA = 0x882000
SIZE = 0x4000
ENTRY = IMAGE_BASE+RVA
TABLE = RVA+0x400
SIGNATURE = b'TIO-manual-item-effect-tooltips-v1'


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def call_bytes(source: int, target: int) -> bytes:
    return b'\xe8'+struct.pack('<i', target-source-5)


def payload(root: Path) -> bytes:
    descriptions = load_descriptions(root)['en']
    result = bytearray(SIZE)
    cursor = 0x800
    records = []
    for identity, lines in sorted(descriptions.items()):
        keys = []
        for index in range(len(lines)):
            key = language_key(identity, index)
            encoded = key.encode('utf-16le')
            cursor = (cursor+3)&~3
            header = struct.pack('<HHii', 1200, 2, -1, len(key))
            result[cursor:cursor+len(header)+len(encoded)+2] = header+encoded+b'\0\0'
            keys.append(RVA+cursor+len(header))
            cursor += len(header)+len(encoded)+2
        cursor = (cursor+3)&~3
        record = RVA+cursor
        for key in keys:
            struct.pack_into('<I', result, cursor, key)
            cursor += 4
        records.append((identity, len(lines), record))
    if cursor >= SIZE-0x100:
        raise ValueError('Tooltip string-table overflow')
    for index, record in enumerate(records):
        struct.pack_into('<III', result, 0x400+index*12, *record)
    c = Code(ENTRY)
    # The caller holds the row counter in EBX. Preserve its registers/flags,
    # reserve a managed Unicode temporary, and read the selected TSItem ID.
    c.emit('9c60 83ec10 31c0 890424 8b44242c 8b7008')
    c.base()
    c.emit('8d93')
    c.word(TABLE)
    c.emit('b9')
    c.word(len(records))
    c.label('find')
    c.emit('3b32')
    c.branch('0f84', 'found')
    c.emit('83c20c 49')
    c.branch('0f85', 'find')
    # Unknown IDs keep the original lookup and healing path unchanged.
    c.emit('83c410 619d')
    c.jump(LOOKUP)
    c.label('found')
    c.emit('8b4204 89442404 8b4208 01d8 89442408 8b442420 8944240c')
    c.label('line')
    c.emit('8b44240c 833820')
    c.branch('0f83', 'done')
    c.emit('8b442408 8b00 01d8 89e2')
    c.call(0x6675e0)  # Existing localization getter, EAX=key, EDX=out.
    c.emit('8b44240c 8b00 8d0480 8b8b')
    c.word(0xac580c-IMAGE_BASE)
    c.emit('8d0cc1 c70144ff4400 8d4104 8b1424')
    c.call(0x40b47c)  # Assign managed text into a 40-byte tooltip row.
    c.emit('8b44240c ff00 8344240804 ff4c2404')
    c.branch('0f85', 'line')
    c.label('done')
    c.emit('89e0')
    c.call(0x40b09c)  # Release the temporary; rows retain their own references.
    # Skip generic healing/AP rows only. Common weight/ownership rows follow.
    c.emit('83c410 8d83')
    c.word(CONTINUE-IMAGE_BASE)
    c.emit('89442424 619d c3')
    result[:0x400] = c.finish(0x400)
    result[-0x100:-0x100+len(SIGNATURE)] = SIGNATURE
    return bytes(result)


def patch(raw: bytes, root: Path) -> bytes:
    if sha(raw) != BASE_SHA:
        raise ValueError('Tooltip patch requires the exact published client')
    pe = pefile.PE(data=raw)
    try:
        section = pe.sections[-1]
        if (pe.FILE_HEADER.Machine != 0x14c or pe.OPTIONAL_HEADER.ImageBase != IMAGE_BASE
                or section.Name.rstrip(b'\0') != b'.tioscr'
                or section.VirtualAddress+section.Misc_VirtualSize != RVA
                or section.SizeOfRawData != section.Misc_VirtualSize
                or section.PointerToRawData+section.SizeOfRawData != len(raw)
                or section.Characteristics & 0xe0000000 != 0xe0000000):
            raise ValueError('Unexpected client extension boundary')
        offset = pe.get_offset_from_rva(HOOK-IMAGE_BASE)
        if raw[offset:offset+5] != call_bytes(HOOK, LOOKUP):
            raise ValueError('Medkit tooltip lookup differs')
        for block in pe.DIRECTORY_ENTRY_BASERELOC:
            for entry in block.entries:
                if entry.type and HOOK-IMAGE_BASE <= entry.rva < HOOK-IMAGE_BASE+5:
                    raise ValueError('Tooltip hook overlaps a relocation')
        result = bytearray(raw)
        result[offset:offset+5] = call_bytes(HOOK, ENTRY)
        for field in (8, 16):
            struct.pack_into('<I', result, section.get_file_offset()+field,
                             section.SizeOfRawData+SIZE)
        struct.pack_into('<I', result,
                         pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),
                         RVA+SIZE)
        result.extend(payload(root))
        return bytes(result)
    finally:
        pe.close()
