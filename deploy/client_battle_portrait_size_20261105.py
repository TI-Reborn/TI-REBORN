"""Include the observed native battle HUD in the bounded portrait draw."""
import hashlib

import pefile
from .client_portrait_size_20261105 import DRAW, draw_code

SOURCE_SHA = '1d4f1c8cd64a3f2e21324964c00be16e1ff39ba12e858b3cf11f9ca7a11a5a58'


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.05.1 Silver')
    with pefile.PE(data=source) as pe:
        offset = pe.get_offset_from_rva(DRAW-0x400000)
    before = draw_code()
    if source[offset:offset+len(before)] != before:
        raise ValueError('Native bounded avatar draw changed')
    result = bytearray(source)
    result[offset:offset+len(before)] = draw_code((0x8d0b58, 0x9daae5))
    return bytes(result)
