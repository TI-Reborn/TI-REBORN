"""Project the server's role into the three existing player-list moderation items."""
from hashlib import sha256
import struct

import pefile

from tio.protocol.system_message import MODERATION_ROLE_DISABLED, MODERATION_ROLE_ENABLED
from .client_equipment_batch import Code

SOURCE_SHA = '70647b21fc26ffdcdedc4ef27a79bab4dc6c6e8c255a3980c2386bce44495cfb'
BASE = 0x400000
ROLE_PACKET = 0xCEAA00
ROLE_RESET = 0xCEAA60
PLAYER_MENU = 0xCEAAB0
MINUTE_LABEL = 0xCEAB00
ROLE = 0xCEAB20


def blocks() -> tuple[tuple[int, bytes], ...]:
    dispatcher = Code(ROLE_PACKET)
    dispatcher.emit('8b45f4 2d')
    dispatcher.word(MODERATION_ROLE_DISABLED)
    dispatcher.emit('3d')
    dispatcher.word(MODERATION_ROLE_ENABLED - MODERATION_ROLE_DISABLED)
    dispatcher.branch('0f87', 'original')
    base = dispatcher.address + len(dispatcher.data) + 5
    dispatcher.call(base)
    dispatcher.emit('5a 8882')
    dispatcher.word(ROLE - base)
    dispatcher.jump(0x7D3E0B)
    dispatcher.label('original')
    dispatcher.emit('33c0')
    dispatcher.call(0x9DC760)
    dispatcher.jump(0x7D1D98)

    reset = Code(ROLE_RESET)
    reset.emit('8945fc')
    base = reset.address + len(reset.data) + 5
    reset.call(base)
    reset.emit('58 c680')
    reset.word(ROLE - base)
    reset.emit('00 33c0')
    reset.jump(0x87D8B5)

    menu = Code(PLAYER_MENU)
    base = menu.address + 5
    menu.call(base)
    menu.emit('5a 8a92')
    menu.word(ROLE - base)
    for offset in (0x3B4, 0x3EC, 0x45C):
        menu.emit('8890')
        menu.word(offset)
    menu.emit('c6802404000000')  # Keep Force Rename hidden.
    menu.jump(0xA04F2B)

    # The original window sends minutes. Mark that field so old manual jail commands
    # (online seconds) keep their existing meaning.
    marker = struct.pack('<HHiI', 1200, 2, -1, 2) + ' m\0'.encode('utf-16le')
    return ((ROLE_PACKET, dispatcher.finish(0x60)), (ROLE_RESET, reset.finish(0x50)),
            (PLAYER_MENU, menu.finish(0x50)), (MINUTE_LABEL, marker), (ROLE, b'\0'))


def sites() -> tuple[tuple[int, bytes, bytes], ...]:
    menu_before = bytes.fromhex(
        'c680b403000000 8b068bd3e8aea30300 8b8058030000'
        'c680ec03000000 8b068bd3e898a30300 8b8058030000'
        'c6805c04000000 8b068bd3e882a30300 8b8058030000'
        'c6802404000000')
    hooks = ((0x7D1D91, bytes.fromhex('33c0e8c8a92000'), ROLE_PACKET),
             (0x87D8B0, bytes.fromhex('8945fc33c0'), ROLE_RESET),
             (0xA04EE2, menu_before, PLAYER_MENU))
    jumps = tuple((at, before, b'\xe9' + struct.pack('<i', target - at - 5)
                   + b'\x90' * (len(before) - 5)) for at, before, target in hooks)
    return jumps + ((0x9FFFC3, bytes.fromhex('683401a000'),
                     b'\x68' + struct.pack('<I', MINUTE_LABEL + 12)),)


def patch(source: bytes) -> bytes:
    if sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.19.1 Silver')
    output = bytearray(source)
    changes = sites() + tuple((at, bytes(len(data)), data) for at, data in blocks())
    with pefile.PE(data=source) as pe:
        for at, before, after in changes:
            offset = pe.get_offset_from_rva(at - BASE)
            if len(after) != len(before) or source[offset:offset+len(before)] != before:
                raise ValueError(f'Native moderation patch span changed at {at:#x}')
            output[offset:offset+len(after)] = after
    return bytes(output)
