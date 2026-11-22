import struct
import unittest

from deploy import client_barracks_skills_skin as skin

try:
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
    from unicorn.x86_const import (
        UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
        UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
    )
except ImportError:
    Uc = None


@unittest.skipUnless(Uc, 'Unicorn is required for native barracks checks')
class BarracksSkillSkinTests(unittest.TestCase):
    def setUp(self):
        self.base, self.data = 0x51000000, 0x31000000
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(self.base, 0x900000)
        self.uc.mem_map(self.data, 0x10000)
        self.page, self.info, self.panel, self.skills, self.abilities, self.rows, self.gauge = (
            self.data + i * 0x400 for i in range(1, 8))
        self.put(self.base + skin.STATE, 1)
        for native, obj in ((skin.INFO, self.info), (skin.SKILL_TAB, self.skills),
                            (skin.ABILITY_TAB, self.abilities)):
            self.put(self.va(native), obj)
        for child, parent in ((self.info, self.page), (self.panel, self.page),
                              (self.skills, self.panel), (self.abilities, self.panel),
                              (self.rows, self.skills), (self.gauge, self.rows)):
            self.put(child + 0x4c, parent)
        self.put(self.skills + 0x280, 1)
        self.rectangles = []
        self.captions = []
        for native in (0xa4211c, 0xa42140, 0x4f2888, 0x4f29a8):
            addr = self.va(native)
            self.uc.hook_add(UC_HOOK_CODE, self.draw, begin=addr, end=addr)

    def va(self, addr):
        return self.base + addr - skin.BASE

    def put(self, addr, *values):
        self.uc.mem_write(addr, struct.pack(f'<{len(values)}I', *values))

    def get(self, addr, count=1):
        return struct.unpack(f'<{count}I', self.uc.mem_read(addr, count * 4))

    def draw(self, uc, addr, _, _data):
        native = addr - self.base + skin.BASE
        sp = uc.reg_read(UC_X86_REG_ESP)
        eax, ecx, edx = (uc.reg_read(reg) for reg in
                         (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX))
        stack_size = 4
        if native == 0x4f2888:
            _, _, colour, _, height = self.get(sp, 5)
            self.rectangles.append((eax, edx, ecx, height, colour))
            stack_size += 16
        elif native == 0x4f29a8:
            _, colour, y = self.get(sp, 3)
            self.captions.append((ecx, y, colour))
            stack_size += 8
        else:
            value = {0xa4211c: 100, 0xa42140: 50}[native]
            uc.reg_write(UC_X86_REG_EAX, value)
        uc.reg_write(UC_X86_REG_EIP, self.get(sp)[0])
        uc.reg_write(UC_X86_REG_ESP, sp + stack_size)

    def paint(self, entry, code, widget, stop=None):
        sp, frame = self.data + 0x7800, self.data + 0x8000
        stop = stop or self.data + 0x7000
        self.put(sp, stop)
        self.put(frame - 8, 100, 80)
        for reg, value in ((UC_X86_REG_EAX, widget), (UC_X86_REG_EBX, widget),
                           (UC_X86_REG_EBP, frame), (UC_X86_REG_ESP, sp),
                           (UC_X86_REG_ESI, 100), (UC_X86_REG_EDI, 50)):
            self.uc.reg_write(reg, value)
        self.uc.mem_write(self.va(entry), code)
        self.uc.emu_start(self.va(entry), stop, count=1000)
        self.assertEqual(self.uc.reg_read(UC_X86_REG_EIP), stop)

    def test_equal_tabs_use_their_native_hit_offsets_and_matching_label_padding(self):
        for control, offset in ((self.skills, 0), (self.abilities, 118)):
            self.paint(skin.TAB_ENTRY, skin.tabs_code(), control)
            self.assertEqual(self.get(control + 0x2b4, 2), (offset, 118))
        self.assertEqual([cap[:2] for cap in self.captions], [(114, 55), (232, 55)])
        self.assertIn((102, 72, 115, 2, skin.native_colour(0xffc88335)), self.rectangles)

    def test_flat_gauge_preserves_native_proportions_and_skips_other_widgets(self):
        entry, code = skin.GAUGE_ENTRY, skin.gauge_code()
        self.paint(entry, code, self.gauge, self.va(0xa48aee))
        self.assertEqual([r[:4] for r in self.rectangles],
                         [(100, 54, 183, 4), (100, 54, 93, 4), (100, 54, 74, 4)])
        self.rectangles.clear()
        self.paint(entry, code, self.info, self.va(skin.GAUGE_PAINT + 7))
        self.put(self.panel + 0x4c, self.info)
        self.paint(entry, code, self.gauge, self.va(skin.GAUGE_PAINT + 7))
        self.assertEqual(self.rectangles, [])
