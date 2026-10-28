"""SC goods and rental page windows execute in Unicorn against fixture windows."""
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESP

from deploy import client_page_windows as pages

ORIGIN, STATE_AT, LAYOUT_STATE = 0x8d7000, 0x8d7f80, 0x89ff00
SHOP_FIT = 0xcd5d00
HEAP = 0x30000000
PAGE, WINDOW, KIDS, LIST, NAME = HEAP, HEAP+0x1000, HEAP+0x2000, HEAP+0x2100, HEAP+0x2400
CHILD = HEAP+0x4000
RETURN = HEAP+0x3ff00


def child(index):
    return CHILD + index*0x400


class Machine:
    def __init__(self, window=pages.SC_SHOP, *, name=None, enabled=1, page=(146, 72, 1728, 768)):
        self.window = window
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(0x400000, 0x900000)
        self.uc.mem_map(HEAP, 0x40000)
        self.uc.mem_write(0x400000+ORIGIN, pages.payload(ORIGIN, STATE_AT, LAYOUT_STATE, SHOP_FIT))
        self.put(0x400000+LAYOUT_STATE, enabled)
        self.put(pages.HEADER, HEAP+0x3000)
        self.put(HEAP+0x3000+0x4c, PAGE)
        for offset, value in zip((0x30, 0x34, 0x38, 0x3c), page):
            self.put(PAGE+offset, value)
        text = (name or window.name).encode('utf-16le')
        self.put(NAME-4, len(text)//2)
        self.uc.mem_write(NAME, text)
        self.put(WINDOW+0x68, NAME)
        self.uc.mem_write(WINDOW+0x49, b'\x01')
        self.uc.mem_write(WINDOW+0x28c, b'\x01\x01')  # movable, resizable
        self.put(WINDOW+0x38, window.native_size[0])
        self.put(WINDOW+0x3c, window.native_size[1])
        self.put(WINDOW+0x2c, KIDS)
        self.put(KIDS+4, LIST)
        self.put(KIDS+8, window.children)
        for index in range(window.children):
            self.put(LIST+4*index, child(index))
            self.put(child(index)+0x2c, 0)
        self.calls = []
        self.uc.hook_add(UC_HOOK_CODE, self.native)

    def put(self, address, value):
        self.uc.mem_write(address, struct.pack('<I', value & 0xffffffff))

    def get(self, address):
        return struct.unpack('<I', self.uc.mem_read(address, 4))[0]

    def rect(self, address):
        return tuple(self.get(address+o) for o in (0x30, 0x34, 0x38, 0x3c))

    def native(self, uc, address, size, unused):
        if address == pages.NAME_EQUALS:
            name, literal, length = (uc.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
            same = self.get(name-4) == length and uc.mem_read(name, 2*length) == uc.mem_read(literal, 2*length)
            uc.reg_write(UC_X86_REG_EAX, int(same))
        elif address in (SHOP_FIT, pages.WINDOW_DRAW):
            self.calls.append((address, uc.reg_read(UC_X86_REG_EAX)))
        else:
            return
        sp = uc.reg_read(UC_X86_REG_ESP)
        uc.reg_write(UC_X86_REG_EIP, self.get(sp))
        uc.reg_write(UC_X86_REG_ESP, sp+4)

    def run(self, offset, eax=WINDOW):
        self.put(HEAP+0x3f000, RETURN)
        self.uc.reg_write(UC_X86_REG_ESP, HEAP+0x3f000)
        self.uc.reg_write(UC_X86_REG_EAX, eax)
        self.uc.emu_start(pages.BASE+ORIGIN+offset, RETURN, count=100000)


class ShowTests(unittest.TestCase):
    def test_named_window_fills_the_page(self):
        for window in pages.WINDOWS:
            with self.subTest(window=window.name):
                machine = Machine(window)
                machine.run(pages.SHOW)
                self.assertEqual(machine.rect(WINDOW), (146, 72, 1728, 768))
                for index, box in pages.layout(window, 1728, 768).items():
                    self.assertEqual(machine.rect(child(index)), tuple(v & 0xffffffff for v in box), index)
                self.assertEqual(bytes(machine.uc.mem_read(WINDOW+0x28c, 2)), b'\x00\x00')

    def test_other_windows_stay_native(self):
        machine = Machine(name='window_shop_filter')
        machine.run(pages.SHOW)
        self.assertEqual(machine.get(WINDOW+0x38), pages.SC_SHOP.native_size[0])

    def test_original_interface_or_small_page_stay_native(self):
        for machine in (Machine(enabled=0), Machine(page=(0, 0, 1100, 448))):
            machine.run(pages.SHOW)
            self.assertEqual(machine.get(WINDOW+0x38), pages.SC_SHOP.native_size[0])


class FitTests(unittest.TestCase):
    def opened(self, window=pages.RENT_SHOP):
        machine = Machine(window)
        machine.run(pages.SHOW)
        return machine

    def test_draw_fits_the_shop_first_and_then_draws_natively(self):
        machine = self.opened()
        machine.run(pages.DRAW)
        self.assertEqual(machine.calls, [(SHOP_FIT, WINDOW), (pages.WINDOW_DRAW, WINDOW)])

    def test_draw_follows_a_recentred_window(self):
        machine = self.opened()
        machine.put(WINDOW+0x30, 500)
        machine.put(WINDOW+0x38, 640)
        machine.run(pages.DRAW)
        self.assertEqual(machine.rect(WINDOW), (146, 72, 1728, 768))

    def test_draw_restores_native_when_the_page_shrinks(self):
        machine = self.opened()
        machine.put(PAGE+0x38, 1100)
        machine.run(pages.DRAW)
        window = pages.RENT_SHOP
        self.assertEqual((machine.get(WINDOW+0x38), machine.get(WINDOW+0x3c)), window.native_size)
        for index, rect in window.natives.items():
            self.assertEqual(machine.rect(child(index)), rect, index)
        self.assertEqual(bytes(machine.uc.mem_read(WINDOW+0x28c, 2)), b'\x01\x01')

    def test_routines_fit_their_blocks(self):
        raw = pages.payload(ORIGIN, STATE_AT, LAYOUT_STATE, SHOP_FIT)
        self.assertEqual(len(raw), pages.SIZE)


if __name__ == '__main__':
    unittest.main()
