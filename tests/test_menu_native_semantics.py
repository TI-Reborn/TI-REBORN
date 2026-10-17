"""Execute presentation thunks with native ABI sentinels, without game/auth IO."""
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX,
    UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP,
    UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_EFLAGS)

from deploy import client_menu_interface as menu

REGS = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
        UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
OBJECT = 0x3001000
REF = 0x3000000
TI = 0x2000000
STACK = 0x4008000
STOP = 0x400f000
SLOT = 0x3001800


class Machine:
    def __init__(self):
        self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        for address, size in ((0x400000, 0x900000), (TI, 0x400000),
                              (0x3000000, 0x20000), (0x4000000, 0x10000)):
            self.u.mem_map(address, size)
        for address, code in menu.thunks().items():
            self.u.mem_write(address, code)
        self.handlers = {}
        self.u.hook_add(UC_HOOK_CODE, self.hook)
        self.write(menu.IMAGE_BASE+menu.FONT_RVA, 8)
        self.write(menu.IMAGE_BASE+menu.CLIENT_BASE_RVA, TI)
        self.write(TI+0x36e688, SLOT)
        self.write(SLOT, 3)
        self.write(REF, OBJECT)
        self.write(OBJECT+0x2d0, menu.TAG)
        self.write(menu.IMAGE_BASE+menu.FRAME_RVA, 0x12345678)
        self.write(OBJECT+0x338, 0x12345678)
        self.write(OBJECT+0x30, 576)
        self.write(OBJECT+0x34, 256)

    def write(self, address, value):
        self.u.mem_write(address, struct.pack('<I', value & 0xffffffff))

    def read(self, address):
        return struct.unpack('<I', self.u.mem_read(address, 4))[0]

    def reg(self, register, value=None):
        if value is not None:
            self.u.reg_write(register, value)
        return self.u.reg_read(register)

    def ret(self, pop=0):
        sp = self.reg(UC_X86_REG_ESP)
        target = self.read(sp)
        self.reg(UC_X86_REG_ESP, sp+4+pop)
        self.reg(UC_X86_REG_EIP, target)

    def hook(self, _u, address, _size, _data):
        if address == STOP:
            self.u.emu_stop()
        elif address in self.handlers:
            self.handlers[address]()

    def run(self, entry, *arguments):
        self.write(STACK, STOP)
        for index, argument in enumerate(arguments, 1):
            self.write(STACK+index*4, argument)
        self.reg(UC_X86_REG_ESP, STACK)
        self.u.emu_start(menu.ENTRIES[entry], 0, count=2000)


class NativeMenuSemanticsTests(unittest.TestCase):
    def test_small_viewport_position_clamp_retains_horizontal_position_and_name(self):
        for center, expected in ((300,360), (384,480), (540,540)):
            m = Machine()
            m.reg(UC_X86_REG_EAX, 0x112233)
            m.reg(UC_X86_REG_EDX, 0x223344)
            m.reg(UC_X86_REG_ECX, center)
            seen = []
            def native():
                seen.append((m.reg(UC_X86_REG_EAX), m.reg(UC_X86_REG_EDX), m.reg(UC_X86_REG_ECX)))
                m.ret()
            m.handlers[0xa69d7c] = native
            m.run('position')
            self.assertEqual(seen, [(0x112233,0x223344,expected)])
            self.assertEqual(m.reg(UC_X86_REG_ESP), STACK+4)

    def test_initializer_preserves_registers_and_native_following_stack(self):
        m = Machine()
        original = {reg: 0x100+index for index, reg in enumerate(REGS)}
        for reg, value in original.items():
            m.reg(reg, value)
        m.reg(UC_X86_REG_EFLAGS, 0x246)
        flags = m.reg(UC_X86_REG_EFLAGS)
        m.write(0x400000+0x6c5800, REF)
        m.write(REF, TI+0x31be94)
        m.write(TI+0x36e180, SLOT)
        m.write(SLOT, 0xabcdef)
        calls = []

        def resource():
            sp = m.reg(UC_X86_REG_ESP)
            calls.append((m.reg(UC_X86_REG_ECX), m.reg(UC_X86_REG_EDX),
                          [m.read(sp+4+i*4) for i in range(4)]))
            m.reg(UC_X86_REG_EAX, 0x555)
            m.reg(UC_X86_REG_ECX, 0x666)
            m.reg(UC_X86_REG_EDX, 0x777)
            m.ret(16)

        def font():
            calls.append((m.reg(UC_X86_REG_EAX), m.reg(UC_X86_REG_EDX),
                          m.reg(UC_X86_REG_ECX)))
            m.reg(UC_X86_REG_EAX, 8)
            m.ret()

        m.handlers[0x4f2cb4] = resource
        m.handlers[TI+0x2fecc8] = font
        m.handlers[0xa62db5] = m.u.emu_stop
        m.run('initialize')
        self.assertEqual(len(calls), 3)
        for dimensions, rva in zip(calls[:2], (menu.RESOURCE_RVA, menu.FRAME_RVA)):
            expected = 50 if rva == menu.RESOURCE_RVA else 32
            self.assertEqual(dimensions, (expected, expected, [0x400000+rva, 2, 0, 0]))
        self.assertEqual(calls[2], (0xabcdef, 0x400000+menu.SECTION_RVA+0xb80,
                                    0x400000+menu.SECTION_RVA+0xba0))
        self.assertEqual(m.read(0x400000+menu.CLIENT_BASE_RVA), TI)
        self.assertEqual(m.read(0x400000+menu.FONT_RVA), 8)
        self.assertEqual({reg:m.reg(reg) for reg in REGS}, original)
        self.assertEqual(m.reg(UC_X86_REG_EFLAGS), flags)
        self.assertEqual(m.reg(UC_X86_REG_ESP), STACK-12)
        self.assertEqual([m.read(STACK-12+i*4) for i in range(4)], [2, 0, 0, STOP])

    def test_constructor_tail_call_keeps_parent_argument(self):
        m = Machine()
        m.reg(UC_X86_REG_EBX, 0x112233)
        seen = []
        def native():
            seen.append((m.reg(UC_X86_REG_ECX), m.reg(UC_X86_REG_EBX),
                         m.read(m.reg(UC_X86_REG_ESP)+4)))
            m.ret(4)
        m.handlers[0xa4517c] = native
        m.run('construct', 0xabc123)
        self.assertEqual(seen, [(0x400000+menu.RESOURCE_RVA, 0x112233, 0xabc123)])
        self.assertEqual(m.reg(UC_X86_REG_ESP), STACK+8)

    def test_marked_and_normal_measure_draw_restore_font_and_stack(self):
        for entry, target, count in (('measure', 0x675578, 1), ('draw', 0x4f2a0c, 2)):
            for marked in (False, True):
                with self.subTest(entry=entry, marked=marked):
                    m = Machine()
                    m.write(OBJECT+0x2d0, menu.TAG if marked else 0)
                    m.reg(UC_X86_REG_EBX, REF)
                    m.reg(UC_X86_REG_EAX, 0x112244)
                    m.reg(UC_X86_REG_ECX, 0x223355)
                    arguments = tuple(range(0x777700, 0x777700+count))
                    seen = []
                    def native():
                        sp = m.reg(UC_X86_REG_ESP)
                        seen.append((m.read(SLOT), tuple(m.read(sp+4+i*4) for i in range(count)),
                                     m.reg(UC_X86_REG_ECX)&255 if entry=='measure' else m.reg(UC_X86_REG_EAX)&255))
                        m.reg(UC_X86_REG_EAX, 0x443322)
                        m.ret(count*4)
                    m.handlers[target] = native
                    m.run(entry, *arguments)
                    self.assertEqual(seen, [(8 if marked else 3, arguments,
                                             3 if marked else (0x55 if entry=='measure' else 0x44))])
                    self.assertEqual(m.read(SLOT), 3)
                    self.assertEqual(m.read(0x400000+menu.FONT_RVA), 8)
                    self.assertEqual(m.reg(UC_X86_REG_EAX), 0x443322)
                    self.assertEqual(m.reg(UC_X86_REG_ESP), STACK+4+count*4)

    def test_title_scope_matches_unique_frame_not_same_dimensions(self):
        for main in (False, True):
            with self.subTest(main=main):
                m = Machine()
                m.write(OBJECT+0x338, 0x12345678 if main else 0x777777)
                m.write(OBJECT+0x38, 384)
                m.write(OBJECT+0x3c, 448)
                m.reg(UC_X86_REG_EBX, OBJECT)
                m.reg(UC_X86_REG_EAX, 0x112244)
                m.reg(UC_X86_REG_ECX, 91)
                m.reg(UC_X86_REG_EDX, 0x223355)
                seen = []
                def native():
                    sp = m.reg(UC_X86_REG_ESP)
                    seen.append((m.read(SLOT), m.reg(UC_X86_REG_EBX),
                                 m.reg(UC_X86_REG_EDX), m.reg(UC_X86_REG_ECX),
                                 m.reg(UC_X86_REG_EAX)&255, m.read(sp+4), m.read(sp+8)))
                    m.reg(UC_X86_REG_EAX, 0x443322)
                    m.ret(8)
                m.handlers[0x4f2a0c if main else 0x4f29a8] = native
                m.run('title', 0x123123, 83)
                self.assertEqual(seen, [(8 if main else 3, OBJECT, 0x223355,
                                         768 if main else 91, 3 if main else 0x44,
                                         0x123123, 278 if main else 83)])
                self.assertEqual(m.read(SLOT), 3)
                self.assertEqual(m.read(0x400000+menu.FONT_RVA), 8)
                self.assertEqual(m.reg(UC_X86_REG_EAX), 0x443322)
                self.assertEqual(m.reg(UC_X86_REG_ESP), STACK+12)

    def test_logo_scales_for_supported_viewports_and_preserves_abi(self):
        for viewport, expected_width in ((800,375), (1024,480), (1920,640)):
            m = Machine()
            m.write(0x400000+0x6c56e0, REF)
            m.write(REF, viewport)
            m.u.mem_write(OBJECT+4, struct.pack('<HH', 640, 190))
            m.reg(UC_X86_REG_EAX, OBJECT)
            m.reg(UC_X86_REG_EBX, 0x123456)
            m.reg(UC_X86_REG_ESI, 0x234567)
            m.reg(UC_X86_REG_EDI, 0x345678)
            seen=[]
            def native():
                sp=m.reg(UC_X86_REG_ESP)
                seen.append((m.reg(UC_X86_REG_EAX), m.reg(UC_X86_REG_EDX), m.reg(UC_X86_REG_ECX),
                             [m.read(sp+4+i*4) for i in range(4)]))
                m.ret(16)
            m.handlers[0x4f28d4]=native
            m.run('logo', 111, 222)
            self.assertEqual(seen, [(OBJECT, (viewport-expected_width)//2, 20,
                                     [0,0,expected_width*190//640,expected_width])])
            self.assertEqual([m.reg(reg) for reg in (UC_X86_REG_EBX,UC_X86_REG_ESI,UC_X86_REG_EDI)],
                             [0x123456,0x234567,0x345678])
            self.assertEqual(m.reg(UC_X86_REG_ESP), STACK+12)


if __name__ == '__main__':
    unittest.main()
