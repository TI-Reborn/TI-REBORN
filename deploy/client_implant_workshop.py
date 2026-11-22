"""Keep the native workshop selector in sync with owned item instances."""
import hashlib
import struct

import pefile

from .client_equipment_batch import Code

SOURCE_SHA = '5ad4cbf596585b9efe9f18965e0d8e807aa026ac88c17c2748751ac4272ad58e'
FIRST_FIX_SHA = '943a73f04e55367a2712c8bd3e5c9542edf799af9d63d13c197207c772cfff97'
HOOK = 0x7b864a
APPEND = 0x7b8650
CLEANUP = 0x7b86bc
SELECTOR = 0xcd8500
LOAD_ITEMS = bytes.fromhex('8b83c8020000')
SHARED_ROW_HOOK = 0x7b89d9
STOCK_SELECTOR = 0x7b86f0
ACTOR_LOOKUP = 0xa93f70
FRESHNESS = 0xcd8580


def selector_code() -> bytes:
    code = Code(SELECTOR)
    # Both the shared list and the selected fighter can supply the same item.
    code.emit(LOAD_ITEMS.hex() + ' 85c0')
    code.branch('0f84', 'append')
    code.emit('8b48fc 8b9598fdffff 83c028')
    code.label('next')
    code.emit('85c9')
    code.branch('0f84', 'append')
    code.emit('3910')
    code.branch('0f84', 'duplicate')
    code.emit('0590020000 49')
    code.branch('e9', 'next')
    code.label('duplicate')
    code.jump(CLEANUP)
    code.label('append')
    code.emit(LOAD_ITEMS.hex())
    code.jump(APPEND)
    return code.finish(0x60)


def freshness_code() -> bytes:
    code = Code(FRESHNESS)
    # The shared list still has the pre-craft items when the result reopens the selector.
    code.emit('50 80b88002000005')
    code.branch('0f85', 'show')
    code.emit('8b8084020000 85c0')
    code.branch('0f84', 'show')
    code.call(ACTOR_LOOKUP)
    code.emit('83f81f')
    code.branch('0f83', 'show')
    code.emit('53')
    code.base()
    code.emit('8b938c616c00 5b 8b0482 85c0')
    code.branch('0f84', 'show')
    code.emit('8b406c 85c0')
    code.branch('0f84', 'hide')
    code.emit('8b48fc 8b1424 8b5228 83c028')
    code.label('next')
    code.emit('85c9')
    code.branch('0f8e', 'hide')
    code.emit('3910')
    code.branch('0f84', 'current')
    code.emit('0590020000 49')
    code.branch('e9', 'next')
    code.label('current')
    code.emit('83e828 83c404')
    code.jump(STOCK_SELECTOR)
    code.label('hide')
    code.emit('58 c3')
    code.label('show')
    code.emit('58')
    code.jump(STOCK_SELECTOR)
    return code.finish(0xa0)


def edits(source_sha: str) -> tuple[tuple[int, bytes, bytes], ...]:
    if source_sha not in (SOURCE_SHA, FIRST_FIX_SHA):
        raise ValueError('Unexpected workshop client source')
    freshness = freshness_code()
    result = (
        (SHARED_ROW_HOOK, bytes.fromhex('e812fdffff'),
         b'\xe8' + struct.pack('<i', FRESHNESS - SHARED_ROW_HOOK - 5)),
        (FRESHNESS, bytes(len(freshness)), freshness),
    )
    if source_sha == FIRST_FIX_SHA:
        return result
    selector = selector_code()
    return result + (
        (HOOK, LOAD_ITEMS, b'\xe9' + struct.pack('<i', SELECTOR - HOOK - 5) + b'\x90'),
        (SELECTOR, bytes(len(selector)), selector),
    )


def patch(source: bytes) -> bytes:
    changes = edits(hashlib.sha256(source).hexdigest())
    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        for address, before, after in changes:
            offset = pe.get_offset_from_rva(address - 0x400000)
            if source[offset:offset + len(before)] != before:
                raise ValueError('Native workshop selector region changed')
            result[offset:offset + len(after)] = after
    return bytes(result)
