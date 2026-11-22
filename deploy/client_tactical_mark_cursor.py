"""Keep tactical markers and their hit tests in physical battlefield pixels."""
import hashlib

import pefile

from . import client_ui_scale as scale

SOURCE_SHA = '0d774d76f4bc95d43b60e720460787d5d12f9d123613ee1716de006d02d5f324'
WRAPPER_SIZE = 0x100
CALLS = (
    (0x9c2f5b, 0x7105c8, 0xce9d00, False),  # Render marker and author inside the HUD.
    (0x9f4a6d, 0x710960, 0xce9e00, True),   # Right-click removal uses the copied mouse.
    (0x9db355, 0x710ad8, 0xce9f00, True),   # Hover hit test uses the same mouse.
)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.14.2 Silver')
    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        if pe.get_data(scale.SIGNATURE_RVA, len(scale.SIGNATURE)) != scale.SIGNATURE:
            raise ValueError('Independent UI scale runtime is missing')
        spans = []
        for site, native, wrapper, physical_mouse in CALLS:
            spans.extend((
                (site, scale.call_bytes(site, native), scale.call_bytes(site, wrapper)),
                (wrapper, bytes(WRAPPER_SIZE), scale.scoped_code(
                    wrapper, native, 0, size=WRAPPER_SIZE, cursor=physical_mouse)),
            ))
        for address, expected, replacement in spans:
            rva = address - scale.IMAGE_BASE
            if any(entry.type and rva <= entry.rva < rva + len(expected)
                   for block in pe.DIRECTORY_ENTRY_BASERELOC for entry in block.entries):
                raise ValueError(f'Tactical marker patch overlaps a relocation at {address:#x}')
            offset = pe.get_offset_from_rva(rva)
            if source[offset:offset + len(expected)] != expected:
                raise ValueError(f'Tactical marker patch guard failed at {address:#x}')
            result[offset:offset + len(expected)] = replacement
    return bytes(result)
