"""Legacy native server row: TI-REBORN, availability colours, integer online.

Pure checked transformer of the exact published 2026.10.11.1 Silver. Leaves
authentication, list06 parsing, row ABI, texture and battle hooks intact.
"""
from __future__ import annotations

import hashlib
import struct

import pefile
from .client_equipment_batch import Code

BASE_SHA = '4897eb6d6af6beb587fc9b303dc6911519d90b3414ae8cca8fd1ffb698c1f082'
IMAGE_BASE = 0x400000
APPEND_RVA = 0x876000
APPEND_SIZE = 0x1000
NAME_HELPER = IMAGE_BASE + APPEND_RVA
HEADER_HELPER = NAME_HELPER + 0x100
NAME_STRING = NAME_HELPER + 0x20c
HEADER_STRING = NAME_HELPER + 0x24c
SIGNATURE = b'TIO-native-server-list-status-online-v1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def call_bytes(address, target):
    return b'\xe8' + struct.pack('<i', target-address-5)


def string_bytes(value):
    # Native immutable UnicodeString: codepage, charsize, refcount, length.
    return struct.pack('<HHii', 1200, 2, -1, len(value)) + value.encode('utf-16-le') + b'\0\0'


def payload():
    c = Code(NAME_HELPER)
    c.emit('80fa01'); c.branch('0f85', 'original')
    # Renderer ABI EAX=control, EDX=server-id, ECX=&name. Other ids use its
    # unchanged localized/custom server-name collection.
    c.emit('53 51'); c.base()
    c.emit('8d93'); c.word(NAME_STRING-IMAGE_BASE)
    c.emit('58'); c.call(0x40b4c4); c.emit('5b c3')
    c.label('original'); c.jump(0x71e724)
    result = c.finish(0x100)
    c = Code(HEADER_HELPER)
    c.emit('53 52'); c.base()
    c.emit('8d93'); c.word(HEADER_STRING-IMAGE_BASE)
    c.emit('58'); c.call(0x40b4c4); c.emit('5b c3')
    result += c.finish(0x100)
    result += string_bytes('TI-REBORN').ljust(0x40, b'\0')
    result += string_bytes('Онлайн').ljust(0x40, b'\0')
    result += SIGNATURE + b'\0'
    return result.ljust(APPEND_SIZE, b'\0')


def specifications():
    return (
        (0x71f402, call_bytes(0x71f402, 0x71e724), call_bytes(0x71f402, NAME_HELPER),
         'Show TI-REBORN for the real server-id1 row; preserve other native names'),
        (0x71f1a7, call_bytes(0x71f1a7, 0x6675e0), call_bytes(0x71f1a7, HEADER_HELPER),
         'Label the integer-count column Онлайн'),
        (0x71f485, bytes.fromhex('8b45e4 80780e00 7427 c745f000ff00ff 8b45e4 80780f32 7607 c745f0ecec00ff 8b45e4 80780f4b 7607 c745f0b02e02ff'),
         b'\xe9'+struct.pack('<i', 0x71f4b5-0x71f485-5)+b'\x90'*43,
         'Keep native status green/gray for the count; remove load-percentage red/yellow colour thresholds'),
        (0x71f4be, bytes.fromhex('0fb6400f'), bytes.fromhex('0fb7400a'),
         'Format the original u16 online field rather than the derived load byte'),
        (0x71f4d5, call_bytes(0x71f4d5, 0x40c1bc), call_bytes(0x71f4d5, 0x40b4c4),
         'Assign the native integer string without appending a percent sign'),
    )


def patch(data):
    if sha(data) != BASE_SHA:
        raise ValueError('Server-list status requires the exact published Silver')
    p = pefile.PE(data=data)
    try:
        last = p.sections[-1]
        if (p.FILE_HEADER.Machine != 0x14c or p.OPTIONAL_HEADER.ImageBase != IMAGE_BASE
                or len(p.sections) != 13 or p.OPTIONAL_HEADER.SizeOfImage != APPEND_RVA
                or last.Name != b'.tioscr\0' or last.VirtualAddress != 0x823000
                or last.Misc_VirtualSize != 0x53000 or last.SizeOfRawData != 0x53000
                or last.PointerToRawData != 0x76b200
                or last.PointerToRawData+last.SizeOfRawData != len(data)):
            raise ValueError('Server-list status PE geometry differs')
        result = bytearray(data)
        for address, before, after, _ in specifications():
            if len(before) != len(after) or p.get_data(address-IMAGE_BASE, len(before)) != before:
                raise ValueError('Server-list presentation instruction differs: '+hex(address))
            at = p.get_offset_from_rva(address-IMAGE_BASE)
            result[at:at+len(after)] = after
        for field in ('Misc_VirtualSize', 'SizeOfRawData'):
            struct.pack_into('<I', result, last.get_field_absolute_offset(field), getattr(last, field)+APPEND_SIZE)
        struct.pack_into('<I', result, p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), APPEND_RVA+APPEND_SIZE)
        result.extend(payload())
        return bytes(result)
    finally:
        p.close()


def review(source, candidate):
    if patch(source) != candidate:
        raise ValueError('Candidate differs from the exact server-list status transformer')
    p = pefile.PE(data=source)
    try:
        ranges = [(p.get_offset_from_rva(a-IMAGE_BASE), len(old), purpose)
                  for a, old, _, purpose in specifications()]
        ranges += [(p.sections[-1].get_field_absolute_offset(f), 4, 'Extend the final executable section for bounded strings/helpers')
                   for f in ('Misc_VirtualSize', 'SizeOfRawData')]
        ranges += [(p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), 4, 'Map appended server presentation helpers')]
        return dict(changes=[dict(offset=a, size=n, purpose=why, source_sha256=sha(source[a:a+n]), candidate_sha256=sha(candidate[a:a+n]))
                             for a, n, why in sorted(ranges)], appended_size=APPEND_SIZE, appended_sha256=sha(candidate[len(source):]))
    finally:
        p.close()


def metadata():
    return dict(source_sha256=BASE_SHA, append_rva=hex(APPEND_RVA), appended_size=APPEND_SIZE,
                name='TI-REBORN', column='Онлайн', row_count_offset='0x0a/u16', row_status_offset='0x0e/u8',
                online_colour='ffb1efdb', offline_colour='ff606060', original_status_colour_branch_preserved=True,
                authentication_and_network_unchanged=True, previous_presentation_and_texture_hooks_preserved=True,
                real_graphical_clients=False, published=False)
