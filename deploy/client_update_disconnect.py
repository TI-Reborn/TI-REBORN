"""Add a server update reason to the native disconnect dialog."""
from hashlib import sha256
import struct

import pefile

from tio.protocol.transport import UPDATE_DISCONNECT_REASON
from .client_equipment_batch import Code

SOURCE_SHA = '06ddb77a8866b6d503d768e8fbafa0c1d5c729ca037e74ad7bf258deb5f85444'
HOOK = 0x87B5C0
CODE = 0xCEA800
MESSAGE = 'Server update'


def patch(source: bytes) -> bytes:
    if sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.18.7 Silver')

    code = Code(CODE)
    code.emit('81fb')
    code.word(UPDATE_DISCONNECT_REASON)
    code.branch('0f85', 'original')
    code.emit('8d45fc')
    return_address = CODE + len(code.data) + 5
    code.call(return_address)
    code.emit('5a 81c2')
    code.word(CODE + 0x40 + 12 - return_address)
    code.call(0x40B4C4)  # Assign the Delphi UnicodeString to the reason label.
    code.jump(0x87B5E6)
    code.label('original')
    code.emit('83ebfd')
    code.branch('0f84', 'ordered')
    code.jump(0x87B5C5)
    code.label('ordered')
    code.jump(0x87B5D9)
    message = struct.pack('<HHiI', 1200, 2, -1, len(MESSAGE))
    message += (MESSAGE + '\0').encode('utf-16le')
    block = code.finish(0x40) + message

    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        hook = pe.get_offset_from_rva(HOOK - 0x400000)
        cave = pe.get_offset_from_rva(CODE - 0x400000)
        if source[hook:hook + 5] != bytes.fromhex('83ebfd7414'):
            raise ValueError('Native disconnect reason branch changed')
        if source[cave:cave + len(block)] != bytes(len(block)):
            raise ValueError('Native disconnect code space is occupied')
        result[hook:hook + 5] = b'\xe9' + struct.pack('<i', CODE - HOOK - 5)
        result[cave:cave + len(block)] = block
    return bytes(result)
