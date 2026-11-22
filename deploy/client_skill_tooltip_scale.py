"""Draw the skill targeting balloon in the UI scale scope (Silver 2026.11.14.1).

Silver 9f410d calls 8b6470, the skill targeting balloon (name, damage, AP),
right after 9f4108 draws the ordinary attack balloon. Both read the logical
mouse copies, but only 9f4108 was wrapped in the UI render scope, so at 125%
and 150% interface scale the skill balloon landed at mouse/scale. Wrap 9f410d
exactly like the attack balloon (scope 1); the native body is unchanged.
"""
import hashlib

import pefile

from . import client_ui_scale as scale

SOURCE_SHA = 'f5c8e02f5e36e49e5ca9aa511220dfef48979b5c208fc5cd3ab9876c025c5526'
IMAGE_BASE = 0x400000
HOOK = 0x9f410d
NATIVE = 0x8b6470
# Free tail of the reviewed 0xcc3e00 cave block (skill target check uses +0..+3f).
WRAPPER = 0xcc3e40
SIZE = 0xc0


def payload() -> bytes:
    return scale.scoped_code(WRAPPER, NATIVE, 1, size=SIZE)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.14.1 Silver')
    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        if pe.get_data(scale.SIGNATURE_RVA, len(scale.SIGNATURE)) != scale.SIGNATURE:
            raise ValueError('Expected the reviewed independent UI scale runtime')
        for block in pe.DIRECTORY_ENTRY_BASERELOC:
            for entry in block.entries:
                if (WRAPPER - IMAGE_BASE <= entry.rva < WRAPPER - IMAGE_BASE + SIZE
                        or HOOK - IMAGE_BASE <= entry.rva < HOOK - IMAGE_BASE + 5):
                    raise ValueError('Skill tooltip patch overlaps an absolute relocation')
        for address, expected, replacement in (
            (HOOK, scale.call_bytes(HOOK, NATIVE), scale.call_bytes(HOOK, WRAPPER)),
            (WRAPPER, bytes(SIZE), payload()),
        ):
            offset = pe.get_offset_from_rva(address - IMAGE_BASE)
            if source[offset:offset + len(expected)] != expected:
                raise ValueError('Skill tooltip call or wrapper space differs')
            result[offset:offset + len(expected)] = replacement
    return bytes(result)
