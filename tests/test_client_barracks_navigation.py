"""The new tab drawing preserves native ownership, stack and registers."""
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ESI,
    UC_X86_REG_EDI, UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_EFLAGS,
)

from deploy import client_barracks_navigation as navigation


class NavigationNativeTests(unittest.TestCase):
    def test_counter_has_space_in_a2_and_keeps_stock_width_in_other_layouts(self):
        for enabled in (0, 1):
            machine = Uc(UC_ARCH_X86, UC_MODE_32)
            machine.mem_map(0x400000, 0x900000)
            machine.mem_map(0x30000000, 0x10000)
            origin, state = 0x8c8000, 0x89ff00
            machine.mem_write(0x400000+origin, navigation.payload(origin, state, 0xa45400, state+0xc))
            machine.mem_write(0x400000+state, struct.pack('<I', enabled))
            machine.reg_write(UC_X86_REG_EAX, 0xffffffff)
            machine.reg_write(UC_X86_REG_EBP, 0x30001000)
            machine.reg_write(UC_X86_REG_EBX, 111)
            machine.reg_write(UC_X86_REG_ESP, 0x3000f000)
            machine.emu_start(0x400000+origin+0x1400, 0xc2071c, count=1000)
            width = struct.unpack('<i', machine.mem_read(0x30001000-20, 4))[0]
            self.assertEqual(width, 200 if enabled else -1)
            self.assertEqual(machine.reg_read(UC_X86_REG_EBX), 111)
            self.assertEqual(machine.reg_read(UC_X86_REG_ESP), 0x3000f000)
            self.assertEqual(bool(machine.reg_read(UC_X86_REG_EFLAGS) & 0x80), not enabled)

    def test_each_tab_draws_its_own_caption_and_keeps_native_context(self):
        for child_index, title in zip((0, 1, 3, 5, 6), navigation.TITLES):
            with self.subTest(title=title):
                machine=Uc(UC_ARCH_X86, UC_MODE_32)
                machine.mem_map(0x400000, 0x900000)
                machine.mem_map(0x30000000, 0x10000)
                origin, state=0x8c8000, 0x89ff00
                machine.mem_write(0x400000+origin, navigation.payload(origin, state, 0xa45400, state+0xc))

                def put(address, value):
                    machine.mem_write(address, struct.pack('<I', value & 0xffffffff))

                def get(address):
                    return struct.unpack('<I', machine.mem_read(address,4))[0]

                button, parent, children, values=(0x30001000, 0x30002000,
                                                   0x30003000, 0x30004000)
                put(0x400000+state, 1); put(0xad1094, parent)
                put(button+0x4c, parent); put(parent+0x2c, children)
                put(children+4, values); put(values+4*child_index, button)
                put(button+0x38, 96); put(button+0x3c, 56)
                machine.mem_write(button+0x49, b'\x01\x01')
                calls=[]

                def returned(extra=0):
                    sp=machine.reg_read(UC_X86_REG_ESP)
                    machine.reg_write(UC_X86_REG_EIP,get(sp))
                    machine.reg_write(UC_X86_REG_ESP,sp+4+extra)

                def native(uc, address, size, unused):
                    if address in (0xa4211c, 0xa42140):
                        machine.reg_write(UC_X86_REG_EAX, 100)
                        returned()
                    elif address == 0x4f2888:
                        returned(16)
                    elif address == 0x67571c:
                        pointer=machine.reg_read(UC_X86_REG_EAX)
                        calls.append(bytes(machine.mem_read(pointer,get(pointer-4))).decode('utf-16le'))
                        returned(12)

                machine.hook_add(UC_HOOK_CODE,native)
                registers=(UC_X86_REG_EBX,UC_X86_REG_ESI,UC_X86_REG_EDI,UC_X86_REG_EBP)
                for register, value in zip(registers,(111,222,333,444)):
                    machine.reg_write(register,value)
                put(0x3000f000,0x3000ff00)
                machine.reg_write(UC_X86_REG_EAX,button)
                machine.reg_write(UC_X86_REG_ESP,0x3000f000)
                machine.emu_start(0x400000+origin+0x2000,0x3000ff00,count=20000)
                self.assertEqual(calls,[title])
                self.assertEqual([machine.reg_read(r) for r in registers],[111,222,333,444])
                self.assertEqual(machine.reg_read(UC_X86_REG_ESP),0x3000f004)


if __name__ == '__main__':
    unittest.main()
