"""Expose the native Shop control in the Shooting Range location menu."""
import hashlib
import struct

import pefile

from .client_equipment_batch import Code

SOURCE_SHA = 'ae1681372487ffee7a20a481aad4ceb8bbbff2b0755fcd423fcf8ff4a6dffcc2'
IMAGE_BASE = 0x400000
HOOK = 0x9E3EFB
ENTRY = 0xCBF000
CHILD_COUNT = 0xA424D4


def layout_code() -> bytes:
    c = Code(ENTRY)
    c.emit('9c60 89c5')  # Preserve the location menu and original count-call inputs.
    c.base()
    c.emit('8b93'); c.word(0xACF044 - IMAGE_BASE)  # Shop control.
    c.emit('85d2'); c.branch('0f84', 'count')
    c.emit('8b83'); c.word(0xAC5D58 - IMAGE_BASE)
    c.emit('833811'); c.branch('0f85', 'hide')
    c.emit('8b83'); c.word(0xAC63BC - IMAGE_BASE)
    c.emit('8b00 8b4040 80b83902000000'); c.branch('0f84', 'hide')
    c.emit('c6424901 c6424a01')

    # Move the existing control after Training before the launcher lays out the menu.
    c.emit('8b83'); c.word(0xACF058 - IMAGE_BASE)  # Training control.
    c.emit('8b752c 8b4e08 8b7604 31ff')  # Child count, array and earlier Shop slot.
    c.label('scan')
    c.emit('85c9'); c.branch('0f84', 'count')
    c.emit('3906'); c.branch('0f84', 'training')
    c.emit('3916 0f44fe 83c604 49'); c.branch('e9', 'scan')
    c.label('training')
    c.emit('85ff'); c.branch('0f84', 'count')  # Already ordered on later refreshes.
    c.emit('8d4704')
    c.label('shift')
    c.emit('8b08 890f 39f0'); c.branch('0f84', 'place')
    c.emit('89c7 83c004'); c.branch('e9', 'shift')
    c.label('place')
    c.emit('8916'); c.branch('e9', 'count')
    c.label('hide')
    c.emit('c6424900 c6424a00')
    c.label('count')
    c.emit('619d'); c.jump(CHILD_COUNT)
    return c.finish(0x100)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.18.1 Silver')
    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        hook = pe.get_offset_from_rva(HOOK - IMAGE_BASE)
        entry = pe.get_offset_from_rva(ENTRY - IMAGE_BASE)
        original = b'\xe8' + struct.pack('<i', CHILD_COUNT - HOOK - 5)
        code = layout_code()
        section = pe.get_section_by_rva(ENTRY - IMAGE_BASE)
        if (section is None or not section.IMAGE_SCN_MEM_EXECUTE
                or entry + len(code) > section.PointerToRawData + section.SizeOfRawData):
            raise ValueError('Shooting Range layout requires executable Silver padding')
        if source[hook:hook + 5] != original or any(source[entry:entry + len(code)]):
            raise ValueError('Unexpected layout call or occupied Silver padding')
        result[entry:entry + len(code)] = code
        result[hook:hook + 5] = b'\xe8' + struct.pack('<i', ENTRY - HOOK - 5)
    return bytes(result)
