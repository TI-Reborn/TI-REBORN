"""Bounded fixes against the exact published November 3 client."""
import hashlib
import struct

import pefile
from .client_equipment_batch import Code

SOURCE_SHA = '617620e4bb082096794f644ffc975c1e7342327a5e8a94ce27d0c2532f3b1c3c'
PORTRAIT = 0xcc3300


def portrait_code() -> bytes:
    """Use the native avatar renderer, preserving the silhouette fallback."""
    c = Code(PORTRAIT)
    c.emit('8b7df4 8b8fdc600000 85c9')
    c.branch('0f84', 'silhouette')
    c.emit('6a00 6aff 8b45fc 83c00a 8b55f8 83c20a')
    c.call(0x6b0250)
    c.jump(0xcc11ca)
    c.label('silhouette')
    c.emit('8b87f85f0000 85c0')
    c.branch('0f84', 'done')
    c.emit('8b4030 50 6a00 8b55fc 83c216 8b4df8 83c10a 8b83fc5b6c00')
    c.call(0x674e38)
    c.label('done')
    c.jump(0xcc11ca)
    return c.finish(0x100)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.03.1 Silver')
    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        # Native gallery 6B0700 and battle portraits read actor+60DC.
        changes = (
            (0xc800aa, '898578020000', '8985dc600000'),
            # A2 reuses shop_admin; its original event subscriber opens bonds.
            (0x9778b3, 'e888d60d00', '9090909090'),
        )
        for address, before, after in changes:
            before, after = bytes.fromhex(before), bytes.fromhex(after)
            offset = pe.get_offset_from_rva(address-0x400000)
            if source[offset:offset+len(before)] != before or len(before) != len(after):
                raise ValueError('Native player-feedback patch span changed')
            result[offset:offset+len(after)] = after
        offset = pe.get_offset_from_rva(PORTRAIT-0x400000)
        if any(source[offset:offset+0x100]):
            raise ValueError('Roster portrait padding is occupied')
        result[offset:offset+0x100] = portrait_code()
        offset = pe.get_offset_from_rva(0xcc1197-0x400000)
        if source[offset:offset+9] != bytes.fromhex('8b7df48b87f85f0000'):
            raise ValueError('Roster portrait hook changed')
        result[offset:offset+9] = b'\xe9'+struct.pack('<i', PORTRAIT-0xcc119c)+b'\x90'*4
        from .client_live_loot import blocks, sites
        for address, code in blocks():
            offset = pe.get_offset_from_rva(address-0x400000)
            if any(source[offset:offset+len(code)]):
                raise ValueError('Live loot padding is occupied')
            result[offset:offset+len(code)] = code
        for address, before, after in sites():
            offset = pe.get_offset_from_rva(address-0x400000)
            if source[offset:offset+len(before)] != before:
                raise ValueError('Live loot native hook changed')
            result[offset:offset+len(after)] = after
    return bytes(result)
