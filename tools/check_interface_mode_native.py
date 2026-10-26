"""Execute the built Silver layout entry for both launcher interface modes.

Research extras (pefile, unicorn) and the A2 GUI-tree fixture are local
inputs; this never starts the game or contacts a server.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import pefile
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_barracks_a2 as a2

SIZES = ((1728, 768), (1344, 544), (1516, 640), (2368, 1120), (3008, 1408), (800, 448), (1199, 900))
NATIVE_CALLS = (0xa42b04, 0xc28600)


def run_layout(image: bytes, tree: dict, base: int, width: int, height: int, mode: int) -> dict:
    pe = pefile.PE(data=image)
    pe.relocate_image(base)
    memory = pe.get_memory_mapped_image()
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(base, (len(memory)+4095) & ~4095)
    u.mem_write(base, memory)
    data, stack = 0x30000000, 0x31000000
    stop = data+0x1ff000
    u.mem_map(data, 0x200000)
    u.mem_map(stack, 0x10000)
    cursor = data+0x1000
    objects: dict[str, int] = {}

    def va(value: int) -> int:
        return base+value-0x400000

    def put(address: int, value: int) -> None:
        u.mem_write(address, struct.pack('<I', value & 0xffffffff))

    def get(address: int) -> int:
        return struct.unpack('<I', u.mem_read(address, 4))[0]

    def allocate(size: int = 0x500) -> int:
        nonlocal cursor
        result = cursor
        cursor += (size+15) & ~15
        return result

    def add(node: dict, parent: int = 0) -> int:
        pointer = allocate()
        objects[node['pointer']] = pointer
        put(pointer, va(int(node['vmt'], 16)))
        put(pointer+0x4c, parent)
        for offset, value in zip((0x30, 0x34, 0x38, 0x3c), node['rect'], strict=True):
            put(pointer+offset, value)
        children = [add(child, pointer) for child in node.get('children', []) if not child.get('unreadable')]
        vector = allocate(16+4*len(children))
        put(pointer+0x2c, vector)
        put(vector+4, vector+16)
        put(vector+8, len(children))
        for index, child in enumerate(children):
            put(vector+16+4*index, child)
        return pointer

    window = next(w for w in tree['windows'] if w and w.get('name') == 'window_squad_page')
    root = add(window)
    put(root+0x38, width)
    put(root+0x3c, height)
    for address, pointer in tree['globals'].items():
        put(va(int(address, 16)), objects[pointer])
    put(va(0x400000+a2.MODE), mode)

    def rect(pointer: int) -> tuple[int, ...]:
        return tuple(get(pointer+offset) for offset in (0x30, 0x34, 0x38, 0x3c))

    before = {name: rect(pointer) for name, pointer in objects.items()}

    def native(uc: Uc, address: int, size: int, user: object) -> None:
        if address not in tuple(va(call) for call in NATIVE_CALLS):
            return
        sp = uc.reg_read(UC_X86_REG_ESP)
        uc.reg_write(UC_X86_REG_EIP, get(sp))
        uc.reg_write(UC_X86_REG_ESP, sp+4)

    u.hook_add(UC_HOOK_CODE, native)
    saved = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
    for register, value in zip(saved, (111, 222, 333, 444), strict=True):
        u.reg_write(register, value)
    sp = stack+0xf000
    put(sp, stop)
    u.reg_write(UC_X86_REG_ESP, sp)
    u.emu_start(va(a2.LAYOUT), stop, count=200000)
    assert u.reg_read(UC_X86_REG_ESP) == sp+4
    assert [u.reg_read(register) for register in saved] == [111, 222, 333, 444]
    state = get(va(0x400000+a2.STATE))
    after = {name: rect(pointer) for name, pointer in objects.items()}
    moved = sorted(name for name in objects if before[name] != after[name])
    plan = a2.layout(width, height)
    expected_state = int(bool(plan) and mode == 0)
    assert state == expected_state, (base, width, height, mode, state)
    if expected_state:
        assert after[tree['globals']['0xad10a4']] == tuple(vars(plan['right']).values())
    else:
        assert not moved, (width, height, mode, moved[:5])
    return dict(base=hex(base), size=[width, height], mode=('original' if mode else 'new'),
                a2_layout=bool(state), controls_moved=len(moved))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('silver', type=Path)
    parser.add_argument('tree', type=Path, help='reports/barracks-a2-20261025/gui-tree.json')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    image = args.silver.read_bytes()
    tree = json.loads(args.tree.read_text(encoding='utf-8'))
    cases = [run_layout(image, tree, base, width, height, mode)
             for base in (0x400000, 0x10000000) for width, height in SIZES for mode in (0, 1)]
    proof = dict(passed=True, silver_sha256=hashlib.sha256(image).hexdigest(), cases=cases,
                 graphical_validation=False)
    args.output.write_text(json.dumps(proof, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, cases=len(cases))))


if __name__ == '__main__':
    main()
