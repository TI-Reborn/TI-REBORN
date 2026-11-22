"""Bound the native battle-card portrait while retaining gallery cache/loading."""
import hashlib
import struct

import pefile
from .client_equipment_batch import Code

SOURCE_SHA = 'b81afd23cc0c11d4b8a2e8d6f668d4d73c5784dff4664411dc8ba687f0e76075'
DRAW = 0xcc3a00
HOOK = 0x6b02e7


def draw_code(callers: tuple[int, ...] = (0x8d0b58,)) -> bytes:
    c = Code(DRAW)
    c.emit('53'); c.base()
    # The caller identifies the bounded card, independently of the avatar ID.
    previous = 0x400000
    for caller in callers[:-1]:
        c.emit('8d9b'); c.word(caller-previous)
        c.emit('395d04'); c.branch('0f84', 'matched')
        previous = caller
    c.emit('8d9b'); c.word(callers[-1]-previous)
    c.emit('395d04 5b'); c.branch('0f85', 'stock')
    if len(callers)>1:
        c.branch('e9', 'scaled')
        c.label('matched'); c.emit('5b')
        c.label('scaled')
    c.emit('55 89e5 83ec08 d9450c db5dfc d94508 db5df8')
    c.emit('6a28 6a28 6a00 6a00 8b55fc 8b4df8')
    c.call(0x4f28d4)
    c.emit('89ec 5d c20800')
    c.label('stock'); c.jump(0x4f2788)
    return c.finish(0x100)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.04.2 Silver')
    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        offset = pe.get_offset_from_rva(DRAW-0x400000)
        code = draw_code()
        if any(source[offset:offset+len(code)]):
            raise ValueError('Portrait drawing padding is occupied')
        result[offset:offset+len(code)] = code
        offset = pe.get_offset_from_rva(HOOK-0x400000)
        before = b'\xe8'+struct.pack('<i', 0x4f2788-HOOK-5)
        if source[offset:offset+5] != before:
            raise ValueError('Native avatar cache drawing call changed')
        result[offset:offset+5] = b'\xe8'+struct.pack('<i', DRAW-HOOK-5)
    return bytes(result)
