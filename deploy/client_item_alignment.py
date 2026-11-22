"""Center compact item illustrations in the existing shop and battle frames."""
import hashlib
import struct

import pefile

SOURCE_SHA = '116d6e874cbade3b4a70ac129ab071e707ef4ac05a5d6ef23c023f899ede2f36'
SITE = 0xca0bf6
SHIM = 0xca0c30


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.04.1 Silver')
    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        site = pe.get_offset_from_rva(SITE-0x400000)
        shim = pe.get_offset_from_rva(SHIM-0x400000)
        if source[site:site+6] != bytes.fromhex('8b45fc8b55f8'):
            raise ValueError('Compact item renderer differs')
        if any(source[shim:shim+32]):
            raise ValueError('Compact item renderer padding is occupied')
        # Compact native frames are two pixels left of the old item origin.
        code = bytes.fromhex('8b45fc83e8028b55f8')
        code += b'\xe9'+struct.pack('<i', SITE+6-(SHIM+len(code)+5))
        result[shim:shim+len(code)] = code
        result[site:site+6] = b'\xe9'+struct.pack('<i', SHIM-SITE-5)+b'\x90'
    return bytes(result)
