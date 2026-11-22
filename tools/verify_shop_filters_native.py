"""Execute the ordinary shop's filter hooks at the preferred and relocated bases."""
import argparse
from pathlib import Path
import struct

import pefile
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EIP, UC_X86_REG_EDX,
    UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_ESP,
)

from verify_auth_native import DATA, STACK, get32, put32, return_from_stub
from deploy.client_shop_filters import BASE, CAPTIONS, ITEM_HOOK, OPEN_HOOK, VISIBLE

FILTER, ITEM, ROWS, METADATA = (DATA + offset for offset in (0x100, 0x400, 0x500, 0x3000))
GROUPS = (16, 21, 3, 18, 2, 15, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 19, 17, 1)

# Template, client type, weapon class, body part, expected visible groups.
CASES = (
    (3, 8, 1, 0, {17}),
    (9, 2, 1, 0, {15}),
    (17, 1, 1, 0, {19}),
    (24, 12, 1, 0, {19}),
    (129, 13, 1, 0, {19}),
    (206, 9, 1, 5, {4, 7}),
    (211, 9, 1, 3, {4, 5}),
    (226, 9, 1, 5, {4, 7}),
    (252, 9, 1, 1, {4, 6}),
    (301, 1, 3, 0, {8, 10}),
    (334, 9, 7, 1, {4, 6}),
    (5001, 1, 7, 0, {8, 14}),
    (5002, 2, 1, 0, {19}),
    (5003, 2, 1, 0, {18}),
    (5011, 2, 1, 0, {18}),
    (5012, 2, 1, 0, {15}),
    (6100, 23, 1, 0, {2}),
    (6120, 24, 1, 0, {2}),
    (6121, 26, 1, 0, {2}),
    (6122, 25, 1, 0, {2}),
    (6123, 1, 1, 0, {2}),
)


def verify(binary: bytes, base: int) -> int:
    with pefile.PE(data=binary) as pe:
        image = pe.get_memory_mapped_image(ImageBase=base)
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(base, (len(image) + 0xfff) & ~0xfff)
    u.mem_write(base, image)
    u.mem_map(DATA, 0x10000)
    u.mem_map(STACK, 0x10000)
    delta = base - BASE
    put32(u, 0xac637c + delta, DATA)
    put32(u, DATA, METADATA)
    put32(u, FILTER + 0x280, ROWS)
    put32(u, ROWS - 4, len(GROUPS))
    rows = [DATA + 0x1000 + index * 0x30 for index in range(len(GROUPS))]
    for index, (address, group) in enumerate(zip(rows, GROUPS)):
        put32(u, ROWS + index * 4, address)
        u.mem_write(address + 0x1a, bytes([group]))

    def hook(uc, address, size, _):
        if address == 0x40b47c + delta:
            # Managed string assignment is the only stub in the UI setup.
            put32(uc, uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_EDX))
            return_from_stub(uc)
        elif address == 0x8e2e68 + delta:
            assert uc.reg_read(UC_X86_REG_EAX) == FILTER
            assert uc.reg_read(UC_X86_REG_EDX) == ITEM
            uc.reg_write(UC_X86_REG_EAX, 1)
            return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE, hook)

    def invoke(site: int, esi: int) -> int:
        preserved = {UC_X86_REG_EBX: 0xcafe, UC_X86_REG_ESI: esi, UC_X86_REG_EDI: 0xfade}
        for register, value in preserved.items():
            u.reg_write(register, value)
        u.reg_write(UC_X86_REG_EAX, FILTER)
        u.reg_write(UC_X86_REG_EDX, ITEM)
        u.reg_write(UC_X86_REG_ESP, STACK + 0x8000)
        end = site + delta + 5
        u.emu_start(site + delta, end, count=10000)
        assert u.reg_read(UC_X86_REG_EIP) == end
        assert u.reg_read(UC_X86_REG_ESP) == STACK + 0x8000
        assert all(u.reg_read(register) == value for register, value in preserved.items())
        return u.reg_read(UC_X86_REG_EAX) & 255

    for starter, locale_index in (('Armor', 1), ('Обмундирование', 2)):
        u.mem_write(DATA + 0x2000, starter.encode('utf-16le'))
        put32(u, rows[6] + 0x14, DATA + 0x2000)
        for _ in range(2):  # Opening again uses the already replaced caption.
            invoke(OPEN_HOOK, 0xbabe)
            assert all(u.mem_read(row + 8, 1)[0] == bool(VISIBLE & (1 << group))
                       for row, group in zip(rows, GROUPS))
            for caption in CAPTIONS:
                address = get32(u, rows[caption[0]] + 0x14)
                size = get32(u, address - 4) * 2
                assert u.mem_read(address, size).decode('utf-16le') == caption[locale_index]

    group_filters = {2, *range(4, 16), 17, 18, 19}
    for template, kind, weapon, part, groups in CASES:
        put32(u, ITEM + 8, template)
        index = 1
        metadata = METADATA + 0x3a78 * index
        u.mem_write(metadata + 0x118, struct.pack('<H', kind))
        u.mem_write(metadata + 0x120, struct.pack('<H', weapon))
        u.mem_write(metadata + 0x12d, bytes([part]))
        for group in (*sorted(group_filters), 1, 20):
            u.mem_write(FILTER + 0x284, bytes([group]))
            expected = group in groups or group in (1, 20)
            assert invoke(ITEM_HOOK, index) == expected, (hex(base), template, group)
    return len(CASES) * (len(group_filters) + 2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('silver', type=Path)
    args = parser.parse_args()
    binary = args.silver.read_bytes()
    total = sum(verify(binary, base) for base in (BASE, 0x1000000))
    print(f'{total} native filter matches, masks and bilingual captions at two image bases passed')
