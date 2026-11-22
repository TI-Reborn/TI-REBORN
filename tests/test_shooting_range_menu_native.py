import json
from pathlib import Path
import struct
import unittest

try:
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
    from unicorn.x86_const import UC_X86_REG_ESP
except ImportError:
    Uc = None

from deploy.client_contracts_windows import relocate
from deploy.client_shooting_range_menu import (
    CONTRACTS_ENTRY, IMAGE_BASE, SLOTS, STOCK_ENTRY, STOCK_LAYOUT, TOWN, patch_plan,
)
from tio.locations import MINE_LOCATIONS


@unittest.skipIf(Uc is None, 'Unicorn required for native menu regression')
class ShootingRangeMenuNativeTests(unittest.TestCase):
    def setUp(self):
        source = (Path(__file__).resolve().parents[1] / 'work/launcher-0148-20261114/launcher'
                  / 'Assets/native-contracts-windows.json')
        if not source.is_file():
            self.skipTest('Current launcher source required for native menu regression')
        self.plan = json.loads(source.read_bytes())
        patch_plan(self.plan)
        self.module, self.plan_base, self.heap = 0x1800000, 0x21000000, 0x31000000
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        for base, size in ((self.module, 0x700000), (self.plan_base, 0x20000), (self.heap, 0x10000)):
            self.uc.mem_map(base, size)
        self.uc.mem_write(self.plan_base, relocate(self.plan, self.plan_base, self.module))
        self.header = self.plan_base + self.plan['header']
        self.town = self.heap + 0x1000
        self.word(self.module + TOWN - IMAGE_BASE, self.town)
        self.word(self.town, 17)
        self.window = self.heap + 0x2000
        self.word(self.header + 24, self.window)
        self.injected = []
        for index in range(3):
            control = self.heap + 0x3000 + 0x400 * index
            self.word(self.plan_base + self.plan['records'] + index * self.plan['stride'], control)
            self.injected.append(control)
        self.slots = []
        for index, (address, _) in enumerate(SLOTS):
            control = self.heap + 0x4000 + 0x400 * index
            self.word(self.module + address - IMAGE_BASE, control)
            self.slots.append(control)

    def word(self, address, value):
        self.uc.mem_write(address, struct.pack('<I', value))

    def read_word(self, address):
        return struct.unpack('<I', self.uc.mem_read(address, 4))[0]

    def run_hook(self, entry, end=None):
        self.word(self.heap + 0xF000, self.heap)
        self.uc.reg_write(UC_X86_REG_ESP, self.heap + 0xF000)
        self.uc.emu_start(self.plan_base + entry, end or self.heap, count=5000)

    def test_reload_and_periodic_updates_keep_the_same_four_slots(self):
        # Simulate the periodic updater restoring both injected controls.
        self.uc.mem_write(self.plan_base + 0x5000, b'\xc3')
        for entry in (STOCK_ENTRY, CONTRACTS_ENTRY, 0x800, 0x800):
            with self.subTest(entry=hex(entry)):
                for control in self.injected[:2]:
                    self.uc.mem_write(control + 0x49, b'\x01\x01')
                for control in self.slots:
                    self.word(control + 0x34, 0x20)
                self.word(self.header, 1)
                self.word(self.header + 8, 1)
                self.word(self.window + 0x3C, 0)
                end = self.module + 0xA3F301 - IMAGE_BASE if entry == 0x800 else None
                self.run_hook(entry, end)
                for control in self.injected[:2]:
                    self.assertEqual(self.uc.mem_read(control + 0x49, 2), b'\0\0')
                self.assertEqual([self.read_word(c + 0x34) for c in self.slots],
                                 [0x20, 0x40, 0x60, 0x80])
                self.assertEqual(self.read_word(self.window + 0x3C), 0xB0)
                if entry == 0x800:
                    self.assertEqual(self.read_word(self.header + 8), 0)

    def test_original_layouts_still_run_in_the_city(self):
        self.word(self.town, 2)
        for control in self.injected[:2]:
            self.uc.mem_write(control + 0x49, b'\x01\x01')
        self.run_hook(STOCK_ENTRY, self.module + STOCK_LAYOUT + 5 - IMAGE_BASE)
        self.run_hook(CONTRACTS_ENTRY, self.plan_base + 0x400)
        for control in self.injected[:2]:
            self.assertEqual(self.uc.mem_read(control + 0x49, 2), b'\x01\x01')

    def test_caption_refresh_keeps_mine_buttons_hidden(self):
        # Leave the real updater in place and stub only Silver's caption setter.
        self.uc.mem_write(self.module + 0xA42B04 - IMAGE_BASE, b'\xc3')
        for index in (0, 1):
            record = self.plan_base + self.plan['records'] + index * self.plan['stride']
            self.word(record + 4, 1)
            self.word(record + 8, 1)
        end = self.module + 0xA3F301 - IMAGE_BASE
        for town in (*MINE_LOCATIONS, 2):
            with self.subTest(town=town):
                self.word(self.town, town)
                for control in self.injected[:2]:
                    self.uc.mem_write(control + 0x49, b'\0\0')
                for control in self.slots:
                    self.word(control + 0x34, 0x24)
                self.word(self.header, 1)
                self.run_hook(0x800, end)
                self.assertEqual(self.read_word(self.header), 0)
                expected = b'\0\0' if town in MINE_LOCATIONS else b'\x01\x01'
                for control in self.injected[:2]:
                    self.assertEqual(self.uc.mem_read(control + 0x49, 2), expected)
                self.assertEqual([self.read_word(c + 0x34) for c in self.slots], [0x24] * 4)
