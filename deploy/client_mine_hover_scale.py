"""Restore physical mouse coordinates only during native deposit hit testing.

The original 814928 detector compares a camera-projected world rectangle with
Silver's copied mouse coordinates. Independent UI scaling makes those copies
logical, while deposits and their rectangles stay physical. Reuse the reviewed
software-cursor scope adapter to borrow the untouched TI mouse during this one
call, then restore the logical copies and previous render scope. Native deposit
selection, adjacency, carrying-drill eligibility and action packets stay intact.

Pure byte transformer; no process attachment, installed file or publication.
"""
from __future__ import annotations

import hashlib
import struct

import pefile

from . import client_ui_scale as scale

BASE_SHA = 'c8849a2997909c9ad6e09c674e67a641de7604aec2ddb829e4ee4187b87a972c'
IMAGE_BASE = 0x400000
HOOK = 0x9f3c0b
NATIVE = 0x814928
SLOT_RVA = 0x827b00
SLOT_SIZE = 0x100
WRAPPER = IMAGE_BASE + SLOT_RVA
SIGNATURE_RVA = SLOT_RVA + 0xc0
SIGNATURE = b'TIO-mine-physical-hover-v1'
NATIVE_BODY_RVA = NATIVE - IMAGE_BASE
NATIVE_BODY_SIZE = 0x1b1
NATIVE_BODY_SHA = '3f996310be16ce7699a639e1f446371a1620272cada0b8e5390e6dc26d501106'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def payload():
    result = bytearray(SLOT_SIZE)
    code = scale.scoped_code(WRAPPER, NATIVE, 0, size=0xc0, cursor=True)
    result[:0xc0] = code
    result[0xc0:0xc0 + len(SIGNATURE) + 1] = SIGNATURE + b'\0'
    return bytes(result)


def patch(data, *, expected_sha=BASE_SHA):
    if sha(data) != expected_sha:
        raise ValueError('Mine hover requires the exact reviewed native candidate')
    pe = pefile.PE(data=data)
    try:
        if (pe.FILE_HEADER.Machine != 0x14c
                or pe.OPTIONAL_HEADER.ImageBase != IMAGE_BASE):
            raise ValueError('Unexpected native PE target')
        if sha(pe.get_data(NATIVE_BODY_RVA, NATIVE_BODY_SIZE)) != NATIVE_BODY_SHA:
            raise ValueError('Native mine deposit detector body differs')
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
            raise ValueError('Mine hover call or reserved wrapper space differs')
        for block in pe.DIRECTORY_ENTRY_BASERELOC:
            for entry in block.entries:
                if entry.type == pefile.RELOCATION_TYPE['IMAGE_REL_BASED_HIGHLOW']:
                    if (SLOT_RVA <= entry.rva < SLOT_RVA + SLOT_SIZE
                            or HOOK - IMAGE_BASE <= entry.rva < HOOK - IMAGE_BASE + 5):
                        raise ValueError('Mine hover patch overlaps an absolute relocation')
        result = bytearray(data)
        result[offset:offset + SLOT_SIZE] = payload()
        result[hook_offset:hook_offset + 5] = after
        struct.pack_into('<I', result,
                         pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 0)
        return bytes(result)
    finally:
        pe.close()


def metadata():
    return {'scope': 'Native mine deposit and installed drill hit testing',
            'native_va': hex(NATIVE), 'call_va': hex(HOOK),
            'wrapper_rva': hex(SLOT_RVA), 'wrapper_size': SLOT_SIZE,
            'logical_mouse_restored': True, 'physical_mouse_unchanged': True,
            'native_detector_body_unchanged': True, 'native_actions_unchanged': True,
            'graphical_validation': False, 'published': False}
