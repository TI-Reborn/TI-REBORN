"""Correct the battle cursor balloon's existing logical-pixel render scope.

Silver 0x9bfea0 draws the action/damage/accuracy/AP balloon using the copied
Silver mouse coordinates. Release13 converts these to logical UI pixels, but
its caller was incorrectly classified as a physical world overlay. Wrap that
one call in the existing UI render scope so the existing upload thunk maps its
vertices back to the physical cursor. The native tooltip, picking, physical
cursor, camera and world overlays are untouched.

Pure, bounded byte transformer: no game launch, process attachment or publish.
"""
from __future__ import annotations

import hashlib
import struct

import pefile

from . import client_ui_scale as scale

BASE_SHA = '3c99c9dd46a087564406b664f5895d7b0457f3dde95d4868353241f3330c4800'
IMAGE_BASE = 0x400000
HOOK = 0x9f4108
NATIVE = 0x9bfea0
# Reviewed zero-filled space after the twenty existing render wrappers and
# before the existing software-cursor wrapper at c27c00.
SLOT_RVA = 0x827900
SLOT_SIZE = 0x200
WRAPPER = IMAGE_BASE + SLOT_RVA
SIGNATURE_RVA = SLOT_RVA + 0x100
SIGNATURE = b'TIO-battle-cursor-tooltip-v1'
NATIVE_BODY_RVA = NATIVE - IMAGE_BASE
NATIVE_BODY_SIZE = 0x37f
NATIVE_BODY_SHA = '635feb82ce8c4de3f4b5af8295a93590405243939531d93536e5981489044eef'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def payload():
    result = bytearray(SLOT_SIZE)
    result[:0x100] = scale.scoped_code(WRAPPER, NATIVE, 1)
    result[0x100:0x100 + len(SIGNATURE) + 1] = SIGNATURE + b'\0'
    return bytes(result)


def patch(data, *, expected_sha=BASE_SHA):
    if sha(data) != expected_sha:
        raise ValueError('Battle tooltip requires the exact reviewed native candidate')
    pe = pefile.PE(data=data)
    try:
        if (pe.FILE_HEADER.Machine != 0x14c
                or pe.OPTIONAL_HEADER.ImageBase != IMAGE_BASE):
            raise ValueError('Unexpected native PE target')
        if sha(pe.get_data(NATIVE_BODY_RVA, NATIVE_BODY_SIZE)) != NATIVE_BODY_SHA:
            raise ValueError('Native battle cursor tooltip body differs')
        if pe.get_data(scale.SIGNATURE_RVA, len(scale.SIGNATURE)) != scale.SIGNATURE:
            raise ValueError('Expected the reviewed independent UI scale runtime')
        offset = pe.get_offset_from_rva(SLOT_RVA)
        hook_offset = pe.get_offset_from_rva(HOOK - IMAGE_BASE)
        before = scale.call_bytes(HOOK, NATIVE)
        after = scale.call_bytes(HOOK, WRAPPER)
        current = data[offset:offset + SLOT_SIZE]
        if current == payload() and data[hook_offset:hook_offset + 5] == after:
            return data
        if (current != bytes(SLOT_SIZE)
                or data[hook_offset:hook_offset + 5] != before):
            raise ValueError('Battle tooltip call or reserved wrapper space differs')
        for block in pe.DIRECTORY_ENTRY_BASERELOC:
            for entry in block.entries:
                if entry.type == pefile.RELOCATION_TYPE['IMAGE_REL_BASED_HIGHLOW']:
                    if (SLOT_RVA <= entry.rva < SLOT_RVA + SLOT_SIZE
                            or HOOK - IMAGE_BASE <= entry.rva < HOOK - IMAGE_BASE + 5):
                        raise ValueError('Battle tooltip patch overlaps an absolute relocation')
        result = bytearray(data)
        result[offset:offset + SLOT_SIZE] = payload()
        result[hook_offset:hook_offset + 5] = after
        struct.pack_into('<I', result,
                         pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 0)
        return bytes(result)
    finally:
        pe.close()


def metadata():
    return {'scope': 'Battle cursor action/damage/accuracy/AP balloon',
            'native_va': hex(NATIVE), 'call_va': hex(HOOK),
            'wrapper_rva': hex(SLOT_RVA), 'wrapper_size': SLOT_SIZE,
            'logical_mouse_unchanged': True, 'physical_mouse_unchanged': True,
            'native_tooltip_body_unchanged': True, 'world_overlays_unchanged': True,
            'graphical_validation': False, 'published': False}
