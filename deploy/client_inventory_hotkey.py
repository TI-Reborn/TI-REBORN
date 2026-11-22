"""Confirm staged battle equipment when the inventory shortcut closes it."""
import hashlib

import pefile

from .client_equipment_batch import OK_ENTRY, WINDOW, Code

SOURCE_SHA = '3ca1d881a484403fe867dd9958cc7b3ab92569342e15d82d77f4b214663e733f'
ESCAPE_SOURCE_SHA = 'a3a63f7e097ffb272b036bbdfb4302ee67b53aff3c4aa9667b841f908193c09a'
TOGGLE_CALL = 0x9db1dc
TOGGLE = 0x9b3bd4
KEY_DISPATCH = 0x9f4f60
KEY_CONTINUE = 0x9f4f69
SHORTCUT = 0xcc3d00


def shortcut_code() -> bytes:
    code = Code(SHORTCUT)
    code.emit('9c60 6683ff1b')
    code.branch('0f84', 'inventory')
    code.emit('6683ff49')
    code.branch('0f85', 'stock')
    code.emit('66f7c60400')
    code.branch('0f85', 'stock')
    code.label('inventory')
    code.base()
    code.emit('8b93'); code.word(0x6c64a0)
    code.emit('803a00')
    code.branch('0f84', 'stock')
    code.emit('8b83'); code.word(WINDOW)
    code.emit('85c0')
    code.branch('0f84', 'stock')
    code.emit('80784900')
    code.branch('0f84', 'stock')
    code.emit('6683ff1b')
    code.branch('0f84', 'cancel')
    code.call(OK_ENTRY)
    code.branch('e9', 'handled')
    code.label('cancel')
    code.call(0xa4370c)
    code.label('handled')
    code.emit('619d')
    code.jump(0x9f5153)
    code.label('stock')
    code.emit('619d 8bce 8bd7')
    code.call(0xa3fe48)
    code.jump(KEY_CONTINUE)
    return code.finish(0x100)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.13.3 Silver')
    original = Code(TOGGLE_CALL)
    original.call(TOGGLE)
    prior = Code(TOGGLE_CALL)
    prior.call(0xcc3c00)
    hook = Code(KEY_DISPATCH)
    hook.jump(SHORTCUT)
    hook.emit('90909090')
    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        for address, expected, replacement in (
            (TOGGLE_CALL, prior.finish(5), original.finish(5)),
            (KEY_DISPATCH, bytes.fromhex('8bce8bd7e8dfae0400'), hook.finish(9)),
            (SHORTCUT, bytes(0x100), shortcut_code()),
        ):
            offset = pe.get_offset_from_rva(address-0x400000)
            if source[offset:offset+len(expected)] != expected:
                raise ValueError('Inventory shortcut span changed')
            result[offset:offset+len(expected)] = replacement
    return bytes(result)


def patch_escape(source: bytes) -> bytes:
    """Route Escape through the same inventory confirmation as I."""
    if hashlib.sha256(source).hexdigest() != ESCAPE_SOURCE_SHA:
        raise ValueError('Expected published 2026.11.13.4 Silver')
    cancel_branch = bytes.fromhex('0f840a000000')
    with pefile.PE(data=source) as pe:
        offset = pe.get_offset_from_rva(SHORTCUT+0x58-0x400000)
    end = offset+len(cancel_branch)
    if source[offset:end] != cancel_branch:
        raise ValueError('Inventory Escape branch changed')
    return source[:offset]+b'\x90'*len(cancel_branch)+source[end:]
