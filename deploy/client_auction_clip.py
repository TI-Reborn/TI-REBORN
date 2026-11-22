"""Apply UI scale to all three paths through Silver's native clip stack."""
from hashlib import sha256
import struct

import pefile

from .client_ui_scale import CLIP, IMAGE_BASE, Code, call_bytes, clip_code, guard_render, scale_clip_arguments

SOURCE_SHA = '70647b21fc26ffdcdedc4ef27a79bab4dc6c6e8c255a3980c2386bce44495cfb'
NATIVE_CALLBACK = bytes.fromhex('a1045fac008b00ffd0')
SITES = (
    (0x4f2ec7, bytes.fromhex('e9342e730090909090')),
    (0x4f2e07, NATIVE_CALLBACK),
    (0x4f2ea6, NATIVE_CALLBACK),
)


def patch(source: bytes) -> bytes:
    if sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Auction clip patch requires client 2026.11.19.2')

    code = Code(CLIP)
    code.emit('9c60')
    code.base()
    guard_render(code, 'done')
    scale_clip_arguments(code, 40)
    code.label('done')
    code.emit('619d 53')
    code.base()
    code.emit('8b83')
    code.word(0x6c5f04)
    # Tail-call the stdcall renderer so it consumes the original four arguments.
    code.emit('5b 8b00 ffe0')

    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        edits = [(address, old, call_bytes(address, CLIP) + b'\x90' * 4)
                 for address, old in SITES]
        edits.append((CLIP, clip_code(), code.finish(0x200)))
        for address, before, after in edits:
            offset = pe.get_offset_from_rva(address - IMAGE_BASE)
            if source[offset:offset+len(before)] != before or len(before) != len(after):
                raise ValueError(f'Auction clip byte guard failed at {address:#x}')
            result[offset:offset+len(before)] = after

        pending = {address + 1 - IMAGE_BASE for address, _ in SITES[1:]}
        for block in pe.DIRECTORY_ENTRY_BASERELOC:
            for entry in block.entries:
                if entry.rva in pending and entry.type == 3:
                    struct.pack_into('<H', result, entry.struct.get_file_offset(), entry.rva & 0xfff)
                    pending.remove(entry.rva)
        if pending:
            raise ValueError('Auction clip callback relocations are missing')
    return bytes(result)
