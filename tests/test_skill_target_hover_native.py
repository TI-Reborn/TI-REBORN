"""Execute the enemy-skill cursor check inside the exact patched Silver image."""
import hashlib
from pathlib import Path
import struct
import unittest

import capstone
import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EIP, UC_X86_REG_ESP

from deploy.client_skill_target_hover import (CURSOR_ENEMY, ENEMY_VISIBLE_CALL, SOURCE_SHA,
                                              VISIBLE, patch)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'reports/skill-target-hover-20261114/source-silver.dll'
ACTOR, STACK, STOP = 0x2000000, 0x3000000, 0x3000100


@unittest.skipUnless(SOURCE.exists(), 'retained published Silver 2026.11.13.5 required')
class SkillTargetHoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_bytes()
        assert hashlib.sha256(cls.source).hexdigest() == SOURCE_SHA
        cls.candidate = patch(cls.source)

    def run_check(self, *, visible, actor_cell, cursor_cell):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        with pefile.PE(data=self.candidate) as pe:
            u.mem_map(0x400000, (pe.OPTIONAL_HEADER.SizeOfImage + 0xfff) & ~0xfff)
            for s in pe.sections:
                u.mem_write(0x400000 + s.VirtualAddress, s.get_data())
        u.mem_map(ACTOR, 0x10000); u.mem_map(STACK, 0x10000)
        u.mem_write(ACTOR + 0x603c, struct.pack('<ii', *actor_cell))
        frame = STACK + 0x800
        u.mem_write(frame - 0xc, struct.pack('<ii', cursor_cell[1], cursor_cell[0]))
        esp = STACK + 0x400
        u.mem_write(esp, struct.pack('<I', STOP))
        u.reg_write(UC_X86_REG_ESP, esp); u.reg_write(UC_X86_REG_EBP, frame)
        u.reg_write(UC_X86_REG_EAX, ACTOR)
        calls = []

        def hook(uc, address, _size, _data):
            if address == VISIBLE:
                calls.append(uc.reg_read(UC_X86_REG_EAX))
                uc.reg_write(UC_X86_REG_EAX, 0xdeadbe00 | int(visible))
                sp = uc.reg_read(UC_X86_REG_ESP)
                uc.reg_write(UC_X86_REG_EIP, struct.unpack('<I', uc.mem_read(sp, 4))[0])
                uc.reg_write(UC_X86_REG_ESP, sp + 4)
        u.hook_add(UC_HOOK_CODE, hook)
        u.emu_start(CURSOR_ENEMY, STOP, count=200)
        self.assertEqual(calls, [ACTOR])
        self.assertEqual(u.reg_read(UC_X86_REG_EBP), frame)
        return u.reg_read(UC_X86_REG_EAX) & 0xff

    def test_visible_enemy_counts_only_on_the_cursor_cell(self):
        self.assertEqual(self.run_check(visible=True, actor_cell=(8, 10), cursor_cell=(8, 10)), 1)
        self.assertEqual(self.run_check(visible=True, actor_cell=(8, 10), cursor_cell=(9, 10)), 0)
        self.assertEqual(self.run_check(visible=True, actor_cell=(8, 10), cursor_cell=(8, 9)), 0)
        self.assertEqual(self.run_check(visible=False, actor_cell=(8, 10), cursor_cell=(8, 10)), 0)

    def test_only_the_enemy_branch_call_and_its_cave_change(self):
        changed = [i for i, (a, b) in enumerate(zip(self.source, self.candidate)) if a != b]
        with pefile.PE(data=self.candidate) as pe:
            site = pe.get_offset_from_rva(ENEMY_VISIBLE_CALL - 0x400000)
            cave = pe.get_offset_from_rva(CURSOR_ENEMY - 0x400000)
        self.assertEqual(len(self.source), len(self.candidate))
        self.assertTrue(all(site <= i < site + 5 or cave <= i < cave + 0x40 for i in changed))
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        call = next(md.disasm(self.candidate[site:site + 5], ENEMY_VISIBLE_CALL))
        self.assertEqual((call.mnemonic, int(call.op_str, 16)), ('call', CURSOR_ENEMY))
        with self.assertRaises(ValueError):
            patch(self.candidate)


if __name__ == '__main__':
    unittest.main()
