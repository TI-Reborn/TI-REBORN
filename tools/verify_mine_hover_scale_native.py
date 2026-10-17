"""Execute the original mine hit detector with physical and logical mice.

The native adjacency, installed/carrying flags, mouse rectangle and cursor-mode
branches execute. Selected-actor lookup, scene projection, collection iteration
and cursor API are explicit fixtures. Neither gameplay nor GUI rendering is
claimed. The actual current client bytes are mapped at two relocated bases.
"""
from __future__ import annotations

import argparse
from itertools import product
import json
from pathlib import Path
import struct
import sys

import pefile
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_mine_hover_scale as patcher
from deploy import client_ui_scale as scale
from tools.verify_client_ui_scale_native import (
    Fixture as ScaleFixture, DATA, API, STACK, END, REGS, VALUES, get, put,
)

BASELINE = ROOT / 'reports/client-ui-incident-20261010/client/silver.dll'
CALLEE = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)


class HoverFixture(ScaleFixture):
    def __init__(self, data, base, physical, percent, mouse, *, installed=True,
                 carrying=False, distance=1, occluded=False, mode=0, camera=(100, 20),
                 selected=True, physical_pointers=True):
        super().__init__(data, base)
        self.u.mem_map(0, 0x1000)
        self.initialize(*physical, percent)
        self.events = []
        self.mouse = mouse
        self.logical = tuple(v * self.state(0xc + i * 4) // physical[i]
                             for i, v in enumerate(mouse))
        for i, rva in enumerate((0x6c5b70, 0x6c5a04)):
            put(self.u, get(self.u, base + rva), self.logical[i])
            put(self.u, DATA + 0x110 + i * 4, mouse[i])
        if not physical_pointers:
            for address in (0x76e518, 0x76e440):
                put(self.u, address, 0)
        self.mouse_bytes = bytes(self.u.mem_read(DATA + 0x110, 8))
        self.physical_mouse = self.mouse_bytes
        self.actor = DATA + 0x10000
        self.record = DATA + 0x20000
        self.iterator = DATA + 0x21000
        self.collection = DATA + 0x22000
        self.selected = selected
        self.iteration = 0
        put(self.u, self.va(0xac618c), DATA + 0x23000)
        put(self.u, DATA + 0x23000, self.actor)
        put(self.u, self.actor + 0x603c, 20 + distance)
        put(self.u, self.actor + 0x6040, 10)
        self.u.mem_write(self.actor + 0x44, bytes([int(carrying)]))
        self.u.mem_write(self.record, struct.pack('<IBBBxIIII', 73, 20, 10,
                                                int(installed), 500, 300, 200, 50))
        put(self.u, self.va(0xacee04), self.collection)
        put(self.u, self.collection + 8, 1)
        put(self.u, self.iterator, DATA + 0x23100)
        put(self.u, DATA + 0x23100 - 4, API + 0x80)
        put(self.u, self.va(0xac5a30), DATA + 0x24000)
        self.u.mem_write(DATA + 0x24000, bytes([mode]))
        put(self.u, self.va(0xac57ac), DATA + 0x24004)
        self.u.mem_write(DATA + 0x24004, bytes([int(occluded)]))
        self.camera = camera
        for i, va in enumerate((0xac61b0, 0xac6068)):
            put(self.u, self.va(va), DATA + 0x25000 + i * 4)
            put(self.u, DATA + 0x25000 + i * 4, camera[i])
        self.actor_bytes = bytes(self.u.mem_read(self.actor, 0x6100))
        self.record_bytes = bytes(self.u.mem_read(self.record, 24))
        self.u.hook_add(UC_HOOK_CODE, self.hover_hook)

    def hover_hook(self, u, actual, size, _):
        va = actual - self.base + scale.IMAGE_BASE
        eax, edx = (u.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX))
        if va == 0xa843d4:
            self.ret(result=0 if self.selected else 0xffffffff)
        elif va == 0x81a27c:
            assert eax == self.collection
            self.ret(result=self.iterator)
        elif va == 0x81a300:
            self.iteration += 1
            self.ret(result=int(self.iteration == 1))
        elif va == 0x81a290:
            assert eax == self.iterator
            self.ret(result=self.record)
        elif va == 0xa896f0:
            assert (get(u, eax), get(u, edx)) == (20 * 32 + 16, 10 * 32 + 16)
            put(u, eax, 650)
            put(u, edx, 480)
            self.ret()
        elif va == 0xa6a610:
            self.events.append({'cursor': eax, 'mouse': self.copied_mouse(),
                                'scope': self.state(0x14)})
            self.ret()
        elif actual == API + 0x80:
            self.ret()

    def copied_mouse(self):
        return tuple(get(self.u, get(self.u, self.base + rva))
                     for rva in (0x6c5b70, 0x6c5a04))

    def detect(self, *, wrapper=True, previous_scope=1):
        self.state(0x14, previous_scope)
        self.run(patcher.WRAPPER if wrapper else patcher.NATIVE)
        assert self.copied_mouse() == self.logical
        assert bytes(self.u.mem_read(DATA + 0x110, 8)) == self.mouse_bytes
        assert bytes(self.u.mem_read(self.actor, 0x6100)) == self.actor_bytes
        assert bytes(self.u.mem_read(self.record, 24)) == self.record_bytes
        assert self.state(0x14) == previous_scope
        for register in CALLEE:
            assert self.u.reg_read(register) == VALUES[REGS.index(register)]
        assert self.u.reg_read(UC_X86_REG_ESP) == STACK + 0xf004
        picked = get(self.u, self.va(0xac4808))
        if picked:
            assert picked == self.record
            assert bytes(self.u.mem_read(DATA + 0x24000, 1)) == b'\7'
        return picked == self.record


def verify(source, candidate, expected_source_sha=patcher.BASE_SHA):
    assert patcher.sha(source) == expected_source_sha
    assert patcher.patch(source, expected_sha=expected_source_sha) == candidate
    assert patcher.patch(candidate, expected_sha=patcher.sha(candidate)) == candidate
    before, after = pefile.PE(data=source), pefile.PE(data=candidate)
    allowed = set(range(before.get_offset_from_rva(patcher.SLOT_RVA),
                        before.get_offset_from_rva(patcher.SLOT_RVA) + patcher.SLOT_SIZE))
    allowed.update(range(before.get_offset_from_rva(patcher.HOOK - scale.IMAGE_BASE),
                         before.get_offset_from_rva(patcher.HOOK - scale.IMAGE_BASE) + 5))
    checksum = before.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum')
    allowed.update(range(checksum, checksum + 4))
    assert len(source) == len(candidate)
    assert all(i in allowed for i, (a, b) in enumerate(zip(source, candidate)) if a != b)
    assert before.get_data(patcher.NATIVE_BODY_RVA, patcher.NATIVE_BODY_SIZE) == after.get_data(
        patcher.NATIVE_BODY_RVA, patcher.NATIVE_BODY_SIZE)
    guards = []
    for name, rva in (('call', patcher.HOOK - scale.IMAGE_BASE),
                      ('cave', patcher.SLOT_RVA + 0xa0),
                      ('detector', patcher.NATIVE_BODY_RVA + 0x80),
                      ('scale', scale.SIGNATURE_RVA)):
        mutated = bytearray(source)
        mutated[before.get_offset_from_rva(rva)] ^= 1
        try:
            patcher.patch(bytes(mutated), expected_sha=patcher.sha(mutated))
        except ValueError:
            guards.append(name)
        else:
            raise AssertionError(name + ' guard did not reject')
    try:
        patcher.patch(source, expected_sha='0' * 64)
    except ValueError:
        guards.append('sha256')
    else:
        raise AssertionError('SHA guard did not reject')
    cases = []
    for base in (0x400000, 0x10400000):
        for (width, height), percent in product(
                ((1920, 1080), (2560, 1440), (3440, 1440), (3840, 2160)),
                (100, 125, 150, 200)):
            for name, mouse, options, hit in (
                ('installed', (750, 500), {}, True),
                ('empty-with-drill', (750, 500), {'installed': False, 'carrying': True}, True),
                ('empty-without-drill', (750, 500), {'installed': False}, False),
                ('distant', (750, 500), {'distance': 2}, False),
                ('occluded', (750, 500), {'occluded': True}, False),
                ('other-mode', (750, 500), {'mode': 4}, False),
                ('no-selection', (750, 500), {'selected': False}, False),
                ('left-edge', (718, 500), {}, False),
                ('right-edge', (782, 500), {}, False),
                ('top-edge', (750, 484), {}, False),
                ('bottom-edge', (750, 516), {}, False),
                ('left-inside', (719, 500), {}, True),
                ('right-inside', (781, 500), {}, True),
                ('top-inside', (750, 485), {}, True),
                ('bottom-inside', (750, 515), {}, True),
                ('panned-camera', (1750, 1000), {'camera': (1100, 520)}, True),
            ):
                f = HoverFixture(candidate, base, (width, height), percent, mouse, **options)
                picked = f.detect(previous_scope=1 if len(cases) % 2 else 0)
                assert picked == hit, (name, percent, picked)
                if hit:
                    assert f.events == [{'cursor': 16, 'mouse': mouse, 'scope': 0}]
                else:
                    assert not f.events
                cases.append({'base': hex(base), 'physical': [width, height],
                              'percent': percent, 'effective_percent': f.state(0),
                              'case': name, 'hit': picked})
    # Demonstrate the user's precise 150% failure with the unmodified detector.
    old = HoverFixture(source, 0x400000, (2560, 1440), 150, (750, 500))
    assert not old.detect(wrapper=False)
    corrected = HoverFixture(candidate, 0x400000, (2560, 1440), 150, (750, 500))
    assert corrected.detect()
    # The established adapter safely falls back when the host pointers are absent.
    missing = HoverFixture(candidate, 0x400000, (2560, 1440), 100, (750, 500),
                           physical_pointers=False)
    assert missing.detect()
    return {'result': 'PASS', 'candidate_sha256': patcher.sha(candidate),
            'candidate_bytes': len(candidate), 'native_cases': len(cases) + 3,
            'guards_reject': guards, 'details': cases,
            'regression': {'physical_cursor': [750, 500], 'logical_cursor': list(old.logical),
                           'physical_rectangle': [718, 484, 782, 516],
                           'before_hit': False, 'after_hit': True},
            'native_detector_executed': True, 'native_detector_unchanged': True,
            'logical_and_physical_mouse_preserved': True, 'render_scope_restored': True,
            'native_actor_and_occurrence_preserved': True,
            'callee_registers_and_stack_preserved': True,
            'external_collection_projection_cursor_stubs': True,
            'real_client_rendering_verified': False, 'published': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=BASELINE)
    parser.add_argument('--source-sha256', default=patcher.BASE_SHA)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--out', type=Path, default=ROOT /
                        'reports/mine-drill-incident-20261010/hover/native-proof.json')
    args = parser.parse_args()
    source = args.source.read_bytes()
    candidate = (args.candidate.read_bytes() if args.candidate else
                 patcher.patch(source, expected_sha=args.source_sha256))
    report = verify(source, candidate, args.source_sha256)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'details'}, indent=2))


if __name__ == '__main__':
    main()
