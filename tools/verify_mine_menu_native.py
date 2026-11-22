"""Execute the native quit-confirmation callback and numeric packet writers.

UI closing, Delphi string cleanup and transport flush are explicit stubs.
This verifies machine code, not a rendered menu or a live network session.
"""
import argparse
import json
import struct
from pathlib import Path

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP

from verify_auth_native import DATA, STACK, STOP, get32, put32, return_from_stub


def confirm(raw: bytes, *, mining: bool, border: bool = False,
            blocked: bool = False, base: int = 0x400000) -> list[str]:
    """Return packets flushed by the actual confirmation callback at 9C1DA0."""
    delta = base - 0x400000
    with pefile.PE(data=raw) as pe:
        pe.relocate_image(base)
        image = pe.get_memory_mapped_image()
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(0, 0x1000)
    u.mem_map(base, (len(image) + 0xfff) & ~0xfff)
    u.mem_write(base, image)
    u.mem_map(DATA, 0x10000)
    u.mem_map(STACK, 0x10000)
    put32(u, STACK + 0x8000, STOP)
    u.reg_write(UC_X86_REG_ESP, STACK + 0x8000)
    battle, flags, actors, actor = DATA + 0x500, DATA + 0x600, DATA + 0x800, DATA + 0x4000
    for address, value in ((0xac6008, battle), (0xac5ae0, flags),
                           (0xac6590, flags + 1), (0xac5834, flags + 2),
                           (0xac63b4, flags + 3), (0xac618c, actors),
                           (0xac561c, flags + 4), (0xac5494, flags + 8)):
        put32(u, address + delta, value)
    u.mem_write(flags, bytes((0, mining, blocked, 0)))
    put32(u, flags + 4, 60)
    put32(u, flags + 8, 60)
    u.mem_write(battle + 0x28, b'\x01')
    u.mem_write(0xac4b25 + delta, b'\x00')
    put32(u, actors, actor)
    u.mem_write(actor + 0x41, b'\x01')
    u.mem_write(actor + 0x6006, struct.pack('<h', 100))
    put32(u, actor + 0x603c, 1 if border else 35)
    put32(u, actor + 0x6040, 5)
    obj, handle, vtable, flush = DATA + 0x1000, DATA + 0x3000, DATA + 0x3100, DATA + 0x3200
    put32(u, handle, obj)
    put32(u, obj, vtable)
    put32(u, vtable, flush)
    put32(u, 0xac600c + delta, handle)
    packets = []

    def hook(uc: Uc, address: int, size: int, user: object) -> None:
        if address == 0x6748b0 + delta:
            uc.reg_write(UC_X86_REG_EAX, handle)
            return_from_stub(uc)
        elif address == flush:
            packets.append(bytes(uc.mem_read(obj + 4, get32(uc, obj + 0x1004))).hex())
            return_from_stub(uc)
        elif address in (0x40b180 + delta, 0x40b09c + delta, 0xa6a114 + delta):
            return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE, hook)
    u.emu_start(0x9c1da0 + delta, STOP, count=10000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP, 'Native callback did not return'
    return packets


def verify(raw: bytes) -> list[dict]:
    cases = []
    for base in (0x400000, 0x12000000):
        for mining, border, blocked, expected in (
            (True, False, False, ['2a01']),
            (True, True, False, ['2a01']),
            (False, False, False, []),
            (False, True, False, ['2a01']),
            (True, False, True, []),
        ):
            actual = confirm(raw, mining=mining, border=border, blocked=blocked, base=base)
            case = dict(base=hex(base), mining=mining, border=border, blocked=blocked, packets=actual)
            assert actual == expected, (case, expected)
            cases.append(case)
    return cases


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    args = parser.parse_args()
    print(json.dumps(dict(passed=True, cases=verify(args.binary.read_bytes())), indent=2))
