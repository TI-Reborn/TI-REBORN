"""Use the ordinary shop control in the published trading menu."""
from hashlib import sha256

import pefile


SOURCE_SHA = '3e3e552b40e35d5c4b48e3255814e582545b5714eca60c84d4337e170b799999'

CHANGES = (
    # Skip the Premium control constructor, leaving the ordinary button in
    # its slot. Two short branches leave the native relocation operands intact.
    (0x977AE6, '568b', 'eb78'),
    (0x977B60, '8d83', 'eb27'),
    # Preserve the auction's zone checks. The shop uses the zone's shop flag.
    (0x9754C7, '0fb6803e0200008845fa', '0fb680390200008845fa'),
    (0x975584, 'b2018bc68b08ff1184db7506807dfa00740833d28bc68b08ff11',
     '8a55fa8bc68b08ff11' + '90' * 17),
    # Native purchase and sale writers still read this gate in mines and bases.
    (0x975814, '84db7410', '807dfa01'),
    (0x975825, 'c60001', '0f9200'),
)


def patch(source: bytes) -> bytes:
    if sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.05.2 Silver')
    result = bytearray(source)
    with pefile.PE(data=source) as image:
        for address, before_hex, after_hex in CHANGES:
            before, after = bytes.fromhex(before_hex), bytes.fromhex(after_hex)
            offset = image.get_offset_from_rva(address - image.OPTIONAL_HEADER.ImageBase)
            if source[offset:offset + len(before)] != before or len(before) != len(after):
                raise ValueError('Native trading menu bytes changed')
            result[offset:offset + len(after)] = after
    return bytes(result)
