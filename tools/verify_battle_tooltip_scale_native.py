"""Execute the actual battle cursor balloon and existing GPU scale x86.

Native tooltip reads/branches/coordinate arithmetic, the new render-scope
wrapper and the existing GPU vertex transformer execute at two relocated
Silver bases. Localized strings, active-weapon getters and draw API endpoints
are explicit fixtures. No process is launched and no graphical or hosted
gameplay validation is claimed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

import pefile
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_battle_tooltip_scale as tooltip
from deploy import client_ui_scale as scale
from tools.verify_client_ui_scale_native import (
    Fixture as ScaleFixture, DATA, STACK, END, FRAME, REGS, VALUES, get, put, signed,
)

BASELINE = ROOT / 'reports/client-ui-incident-20261010/baseline/silver.dll'
CALLEE = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)


class TooltipFixture(ScaleFixture):
    def __init__(self, data, base, physical, percent, mouse, mode=0, melee=False):
        super().__init__(data, base)
        self.u.mem_map(0, 0x1000)  # Native Delphi SEH frame.
        self.initialize(*physical, percent)
        self.events = []
        self.strings = {}
        self.string_next = DATA + 0x16000
        self.mode, self.melee = mode, melee
        self.mouse = mouse
        self.logical = tuple(v * self.state(0xc + i * 4) // physical[i]
                             for i, v in enumerate(mouse))
        self.input_slots = (DATA + 0x110, DATA + 0x114)
        for i, rva in enumerate((0x6c5b70, 0x6c5a04)):
            put(self.u, get(self.u, base + rva), self.logical[i])
            put(self.u, self.input_slots[i], mouse[i])
        self.physical_mouse = bytes(self.u.mem_read(DATA + 0x110, 8))
        put(self.u, base + 0x6c5a30, DATA + 0x13000)
        self.u.mem_write(DATA + 0x13000, b'\1')
        self.u.mem_write(base + 0x6c4c04, bytes([mode]))
        put(self.u, base + 0x6c4bfc, 200)
        put(self.u, base + 0x6c4c08, self.string('7-54'))
        put(self.u, base + 0x6c4c0c, self.string('65%'))
        self.actor = DATA + 0x1c000
        self.actor_bytes = bytes((i * 31 + 19) & 255 for i in range(0x1000))
        self.u.mem_write(self.actor, self.actor_bytes)
        put(self.u, DATA + 0x1b000, self.actor)
        put(self.u, base + 0x6c618c, DATA + 0x1b000)
        for rva in (0x6c6144, 0x6c6404, 0x6c614c):
            put(self.u, base + rva, DATA + 0x1d000)
        self.u.hook_add(UC_HOOK_CODE, self.tooltip_hook)

    def string(self, text):
        for pointer, previous in self.strings.items():
            if text == previous:
                return pointer
        pointer = self.string_next + 12
        raw = text.encode('utf-16le')
        self.u.mem_write(pointer - 12, struct.pack('<HHiI', 1200, 2, -1, len(text))
                         + raw + b'\0\0')
        self.strings[pointer] = text
        self.string_next += (len(raw) + 32 + 15) & ~15
        return pointer

    def tooltip_hook(self, u, actual, size, _):
        va = actual - self.base + scale.IMAGE_BASE
        eax, edx, ecx = (u.reg_read(r) for r in
                         (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
        sp = u.reg_read(UC_X86_REG_ESP)
        if va == 0x9da38c:
            self.ret(result=0)
        elif va == 0x9bf90c:
            put(u, edx, self.string('Attack action'))
            self.ret()
        elif va == 0x40c354:
            # Native checks whether the localized action label is blank.
            u.reg_write(UC_X86_REG_EFLAGS, u.reg_read(UC_X86_REG_EFLAGS) & ~0x40)
            self.ret()
        elif va == 0x6675e0:
            labels = {0x9c0244: 'Damage:', 0x9c025c: 'Accuracy:',
                      0x9c0274: 'Accuracy:'}
            put(u, edx, self.string(labels[eax - self.base + scale.IMAGE_BASE]))
            self.ret()
        elif va == 0x423b50:
            put(u, edx, eax)
            self.ret()
        elif va == 0x4244b4:
            put(u, edx, self.string(str(eax)))
            self.ret()
        elif va in (0xa843d4, 0xa7b858, 0xa83f94):
            self.ret(result={0xa843d4: 0, 0xa7b858: int(self.melee),
                             0xa83f94: 5}[va])
        elif va == 0x4f2ba8:
            self.ret(result=72)
        elif va in (0x4f2a0c, 0x4f29a8):
            self.events.append({'kind': 'text', 'text': self.strings[edx],
                                'logical': [signed(ecx), signed(get(u, sp + 8))],
                                'scope': self.state(0x14)})
            self.ret(8)
        elif va in (0x4f27fc, 0x674e78):
            self.events.append({'kind': 'icon',
                                'logical': [signed(edx), signed(ecx)],
                                'scope': self.state(0x14)})
            self.ret(12)
        elif va == 0x4f2864:
            self.events.append({'kind': 'rectangle',
                                'logical': [signed(eax), signed(edx)],
                                'scope': self.state(0x14)})
            self.ret(12)
        elif va == 0x40b0fc:
            self.ret()  # Managed temporary-string cleanup only.

    def draw(self, previous_scope=7):
        self.state(0x14, previous_scope)
        # Execute the actual patched caller. Stop immediately after its return.
        self.run(tooltip.HOOK, stop=tooltip.HOOK + 5)
        assert self.state(0x14) == previous_scope
        expected_registers = dict(zip(REGS, VALUES))
        assert all(self.u.reg_read(reg) == expected_registers[reg] for reg in CALLEE)
        assert bytes(self.u.mem_read(self.actor, len(self.actor_bytes))) == self.actor_bytes
        assert tuple(get(self.u, get(self.u, self.base + rva))
                     for rva in (0x6c5b70, 0x6c5a04)) == self.logical
        return self.events

    def upload_event(self, event):
        # Run the existing exact GPU x86 adapter with this native draw's scope.
        # Draw endpoints are stubbed above; GPU batch construction is explicit.
        scope = self.state(0x14)
        self.state(0x14, event['scope'])
        put(self.u, self.vb + 0x18, 0x144)
        put(self.u, self.vb + 0x1c, 28)
        put(self.u, FRAME - 4, self.vb)
        source, destination = DATA + 0x21000, DATA + 0x22000
        raw = struct.pack('<4f3I', *event['logical'], 0.5, 1.0,
                          0xffffffff, 0x12345678, 0x9abcdef0)
        self.u.mem_write(source, raw)
        self.u.reg_write(UC_X86_REG_EAX, source)
        self.u.reg_write(UC_X86_REG_EDX, destination)
        self.u.reg_write(UC_X86_REG_ECX, len(raw))
        self.u.reg_write(UC_X86_REG_EBP, FRAME)
        put(self.u, STACK + 0x8000, END)
        self.u.reg_write(UC_X86_REG_ESP, STACK + 0x8000)
        self.stopping = END
        self.u.emu_start(self.va(scale.UPLOAD), END, count=10000)
        assert self.u.reg_read(UC_X86_REG_EIP) == END
        assert self.u.reg_read(UC_X86_REG_ESP) == STACK + 0x8004
        result = bytes(self.u.mem_read(destination, len(raw)))
        assert result[8:] == raw[8:]
        assert bytes(self.u.mem_read(source, len(raw))) == raw
        self.state(0x14, scope)
        return list(struct.unpack('<2f', result[:8]))


def verify(source, candidate, expected_source_sha=tooltip.BASE_SHA):
    assert tooltip.sha(source) == expected_source_sha
    assert tooltip.patch(source, expected_sha=expected_source_sha) == candidate
    assert tooltip.patch(candidate, expected_sha=tooltip.sha(candidate)) == candidate
    before, after = pefile.PE(data=source), pefile.PE(data=candidate)
    allowed = set(range(before.get_offset_from_rva(tooltip.SLOT_RVA),
                        before.get_offset_from_rva(tooltip.SLOT_RVA) + tooltip.SLOT_SIZE))
    allowed.update(range(before.get_offset_from_rva(tooltip.HOOK - scale.IMAGE_BASE),
                         before.get_offset_from_rva(tooltip.HOOK - scale.IMAGE_BASE) + 5))
    checksum = before.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum')
    allowed.update(range(checksum, checksum + 4))
    assert len(source) == len(candidate)
    assert all(i in allowed for i, (a, b) in enumerate(zip(source, candidate)) if a != b)
    assert before.get_data(tooltip.NATIVE_BODY_RVA, tooltip.NATIVE_BODY_SIZE) == after.get_data(
        tooltip.NATIVE_BODY_RVA, tooltip.NATIVE_BODY_SIZE)
    for site, native, _ in scale.WORLD_CALLS:
        if site != tooltip.HOOK:
            assert after.get_data(site - scale.IMAGE_BASE, 5) == scale.call_bytes(site, native)
    guard_cases = []
    for name, rva in (('call', tooltip.HOOK - scale.IMAGE_BASE),
                      ('cave', tooltip.SLOT_RVA + 0x80),
                      ('tooltip', tooltip.NATIVE_BODY_RVA + 0x80),
                      ('scale', scale.SIGNATURE_RVA)):
        mutated = bytearray(source)
        mutated[before.get_offset_from_rva(rva)] ^= 1
        try:
            tooltip.patch(bytes(mutated), expected_sha=tooltip.sha(mutated))
        except ValueError:
            guard_cases.append(name)
        else:
            raise AssertionError(name + ' guard did not reject')
    try:
        tooltip.patch(source, expected_sha='0' * 64)
    except ValueError:
        guard_cases.append('sha256')
    else:
        raise AssertionError('SHA guard did not reject')
    cases = []
    for base in (0x400000, 0x10400000):
        for width, height, percent in ((1920, 1080, 100), (2560, 1440, 125),
                                       (2560, 1440, 150), (3440, 1440, 150),
                                       (3840, 2160, 200)):
            for mouse in ((1200, 330), (57, 40), (width - 70, height - 80)):
                for mode, melee in ((0, False), (0, True), (1, False)):
                    f = TooltipFixture(candidate, base, (width, height), percent,
                                       mouse, mode, melee)
                    events = f.draw()
                    assert events and all(e['scope'] == 1 for e in events)
                    for event in events:
                        event['physical'] = f.upload_event(event)
                        for i, pixel in enumerate(event['physical']):
                            ratio = (width, height)[i] / f.state(0xc + i * 4)
                            expected = event['logical'][i] * ratio
                            assert abs(pixel - expected) < 0.0005
                    damage = next((e for e in events if e.get('text') == '7-54'), None)
                    if mode == 0:
                        assert damage is not None
                        for i, offset in enumerate((58, 22)):
                            ratio = (width, height)[i] / f.state(0xc + i * 4)
                            assert abs(damage['physical'][i] - mouse[i] - offset * ratio) <= ratio
                    cases.append({'silver_base': hex(base), 'physical': [width, height],
                                  'percent': percent, 'cursor': list(mouse),
                                  'mode': mode, 'melee': melee,
                                  'draws': len(events), 'damage': damage})
    # The unmodified release demonstrates the user's specific failure at150%.
    f = TooltipFixture(source, 0x400000, (2560, 1440), 150, (1200, 330))
    old = f.draw(previous_scope=0)
    old_damage = next(e for e in old if e.get('text') == '7-54')
    assert old_damage['scope'] == 0
    old_damage['physical'] = f.upload_event(old_damage)
    assert old_damage['physical'][0] < 900
    return {'result': 'PASS', 'candidate_sha256': tooltip.sha(candidate),
            'candidate_bytes': len(candidate), 'native_cases': len(cases),
            'guards_reject': guard_cases, 'details': cases,
            'regression_reproduced': old_damage, 'patch_byte_range_preservation': True,
            'actual_native_tooltip_executed': True,
            'actual_native_gpu_transform_executed': True,
            'model_and_both_mouse_states_preserved': True,
            'native_callee_registers_preserved': True,
            'external_strings_and_draw_endpoints_stubbed': True,
            'real_client_rendering_verified': False, 'published': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=BASELINE)
    parser.add_argument('--source-sha256', default=tooltip.BASE_SHA,
                        help='Exact reviewed source hash when composing after another transformer')
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--out', type=Path, default=ROOT /
                        'reports/client-ui-incident-20261010/tooltip/native-proof.json')
    args = parser.parse_args()
    source = args.source.read_bytes()
    candidate = (args.candidate.read_bytes() if args.candidate else
                 tooltip.patch(source, expected_sha=args.source_sha256))
    report = verify(source, candidate, args.source_sha256)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'details'}, indent=2))


if __name__ == '__main__':
    main()
