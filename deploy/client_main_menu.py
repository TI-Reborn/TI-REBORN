"""Request the authenticated character list from the in-game Main menu button."""
from hashlib import sha256
import struct

import pefile

from tio.protocol.character_select import RETURN_TO_CHARACTER_SELECT
from .client_equipment_batch import Code

SOURCE_SHA = 'cae8fe433d8fd9be70600e0695ad033d388bd2c2d01c513d95b9e16dae4a81c5'
IMAGE_BASE = 0x400000
BUTTON_CALLBACK = 0x88585c
ENTRY = 0xcea900


def main_menu_request() -> bytes:
    code = Code(ENTRY)
    code.emit('53')
    code.base()
    code.emit('8b83')
    code.word(0xac600c - IMAGE_BASE)
    code.emit('8b00')
    code.call(0x6748b0)
    for value in RETURN_TO_CHARACTER_SELECT:
        code.emit(f'8b00 b2{value:02x}')
        code.call(0x675bf8)
    code.emit('8b00 8b10 ff12 5b c3')
    return code.finish(0x40)


def patch(source: bytes) -> bytes:
    if sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.19.3 Silver')
    code = main_menu_request()
    result = bytearray(source)
    with pefile.PE(data=source, fast_load=True) as pe:
        callback = pe.get_offset_from_rva(BUTTON_CALLBACK - IMAGE_BASE)
        cave = pe.get_offset_from_rva(ENTRY - IMAGE_BASE)
        if source[callback - 1:callback + 4] != b'\xba\xf4\x2b\x8a\x00':
            raise ValueError('Native Main menu binding changed')
        if any(source[cave:cave + len(code)]):
            raise ValueError('Native Main menu code space is occupied')
        # The binding's existing PE relocation also relocates the new pointer.
        struct.pack_into('<I', result, callback, ENTRY)
        result[cave:cave + len(code)] = code
    return bytes(result)
