"""Warehouse stack badges show authoritative counts inside the square cell."""
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

from deploy.client_barracks_cards import number_code
from deploy.client_item_icon_render import _quantity


class ItemCountTests(unittest.TestCase):
    def test_only_stacked_warehouse_items_draw_their_quantity(self):
        for scope, count, expected in ((1, 3, ['3']), (1, 120, ['120']),
                                       (1, 1, []), (0, 3, []), (2, 3, []),
                                       (3, 3, [])):
            machine = Uc(UC_ARCH_X86, UC_MODE_32)
            machine.mem_map(0x400000, 0x900000)
            machine.mem_map(0x30000000, 0x20000)
            origin, state = 0x8a0000, 0x8a9000
            machine.mem_write(0x400000+origin+0x2700, _quantity(origin, state))
            machine.mem_write(0x400000+origin+0x23000,
                              number_code(0x400000+origin+0x23000))

            def put(address, value):
                machine.mem_write(address, struct.pack('<I', value & 0xffffffff))

            def get(address):
                return struct.unpack('<I', machine.mem_read(address, 4))[0]

            frame, record = 0x30001000, 0x30002000
            put(frame-4, 100); put(frame-8, 200); put(frame-12, record)
            put(record+28, count); put(0x400000+state, scope)
            calls = []

            def native(uc, address, size, unused):
                if address != 0x67571c:
                    return
                ptr = machine.reg_read(UC_X86_REG_EAX)
                calls.append(bytes(machine.mem_read(ptr, get(ptr-4))).decode('utf-16le'))
                x, y = machine.reg_read(UC_X86_REG_EDX), machine.reg_read(UC_X86_REG_ECX)
                self.assertGreaterEqual(x, 68)
                self.assertLessEqual(x+7*len(calls[-1]), 140)
                self.assertGreaterEqual(y, 184)
                self.assertLessEqual(y+16, 256)
                sp = machine.reg_read(UC_X86_REG_ESP)
                machine.reg_write(UC_X86_REG_EIP, get(sp))
                machine.reg_write(UC_X86_REG_ESP, sp+16)

            machine.hook_add(UC_HOOK_CODE, native)
            put(0x3001f000, 0x3001ff00)
            machine.reg_write(UC_X86_REG_EBP, frame)
            machine.reg_write(UC_X86_REG_ESP, 0x3001f000)
            machine.emu_start(0x400000+origin+0x2700, 0x3001ff00, count=10000)
            self.assertEqual(calls, expected)
            self.assertEqual(machine.reg_read(UC_X86_REG_ESP), 0x3001f004)


if __name__ == '__main__':
    unittest.main()
