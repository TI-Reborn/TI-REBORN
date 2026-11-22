"""Execute the real Services description call with managed-string stubs only."""
from pathlib import Path
import struct
import unittest

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX,
                              UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EIP,
                              UC_X86_REG_ESI, UC_X86_REG_ESP)

from deploy import client_warehouse_service_description as patcher

SOURCE = Path(__file__).resolve().parents[1] / 'reports/warehouse-expansion-20261101/client/silver-before.dll'
if not SOURCE.is_file():
    SOURCE = Path.home() / 'AppData/Local/TIO-Online/silver.dll'
DATA = 0x30000000
SAVED = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)


class Machine:
    def __init__(self, raw, *, base=0x400000, powers=(8, 16, 32, 64, 128, 256)):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.base = base
        with pefile.PE(data=raw) as pe:
            pe.relocate_image(base)
            self.uc.mem_map(base, pe.OPTIONAL_HEADER.SizeOfImage)
            self.uc.mem_write(base, pe.get_memory_mapped_image())
        self.uc.mem_map(DATA, 0x20000)
        self.parent, self.offer, self.destination = DATA+0x100, DATA+0x200, DATA+0x300
        self.put(self.parent-4, self.offer)
        rows = [(1, number, power) for number, power in enumerate(powers, 1)]
        rows.extend((2, number, number) for number in range(1, 6))
        table = DATA+0x1000
        self.put(table-4, len(rows))
        for index, (service, level, power) in enumerate(rows):
            self.uc.mem_write(table+24*index, struct.pack('<6I', service, level, power, 0, 0, 0))
        self.put(self.address(0xacefb0), table)
        self.result = None
        self.uc.hook_add(UC_HOOK_CODE, self.native)

    def address(self, original):
        return self.base+original-patcher.BASE

    def put(self, address, value):
        self.uc.mem_write(address, struct.pack('<I', value))

    def get(self, address):
        return struct.unpack('<I', self.uc.mem_read(address, 4))[0]

    def native(self, uc, address, size, unused):
        if address not in (self.address(0x4244b4), self.address(0x40b09c)):
            return
        self.result = (str(uc.reg_read(UC_X86_REG_EAX))
                       if address == self.address(0x4244b4) else '')
        sp = uc.reg_read(UC_X86_REG_ESP)
        uc.reg_write(UC_X86_REG_EIP, self.get(sp))
        uc.reg_write(UC_X86_REG_ESP, sp+4)

    def run(self, service, level):
        self.put(self.offer, service)
        values = (111, 222, 333, self.parent)
        for register, value in zip(SAVED, values):
            self.uc.reg_write(register, value)
        stack = DATA+0x1f000
        self.put(stack, self.parent)
        self.uc.reg_write(UC_X86_REG_ESP, stack)
        self.uc.reg_write(UC_X86_REG_EAX, level)
        self.uc.reg_write(UC_X86_REG_EDX, self.destination)
        self.uc.emu_start(self.address(patcher.HOOK), self.address(patcher.HOOK+5), count=2000)
        assert self.uc.reg_read(UC_X86_REG_ESP) == stack
        assert tuple(self.uc.reg_read(register) for register in SAVED) == values
        return self.result


class WarehouseDescriptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SOURCE.is_file():
            raise unittest.SkipTest('Pinned proprietary Silver fixture is unavailable')
        cls.source = SOURCE.read_bytes()
        cls.candidate = patcher.patch(cls.source)

    def test_every_warehouse_purchase_displays_incremental_slots_at_two_bases(self):
        for base in (0x400000, 0x14000000):
            machine = Machine(self.candidate, base=base)
            for level, gain in enumerate((8, 8, 16, 32, 64, 128), 1):
                with self.subTest(base=base, level=level):
                    self.assertEqual(machine.run(1, level), str(gain))

    def test_cached_or_missing_xml_powers_cannot_display_zero(self):
        for powers in ((), (0,)*6, (8, 16)):
            machine = Machine(self.candidate, powers=powers)
            for level, gain in enumerate((8, 8, 16, 32, 64, 128), 1):
                with self.subTest(powers=powers, level=level):
                    self.assertEqual(machine.run(1, level), str(gain))

    def test_other_services_retain_original_total_power(self):
        for base in (0x400000, 0x14000000):
            machine = Machine(self.candidate, base=base)
            for level in range(1, 6):
                self.assertEqual(machine.run(2, level), str(level))

    def test_invalid_warehouse_levels_clear_the_description_value(self):
        machine = Machine(self.candidate)
        for level in (0, 7, 255):
            self.assertEqual(machine.run(1, level), '')

    def test_patch_changes_only_description_call_and_appended_section_headers(self):
        report = patcher.review(self.source, self.candidate)
        allowed = {i for row in report['changes'] for i in range(row['offset'], row['offset']+row['size'])}
        self.assertTrue(all(a == b or index in allowed for index, (a, b) in
                            enumerate(zip(self.source, self.candidate))))
        self.assertEqual(len(self.candidate)-len(self.source), patcher.SIZE)
        with self.assertRaises(ValueError):
            patcher.patch(self.source[:-1])
