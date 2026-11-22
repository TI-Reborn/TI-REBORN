"""Two bounded presentation fixes against the published November 2 Silver.

The emulator uses F0/117 only to open a city, never to reject travel. Catalogue
reads use the same ordered game connection as the pending operation; purchase
builders and the authoritative server checks keep their existing guards.
"""
import hashlib
import struct

import pefile

SOURCE_SHA = '076bc1c789f2e3ab086b359f376d13fc7b1661307d44dc821604bb4dd39d94be'


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.02.2 Silver')
    pe = pefile.PE(data=source)
    result = bytearray(source)
    # shortcut: F0/117 is city-open only; use a distinct command before adding native level denials.
    city = (b'\xe8' + struct.pack('<i', 0x8596e0-0x7d26e7)
            + b'\xe9' + struct.pack('<i', 0x7d3e0b-0x7d26ec) + b'\x90'*7)
    changes = (
        (0x7d26e2, bytes.fromhex('55e868ecffff59e8f26f0800e966160000'), city),
        (0x99194e, bytes.fromhex('752b'), b'\x90\x90'),
    )
    for address, before, after in changes:
        offset = pe.get_offset_from_rva(address-0x400000)
        if source[offset:offset+len(before)] != before or len(before) != len(after):
            raise ValueError('Native city/shop guard changed')
        result[offset:offset+len(after)] = after
    return bytes(result)
