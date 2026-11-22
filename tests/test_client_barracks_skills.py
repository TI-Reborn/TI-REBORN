import struct
import unittest

from deploy import client_barracks_preview as preview
from deploy import client_barracks_skills as skills
from deploy.client_barracks_a2 import TABLE, TABS
from deploy.client_barracks_bag import BAG
from deploy.client_barracks_skills_skin import ABILITY_TAB

try:
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
    from unicorn.x86_const import (
        UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESP,
    )
except ImportError:
    Uc = None


@unittest.skipUnless(Uc, 'Unicorn is required for native barracks checks')
class BarracksSkillsTests(unittest.TestCase):
    def setUp(self):
        self.base, self.data = 0x51000000, 0x31000000
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(self.base, 0x900000)
        self.uc.mem_map(self.data, 0x10000)
        self.uc.mem_write(self.va(skills.ENTRY), skills.layout_code())
        self.page, self.header, self.owner, self.info, self.skill, self.profile, self.model, self.armor = (
            self.data + offset for offset in range(0x100, 0x900, 0x100))
        first, profile_tab = self.data + 0x900, self.data + 0xa00
        for native, pointer in ((skills.HEADER, self.header), (skills.LEFT, self.owner),
                                (skills.INFO, self.info), (skills.SKILL_TAB, first),
                                (skills.PROFILE_TAB, profile_tab)):
            self.set(self.va(native), pointer)
        for child, parent in ((self.header, self.page), (self.owner, self.page),
                              (self.info, self.page), (self.skill, self.info),
                              (self.profile, self.info), (first, self.skill), (profile_tab, self.profile)):
            self.set(child + 0x4c, parent)
        self.set(self.page, self.va(skills.PAGE_VMT))
        self.set(self.owner + 0x30, 50, 118, 964, 558)
        self.set(self.model + 0x30, 596, 0, 356, 448)
        self.set(self.armor + 0x30, 458, 34, 124, 106)
        self.set(self.profile + 0x30, 235)
        self.children = {}
        for i, (node, children) in enumerate(((self.page, [self.owner, self.info]),
                                             (self.info, [self.skill,self.profile]),
                                             (self.owner, [0,0,self.model,0,0,0,0,0,self.armor]))):
            vector = self.data + 0x1800 + i * 0x100
            self.set(node + 0x2c, vector)
            self.set(vector + 4, vector + 16, len(children))
            self.set(vector + 16, *children)
            self.children[vector] = children
        self.moves = []
        for address in (0xa57a70, 0xa576e8, 0xa571f4):
            self.uc.hook_add(UC_HOOK_CODE, self.native_list, begin=self.va(address), end=self.va(address))

    def va(self, address):
        return self.base + address - skills.BASE

    def set(self, address, *words):
        self.uc.mem_write(address, struct.pack(f'<{len(words)}I', *words))

    def get(self, address, n=1):
        values = struct.unpack(f'<{n}I', self.uc.mem_read(address, n * 4))
        return values[0] if n == 1 else values

    def native_list(self, uc, address, size, _):
        vector, value = uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_EDX)
        children = self.children[vector]
        operation = address - self.base + skills.BASE
        if operation == 0xa57a70:
            uc.reg_write(UC_X86_REG_EAX, children.index(value))
        elif operation == 0xa576e8:
            self.moves.append(('remove', children.pop(value)))
        else:
            self.moves.append(('add', value))
            children.append(value)
        self.set(vector + 8, len(children))
        self.set(vector + 16, *children)
        sp = uc.reg_read(UC_X86_REG_ESP)
        uc.reg_write(UC_X86_REG_EIP, self.get(sp))
        uc.reg_write(UC_X86_REG_ESP, sp + 4)

    def arrange(self, *, active=1):
        self.set(self.base + skills.STATE, active)
        stack, stop = self.data + 0x7000, self.data + 0xf00
        self.set(stack, *([0] * 8), 2, stop)
        self.uc.reg_write(UC_X86_REG_ESP, stack)
        self.uc.reg_write(UC_X86_REG_EBX, self.base)
        self.uc.emu_start(self.va(skills.ENTRY), stop, count=1000)
        self.assertEqual(self.uc.reg_read(UC_X86_REG_ESP), stack + 40)

    def test_native_panel_moves_once_and_portrait_centres_in_the_new_gap(self):
        self.arrange()
        self.assertEqual(self.get(self.skill + 0x4c), self.page)
        self.assertEqual(self.get(self.skill + 0x30, 3), (767, 150, 237))
        self.assertEqual(self.get(self.profile + 0x30), 8)
        self.assertEqual(self.get(self.model + 0x30, 4), (501, 0, 297, 448))
        self.arrange()
        self.assertEqual(self.moves, [('remove',self.skill), ('add',self.skill)])

    def test_wide_to_narrow_resize_restores_information_panel_ownership(self):
        self.arrange()
        self.set(self.owner + 0x38, 840)
        self.arrange()
        self.assertEqual(self.get(self.skill + 0x4c), self.info)
        self.assertEqual(self.get(self.skill + 0x30, 3), (0, 0, 235))
        self.assertEqual(self.get(self.profile + 0x30), 235)

    def test_stock_interface_leaves_original_panel_in_place(self):
        self.arrange(active=0)
        self.assertEqual(self.get(self.skill + 0x4c), self.info)
        self.assertEqual(self.moves, [])

    def test_compact_information_docks_skills_before_laying_out_the_stack(self):
        table, nav, bag, ability = (self.data + offset for offset in (0x2000, 0x2400, 0x2800, 0x2c00))
        for address, widget, parent in ((TABLE, table, self.page), (TABS, nav, self.page),
                                        (BAG, bag, self.owner), (ABILITY_TAB, ability, self.skill)):
            self.set(self.va(address), widget)
            self.set(widget + 0x4c, parent)
        self.set(self.owner + 0x30, 12, 112, 780, 796)
        self.set(table + 0x30, 806, 112, 430, 796)
        self.set(nav + 0x34, 844)
        self.set(bag + 0x38, 314)
        self.uc.mem_write(self.va(preview.ARRANGE), preview.arrange_code(adopt_information=True))

        stack, stop = self.data + 0x7000, self.data + 0xf00
        for _ in range(2):
            self.set(stack, stop)
            self.uc.reg_write(UC_X86_REG_ESP, stack)
            self.uc.reg_write(UC_X86_REG_EBX, self.base)
            self.uc.emu_start(self.va(preview.ARRANGE), stop, count=1000)

        self.assertEqual(self.get(self.skill + 0x4c), self.page)
        self.assertEqual(self.get(self.skill + 0x30, 3), (557, 145, 237))
        self.assertEqual(self.get(self.base + preview.PANEL), self.skill)
        self.assertEqual(self.moves, [('remove', self.skill), ('add', self.skill)])
