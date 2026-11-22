"""Use the native selected-ID writer for paid rename in Silver 2026.11.18.5."""
import hashlib
import struct

import pefile

SOURCE_SHA = '5525b27466cc28afad2391abb8dc6d1e49f5531ce9091fc030a2a831a623689a'


def _branch(opcode: bytes, address: int, target: int) -> bytes:
    return opcode + struct.pack('<i', target - (address + 5))


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published Silver 2026.11.18.5')

    # Reuse the paid-only block after its original unchanged-name check.
    # The shared writer keeps B9/05 at character selection and uses B9/06 in the world.
    # The absolute operand at 0x6d656c keeps its existing PE relocation.
    writer = (
        _branch(b'\xe9', 0x6d6563, 0x6d64e9)
        + b'\xb2\x06\x2a\x15' + struct.pack('<I', 0xac4648)
        + _branch(b'\xe8', 0x6d6570, 0x673464)
        + _branch(b'\xe9', 0x6d6575, 0x6d6507)
    )
    edits = (
        (0x6d6500, 'b205e85dcff9ff', _branch(b'\xe9', 0x6d6500, 0x6d6568) + b'\x90\x90'),
        (0x6d6563, '33c08945fc33ff8b358c61ac00833e0074328b068b80f4', writer),
    )
    result = bytearray(source)
    with pefile.PE(data=source, fast_load=True) as pe:
        for address, expected, replacement in edits:
            before = bytes.fromhex(expected)
            offset = pe.get_offset_from_rva(address - pe.OPTIONAL_HEADER.ImageBase)
            if len(before) != len(replacement) or source[offset:offset + len(before)] != before:
                raise ValueError(f'Native rename region differs at {address:#x}')
            result[offset:offset + len(before)] = replacement
    return bytes(result)
