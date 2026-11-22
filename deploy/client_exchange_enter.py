"""Route Enter in battle exchange's quantity modal to its original OK action."""
import hashlib
import struct

import pefile

from .client_equipment_batch import Code
from .client_inventory_hotkey import KEY_DISPATCH, SHORTCUT

SOURCE_SHA = '2db52da0527c2131d29fd1b356f630fd6dabb5da2238ad016f18bdbb11320f53'
ENTRY = 0xcc4200


def code() -> bytes:
    c = Code(ENTRY)
    c.emit('9c60 6683ff0d')
    c.branch('0f85', 'stock')
    c.base()
    c.emit('8b83'); c.word(0x6c64a0)
    c.emit('803800'); c.branch('0f84', 'stock')
    c.emit('8b83'); c.word(0x6c5f18)
    c.emit('803801'); c.branch('0f85', 'stock')
    c.emit('80bb'); c.word(0x6d0d78); c.emit('00')
    c.branch('0f85', 'stock')
    c.emit('8b83'); c.word(0x6c622c); c.emit('8b00')
    c.emit('8d93'); c.word(0x594a74)
    c.call(0xa3fca8)
    c.emit('83f8ff'); c.branch('0f84', 'stock')
    c.emit('89c2 8b83'); c.word(0x6c622c); c.emit('8b00')
    c.call(0xa3f2a0)
    c.emit('80784900'); c.branch('0f84', 'stock')
    c.call(0x993da0)
    c.emit('619d'); c.jump(0x9f5153)
    c.label('stock'); c.emit('619d'); c.jump(SHORTCUT)
    return c.finish(0x200)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected inspected 2026.11.16.2 Silver')
    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        for address, before, after in (
            (KEY_DISPATCH, b'\xe9' + struct.pack('<i', SHORTCUT-KEY_DISPATCH-5),
             b'\xe9' + struct.pack('<i', ENTRY-KEY_DISPATCH-5)),
            (ENTRY, bytes(0x200), code()),
        ):
            offset = pe.get_offset_from_rva(address-0x400000)
            if source[offset:offset+len(before)] != before:
                raise ValueError('Exchange Enter patch span changed')
            result[offset:offset+len(before)] = after
    from tools.build_launcher_silver_regions import require_compatible
    require_compatible(bytes(result))
    return bytes(result)
