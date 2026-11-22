"""Send the native empty 40 when the player closes a battle container."""
import hashlib

import pefile

from .client_equipment_batch import Code
from .client_live_loot import STATE

SOURCE_SHA = 'ec81e07267d5f9c8784b3f1fca6eae2f21303139a94f70ee66effe3b0d4c36e1'
EMPTY_BRANCH = 0x9dcf53
CLOSE = 0xcc3b00


def close_code() -> bytes:
    code = Code(CLOSE)
    code.branch('0f8f', 'changes')
    code.emit('53')
    code.base()
    # State 2 means the per-frame commit is still collecting changes.
    code.emit('80bb'); code.word(STATE); code.emit('02')
    code.branch('0f84', 'skip')
    code.emit('80bb'); code.word(0x6c4c64); code.emit('00')
    code.branch('0f85', 'skip')
    code.emit('83bb'); code.word(0x6c4c5c); code.emit('00')
    code.branch('0f84', 'skip')
    code.emit('5b')
    code.jump(0x9dcf6c)
    code.label('skip')
    code.emit('5b')
    code.jump(0x9dd012)
    code.label('changes')
    code.jump(0x9dcf59)
    return code.finish(0x100)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.13.1 Silver')
    branch = Code(EMPTY_BRANCH)
    branch.jump(CLOSE)
    branch.emit('90')
    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        for address, expected, replacement in (
            (EMPTY_BRANCH, bytes.fromhex('0f8eb9000000'), branch.finish(6)),
            (CLOSE, bytes(0x100), close_code()),
        ):
            offset = pe.get_offset_from_rva(address-0x400000)
            if source[offset:offset+len(expected)] != expected:
                raise ValueError('Native crate close span changed')
            result[offset:offset+len(expected)] = replacement
    return bytes(result)
