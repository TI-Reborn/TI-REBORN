"""Execute the exact key hook at two load bases; original OK is the boundary."""
from pathlib import Path
import struct
import unittest

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP, UC_X86_REG_EDI
from deploy.client_exchange_enter import patch, KEY_DISPATCH
from deploy.client_inventory_hotkey import SHORTCUT

SOURCE = Path(__file__).resolve().parents[1]/'work/gameplay-20261117/source-silver.dll'


class EnterTests(unittest.TestCase):
    def test_only_visible_battle_exchange_quantity_modal_confirms(self):
        for base in (0x400000, 0x1400000):
            for key, battle, kind, modal, found, visible, expected in (
                (13, 1, 1, 0, True, True, True),
                (13, 1, 1, 0, True, False, False),
                (13, 1, 1, 0, False, False, False),
                (13, 0, 1, 0, True, True, False),
                (13, 1, 0, 0, True, True, False),
                (13, 1, 1, 9, True, True, False),
                (27, 1, 1, 0, True, True, False),
                (49, 1, 1, 0, True, True, False),
            ):
                with self.subTest(base=base, key=key, battle=battle, kind=kind, modal=modal,
                                  found=found, visible=visible):
                    pe = pefile.PE(data=patch(SOURCE.read_bytes()))
                    delta = base-0x400000
                    pe.relocate_image(base)
                    raw = pe.get_memory_mapped_image()
                    u = Uc(UC_ARCH_X86, UC_MODE_32)
                    u.mem_map(base, (len(raw)+4095)&~4095)
                    u.mem_write(base, raw)
                    data, stack = 0x3000000, 0x3100000
                    u.mem_map(data, 0x10000); u.mem_map(stack, 0x10000)
                    def put(at, value):
                        u.mem_write(at, struct.pack('<I', value))
                    for rva, offset in ((0x6c64a0, 0), (0x6c5f18, 4), (0x6c622c, 8)):
                        put(base+rva, data+offset)
                    put(data, battle); put(data+4, kind); put(data+8, data+0x100)
                    u.mem_write(base+0x6d0d78, bytes((modal,)))
                    u.mem_write(data+0x249, bytes((visible,)))
                    calls = []
                    def hook(uc, address, size, _):
                        if address in (SHORTCUT+delta, 0x9f5153+delta):
                            calls.append('stock' if address == SHORTCUT+delta else 'handled')
                            uc.emu_stop(); return
                        values = {0xa3fca8+delta: 7 if found else 0xffffffff,
                                  0xa3f2a0+delta: data+0x200, 0x993da0+delta: 0}
                        if address in values:
                            if address == 0x993da0+delta: calls.append('ok')
                            uc.reg_write(UC_X86_REG_EAX, values[address])
                            sp = uc.reg_read(UC_X86_REG_ESP)
                            target, = struct.unpack('<I', uc.mem_read(sp, 4))
                            uc.reg_write(UC_X86_REG_ESP, sp+4)
                            uc.reg_write(UC_X86_REG_EIP, target)
                    u.hook_add(UC_HOOK_CODE, hook)
                    u.reg_write(UC_X86_REG_ESP, stack+0x8000)
                    u.reg_write(UC_X86_REG_EDI, key)
                    u.emu_start(KEY_DISPATCH+delta, base, count=500)
                    self.assertEqual(calls, ['ok', 'handled'] if expected else ['stock'])
                    self.assertEqual(u.reg_read(UC_X86_REG_ESP), stack+0x8000)


if __name__ == '__main__':
    unittest.main()
