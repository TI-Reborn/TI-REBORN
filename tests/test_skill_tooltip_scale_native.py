"""The skill targeting balloon is drawn in the same UI scope as the attack balloon."""
import hashlib
from pathlib import Path
import struct
import unittest

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EIP, UC_X86_REG_ESI,
                               UC_X86_REG_ESP)

from deploy import client_ui_scale as scale
from deploy.client_skill_tooltip_scale import HOOK, NATIVE, SOURCE_SHA, WRAPPER, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'reports/skill-tooltip-scale-20261114/source-silver.dll'
STACK, STOP = 0x3000000, 0x3000100
SCOPE = 0x400000 + scale.STATE + 0x14
ATTACK_HOOK, ATTACK_WRAPPER = 0x9f4108, 0xc27900


@unittest.skipUnless(SOURCE.exists(), 'retained published Silver 2026.11.14.1 required')
class SkillTooltipScaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_bytes()
        assert hashlib.sha256(cls.source).hexdigest() == SOURCE_SHA
        cls.candidate = patch(cls.source)

    def image(self):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        with pefile.PE(data=self.candidate) as pe:
            u.mem_map(0x400000, (pe.OPTIONAL_HEADER.SizeOfImage + 0xfff) & ~0xfff)
            for s in pe.sections:
                u.mem_write(0x400000 + s.VirtualAddress, s.get_data())
        u.mem_map(STACK, 0x10000)
        return u

    def scope_during(self, entry, native):
        u = self.image()
        u.mem_write(SCOPE, struct.pack('<I', 0))
        esp = STACK + 0x400
        u.mem_write(esp, struct.pack('<I', STOP))
        u.reg_write(UC_X86_REG_ESP, esp)
        for register, value in ((UC_X86_REG_EBP, 0x1111), (UC_X86_REG_EBX, 0x2222),
                                (UC_X86_REG_ESI, 0x3333)):
            u.reg_write(register, value)
        seen = []

        def hook(uc, address, _size, _data):
            if address == native:
                seen.append(struct.unpack('<I', uc.mem_read(SCOPE, 4))[0])
                sp = uc.reg_read(UC_X86_REG_ESP)
                uc.reg_write(UC_X86_REG_EIP, struct.unpack('<I', uc.mem_read(sp, 4))[0])
                uc.reg_write(UC_X86_REG_ESP, sp + 4)
        u.hook_add(UC_HOOK_CODE, hook)
        u.emu_start(entry, STOP, count=500)
        restored = struct.unpack('<I', u.mem_read(SCOPE, 4))[0]
        preserved = (u.reg_read(UC_X86_REG_EBP), u.reg_read(UC_X86_REG_EBX), u.reg_read(UC_X86_REG_ESI),
                     u.reg_read(UC_X86_REG_ESP))
        return seen, restored, preserved

    def test_skill_balloon_uses_the_attack_balloon_scope_and_restores_it(self):
        skill = self.scope_during(WRAPPER, NATIVE)
        attack = self.scope_during(ATTACK_WRAPPER, 0x9bfea0)
        self.assertEqual(skill[0], [1])
        self.assertEqual(skill[0], attack[0])
        self.assertEqual(skill[1], 0)
        self.assertEqual(skill[2], (0x1111, 0x2222, 0x3333, STACK + 0x404))

    def test_only_the_skill_balloon_call_and_its_wrapper_change(self):
        with pefile.PE(data=self.candidate) as pe:
            hook = pe.get_offset_from_rva(HOOK - 0x400000)
            wrapper = pe.get_offset_from_rva(WRAPPER - 0x400000)
            attack = pe.get_offset_from_rva(ATTACK_HOOK - 0x400000)
        changed = [i for i, (a, b) in enumerate(zip(self.source, self.candidate)) if a != b]
        self.assertTrue(all(hook <= i < hook + 5 or wrapper <= i < wrapper + 0xc0 for i in changed))
        self.assertEqual(self.candidate[hook:hook + 5], scale.call_bytes(HOOK, WRAPPER))
        self.assertEqual(self.candidate[attack:attack + 5], scale.call_bytes(ATTACK_HOOK, ATTACK_WRAPPER))
        with self.assertRaises(ValueError):
            patch(self.candidate)


if __name__ == '__main__':
    unittest.main()
