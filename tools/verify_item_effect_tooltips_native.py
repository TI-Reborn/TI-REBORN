"""Execute the published/candidate medkit tooltip paths in synthetic fixtures.

Metadata lookup executes original code. Localization, managed allocation/string
formatting and GUI output are isolated; this is not a rendered-client proof.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy.item_effect_descriptions import load_descriptions, language_key
DATA, STACK, STOP = (0x30000000, 0x31000000, 0x300ff000)

def run(raw: bytes, identity: int, language: str, *, base: int=0x400000) -> dict:
    pe = pefile.PE(data=raw)
    pe.relocate_image(base)
    memory = pe.get_memory_mapped_image()
    pe.close()
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(base, len(memory) + 4095 & ~4095)
    u.mem_write(base, memory)
    u.mem_map(0, 0x1000)
    u.mem_map(DATA, 0x100000)
    u.mem_map(STACK, 0x20000)
    va = lambda address: base + address - 0x400000

    def put(address, value):
        u.mem_write(address, struct.pack('<I', value & 0xffffffff))

    def get(address):
        return struct.unpack('<I', u.mem_read(address, 4))[0]
    arena = DATA + 0x20000

    def allocate(text):
        nonlocal arena
        value = arena + 12
        raw_text = text.encode('utf-16le')
        u.mem_write(arena, struct.pack('<HHii', 1200, 2, -1, len(text)) + raw_text + b'\x00\x00')
        arena = value + len(raw_text) + 6 & ~3
        return value

    def string(pointer):
        if not pointer:
            return ''
        length = get(pointer - 4)
        assert length < 2048
        return bytes(u.mem_read(pointer, length * 2)).decode('utf-16le')

    def returned(pop=0):
        sp = u.reg_read(UC_X86_REG_ESP)
        u.reg_write(UC_X86_REG_EIP, get(sp))
        u.reg_write(UC_X86_REG_ESP, sp + 4 + pop)
    templates = DATA + 0x1000
    put(va(0xac637c), DATA + 256)
    put(DATA + 256, templates)
    put(templates - 4, 1)
    put(templates, identity)
    put(va(0xaceb50) + 4, 0)
    put(va(0xaceb50) + 8, identity)
    # Three ordinary medical controls must retain the original path.
    heal = {20: 100, 33: 24, 28: 15}.get(identity, 0)
    for offset in (1616, 1620, 1624):
        put(templates + offset, heal)
    put(va(0xac580c), DATA + 0x10000)
    put(va(0xacedf0), 0)
    put(va(0xacee00), allocate('8'))
    rows = load_descriptions(ROOT)[language]
    dictionary = {language_key(i, n): text for i, lines in rows.items() for n, text in enumerate(lines)}
    dictionary.update(c026='Излечивает %s hp' if language == 'ru' else 'Heals %s hp', c013='Цена применения: %s ap' if language == 'ru' else 'Use cost: %s ap')
    # Only infrastructure/string helpers are substituted; metadata lookup executes.
    executed = []

    def hook(uc, address, size, user):
        at = address - base + 0x400000
        eax = uc.reg_read(UC_X86_REG_EAX)
        edx = uc.reg_read(UC_X86_REG_EDX)
        if at == 0x6675e0:
            key = string(eax)
            assert key in dictionary, key
            put(edx, allocate(dictionary[key]))
            returned()
        elif at == 0x40b47c:
            put(eax, edx)
            returned()
        elif at == 0x40b09c:
            put(eax, 0)
            returned()
        elif at == 0x4244b4:
            put(edx, allocate(str(eax)))
            returned()
        elif at == 0x425c3c:
            sp = uc.reg_read(UC_X86_REG_ESP)
            value = string(eax).replace('%s', string(get(edx)), 1)
            put(get(sp + 4), allocate(value))
            returned(4)
        elif at == 0x40c244:
            raise AssertionError('Unequal healing endpoints outside this fixture')
        elif at == 0x80d748:
            uc.emu_stop()
        elif at == 0xa7b030:
            executed.append(at)
    u.hook_add(UC_HOOK_CODE, hook)
    put(STACK + 0x10000, STOP)
    u.reg_write(UC_X86_REG_ESP, STACK + 0x10000)
    u.reg_write(UC_X86_REG_EBP, STACK + 0x11000)
    u.reg_write(UC_X86_REG_EBX, va(0xacedf0))
    u.emu_start(va(0x80d59a), STOP, count=20000)
    assert u.reg_read(UC_X86_REG_EIP) == va(0x80d748)
    assert u.reg_read(UC_X86_REG_ESP) == STACK + 0x10000
    assert u.reg_read(UC_X86_REG_EBX) == va(0xacedf0)
    assert u.reg_read(UC_X86_REG_EBP) == STACK + 0x11000
    count = get(va(0xacedf0))
    assert count <= 6
    actual = [string(get(DATA + 0x10000 + n * 40 + 4)) for n in range(count)]
    return dict(identity=identity, language=language, base=hex(base), lines=actual, original_lookup_calls=len(executed))

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    before, after = (args.source.read_bytes(), args.candidate.read_bytes())
    rows = load_descriptions(ROOT)
    cases = []
    for language in ('ru', 'en'):
        for base in (0x400000, 0x10400000):
            for identity, lines in rows[language].items():
                old = run(before, identity, language, base=base)
                assert '0 hp' in old['lines'][0], old
                new = run(after, identity, language, base=base)
                assert new['lines'] == list(lines), new
                assert new['original_lookup_calls'] == 0
                cases.append(new)
            for identity, heal in ((20, 100), (33, 24), (28, 15)):
                old = run(before, identity, language, base=base)
                new = run(after, identity, language, base=base)
                assert new['lines'] == old['lines'] and f'{heal} hp' in new['lines'][0]
                assert new['original_lookup_calls'] >= 1
                cases.append(new)
    report = dict(passed=True, source_sha256=hashlib.sha256(before).hexdigest(), candidate_sha256=hashlib.sha256(after).hexdigest(), cases=len(cases), details=cases, graphical_client=False)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(passed=True, cases=len(cases))))
if __name__ == '__main__':
    main()
