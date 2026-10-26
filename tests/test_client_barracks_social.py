"""Native social windows fit their column and preserve unrelated windows."""
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX, UC_X86_REG_ESP,
    UC_X86_REG_EIP,
)

from deploy import client_barracks_social as social
from deploy.client_barracks_a2 import layout


class SocialLayoutTests(unittest.TestCase):
    def test_social_controls_fit_the_right_column_on_both_layouts(self):
        for width in (1728, 1344):
            for name in (*social.NAMES, 'window_other'):
                with self.subTest(width=width, name=name):
                    machine = Uc(UC_ARCH_X86, UC_MODE_32)
                    machine.mem_map(0x400000, 0x900000)
                    machine.mem_map(0x30000000, 0x10000)
                    origin, state = 0x8ce800, 0x89ff00
                    machine.mem_write(0x400000+origin, social.payload(origin, state))

                    def put(address, value):
                        machine.mem_write(address, struct.pack('<I', value & 0xffffffff))

                    def get(address):
                        return struct.unpack('<I', machine.mem_read(address, 4))[0]

                    root, header, window, vector = (0x30001000, 0x30002000,
                                                    0x30003000, 0x30004000)
                    put(0xac4bdc, header); put(header+0x4c, root)
                    put(root+0x30, 146); put(root+0x34, 72)
                    put(root+0x38, width); put(root+0x3c, 768)
                    machine.mem_write(root+0x49, b'\x01')
                    put(0x400000+state, 1)
                    put(window+0x2c, vector); put(vector+4, vector+16)
                    put(vector+8, 26)
                    children = []
                    for index in range(26):
                        child = 0x30005000+index*0x100
                        put(vector+16+index*4, child); children.append(child)
                    text = 0x30009000
                    put(text-4, len(name))
                    machine.mem_write(text, name.encode('utf-16le')+b'\0\0')
                    put(window+0x68, text)

                    def native(uc, address, size, unused):
                        if address != 0xc2be00:
                            return
                        left = machine.reg_read(UC_X86_REG_EAX)
                        right = machine.reg_read(UC_X86_REG_EDX)
                        length = machine.reg_read(UC_X86_REG_ECX)*2
                        equal = (get(left-4)*2 == length and
                                 machine.mem_read(left, length) == machine.mem_read(right, length))
                        machine.reg_write(UC_X86_REG_EAX, int(equal))
                        sp = machine.reg_read(UC_X86_REG_ESP)
                        machine.reg_write(UC_X86_REG_EIP, get(sp))
                        machine.reg_write(UC_X86_REG_ESP, sp+4)

                    machine.hook_add(UC_HOOK_CODE, native)
                    put(0x3000f000, 0x3000ff00)
                    machine.reg_write(UC_X86_REG_EAX, window)
                    machine.reg_write(UC_X86_REG_ESP, 0x3000f000)
                    machine.emu_start(0x400000+origin, 0x3000ff00, count=20000)
                    self.assertEqual(machine.reg_read(UC_X86_REG_ESP), 0x3000f004)
                    if name == 'window_other':
                        self.assertEqual(get(window+0x38), 0)
                        continue
                    column = layout(width, 768)['right']
                    self.assertGreaterEqual(get(window+0x30), 146+column.x)
                    self.assertEqual(get(window+0x34), 72+column.y)
                    self.assertLessEqual(get(window+0x30)+get(window+0x38), 146+column.x+column.width)
                    for child in children:
                        if get(child+0x38):
                            self.assertLessEqual(get(child+0x30)+get(child+0x38), get(window+0x38))
                            self.assertLessEqual(get(child+0x34)+get(child+0x3c), get(window+0x3c))


if __name__ == '__main__':
    unittest.main()
