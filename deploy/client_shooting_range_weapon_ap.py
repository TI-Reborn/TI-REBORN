"""Keep native weapon targeting available at zero AP during Shooting Range combat."""
from hashlib import sha256
import struct

import pefile

from .client_equipment_batch import Code

SOURCE_SHA = 'd18da1a674017952104b865fb911cb3bc7cbfedb20472111a6135658221c5cad'
IMAGE_BASE = 0x400000
HOOK = 0xA83F94
ENTRY = 0xD15000
PROLOGUE = bytes.fromhex('558bec538bd8')


def weapon_cost_code() -> bytes:
    code = Code(ENTRY)
    code.emit('53 52')  # Preserve the actor argument and the original registers.
    code.base()
    code.emit('8b93'); code.word(0xAC64A0 - IMAGE_BASE)  # Active battle flag.
    code.emit('803a01'); code.branch('0f85', 'stock')
    code.emit('8b93'); code.word(0xAC6008 - IMAGE_BASE)  # Battle settings.
    code.emit('807a1910'); code.branch('0f85', 'stock')  # Mode 16 is Shooting Range.
    code.emit('5a 5b 31c0 c3')
    code.label('stock')
    code.emit('5a 5b'); code.emit(PROLOGUE.hex())
    code.jump(HOOK + len(PROLOGUE))
    return code.finish(0x40)


def patch(source: bytes) -> bytes:
    if sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected the reviewed Shooting Range Silver baseline')
    result = bytearray(source)
    code = weapon_cost_code()
    with pefile.PE(data=source) as pe:
        hook = pe.get_offset_from_rva(HOOK - IMAGE_BASE)
        entry = pe.get_offset_from_rva(ENTRY - IMAGE_BASE)
        section = pe.get_section_by_rva(ENTRY - IMAGE_BASE)
        if (section is None or not section.IMAGE_SCN_MEM_EXECUTE
                or entry + len(code) > section.PointerToRawData + section.SizeOfRawData):
            raise ValueError('Shooting Range hook requires executable Silver padding')
        if source[hook:hook + len(PROLOGUE)] != PROLOGUE or any(source[entry:entry + len(code)]):
            raise ValueError('Unexpected weapon cost entry or occupied Silver padding')
        result[entry:entry + len(code)] = code
        result[hook:hook + len(PROLOGUE)] = b'\xe9' + struct.pack('<i', ENTRY - HOOK - 5) + b'\x90'
    return bytes(result)
