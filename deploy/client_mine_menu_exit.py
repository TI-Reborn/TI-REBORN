"""Let the authoritative server decide mine exit after native confirmation."""
import hashlib
import struct

import pefile

from .client_equipment_batch import Code

SOURCE_SHA = '62654c810380d5bab5f3908525202c8d7573e05f6251eff3814d9216149953ae'
HOOK = 0x9c1e00
ENTRY = 0xc21540


def exit_gate() -> bytes:
    c = Code(ENTRY)
    c.emit('e800000000 58 2d')
    c.word(ENTRY + 5 - 0x400000)
    c.emit('8b80')
    c.word(0xac6590 - 0x400000)
    c.emit('803800')
    c.branch('0f84', 'original')
    # B20A marks mining; B216 and the server enforce drill/raider exit rules.
    c.emit('b001 c3')
    c.label('original')
    c.jump(0x95dc30)
    return c.finish(0x40)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.17.2 Silver')
    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        offset = pe.get_offset_from_rva(ENTRY - 0x400000)
        code = exit_gate()
        if any(source[offset:offset + len(code)]):
            raise ValueError('Mine exit gate padding is occupied')
        result[offset:offset + len(code)] = code
        offset = pe.get_offset_from_rva(HOOK - 0x400000)
        before = b'\xe8' + struct.pack('<i', 0x95dc30 - HOOK - 5)
        if source[offset:offset + 5] != before:
            raise ValueError('Native quit confirmation hook changed')
        result[offset:offset + 5] = b'\xe8' + struct.pack('<i', ENTRY - HOOK - 5)
    return bytes(result)
