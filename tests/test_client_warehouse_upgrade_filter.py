"""Execute the warehouse hooks against the relocated release image."""
from pathlib import Path
import struct
import unittest

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
    UC_X86_REG_EDX, UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from deploy.client_barracks_a2 import STATE
from deploy.client_ui_scale import INVENTORY_FOOTER

BASELINE = (Path(__file__).resolve().parents[1] /
            'reports/barracks-equipment-20261120/silver-barracks-chat-focus.dll')
IMAGE_BASE = 0x50000000
DELTA = IMAGE_BASE - 0x400000
MEMORY = 0x30000000
FRAME = MEMORY + 0x2000
STACK = MEMORY + 0x7000
STOP = MEMORY + 0x6000
PATHS = (
    (0x91597d, -4, -0xd, 0x9159bc, 0x915ad2),
    (0x917123, -8, -0x7c5, 0x917168, 0x917305),
)


@unittest.skipUnless(BASELINE.is_file(), 'Published warehouse DLL is needed for x86 execution')
class WarehouseUpgradeFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from deploy.client_warehouse_upgrade_filter import patch

        with pefile.PE(data=patch(BASELINE.read_bytes()), fast_load=True) as pe:
            cls.image = pe.get_memory_mapped_image()

    def setUp(self):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(IMAGE_BASE, (len(self.image)+4095) & ~4095)
        self.uc.mem_write(IMAGE_BASE, self.image)
        self.uc.mem_map(MEMORY, 0x8000)
        self.uc.reg_write(UC_X86_REG_ESP, STACK)
        self.uc.reg_write(UC_X86_REG_EBP, FRAME)

    def words(self, address, *values):
        self.uc.mem_write(address, struct.pack('<' + 'I' * len(values), *values))

    def run_to(self, start, *ends):
        def stop_at_branch(emulator, address, _size, _data):
            if address in ends:
                emulator.emu_stop()

        hook = self.uc.hook_add(UC_HOOK_CODE, stop_at_branch)
        self.uc.emu_start(start, 0, count=1000)
        self.uc.hook_del(hook)
        return self.uc.reg_read(UC_X86_REG_EIP)

    def test_upgrade_category_hides_zero_and_respects_native_search(self):
        for site, query, category, match, reject in PATHS:
            for selected, upgrade, has_text, expected in (
                (30, 0, True, reject), (30, 1, False, match),
                (30, 255, True, site + 6), (1, 0, False, match),
                (1, 1, True, site + 6),
            ):
                with self.subTest(site=hex(site), selected=selected, upgrade=upgrade):
                    item = MEMORY + 0x3000
                    self.words(FRAME + query, int(has_text))
                    self.uc.mem_write(FRAME + category, bytes((selected,)))
                    for offset in (item+0x4e, FRAME-0x252):
                        self.uc.mem_write(offset, bytes((upgrade,)))
                    self.uc.reg_write(UC_X86_REG_EDI, item)
                    self.uc.reg_write(UC_X86_REG_EBX, 1)
                    self.uc.reg_write(UC_X86_REG_EAX, 0x11223344)
                    result = self.run_to(site+DELTA, match+DELTA, reject+DELTA, site+6+DELTA)
                    self.assertEqual(result, expected+DELTA)
                    self.assertEqual(self.uc.reg_read(UC_X86_REG_EBX), int(expected != reject))
                    self.assertEqual(self.uc.reg_read(UC_X86_REG_ESP), STACK)
                    self.assertEqual(self.uc.reg_read(UC_X86_REG_EAX), 0x11223344)

    def test_new_menu_row_uses_native_add_and_utf16_caption(self):
        menu = MEMORY + 0x3200
        self.uc.reg_write(UC_X86_REG_ESI, menu)
        endpoint = 0x6cc718 + DELTA
        self.assertEqual(self.run_to(0x6cbf1d + DELTA, endpoint), endpoint)
        self.assertEqual(self.uc.reg_read(UC_X86_REG_EAX), menu)
        self.assertEqual(self.uc.reg_read(UC_X86_REG_ECX), 0)
        caption = self.uc.reg_read(UC_X86_REG_EDX)
        length = struct.unpack('<I', self.uc.mem_read(caption-4, 4))[0]
        self.assertEqual(self.uc.mem_read(caption, length*2).decode('utf-16le'), 'Улучшения')
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        self.assertEqual(struct.unpack('<4I', self.uc.mem_read(esp, 16))[1:], (0, 30, 0xff519da6))

    def test_resize_keeps_menu_under_new_filter_button(self):
        table, menu = MEMORY + 0x3000, MEMORY + 0x3400
        anchor, continuation = INVENTORY_FOOTER + DELTA + 0x94, INVENTORY_FOOTER + DELTA + 0x9d
        self.uc.reg_write(UC_X86_REG_EAX, menu)
        self.uc.reg_write(UC_X86_REG_ESI, table)
        self.words(FRAME - 0x14, IMAGE_BASE)
        for mode, width, expected in ((1, 674, 0), (1, 1198, 0), (0, 674, 549)):
            with self.subTest(mode=mode, width=width):
                self.words(IMAGE_BASE + STATE, mode)
                self.words(table + 0x38, width)
                self.words(menu + 0x30, 549, 30)
                self.uc.reg_write(UC_X86_REG_EDX, 775)
                self.assertEqual(self.run_to(anchor, continuation), continuation)
                self.assertEqual(struct.unpack('<2I', self.uc.mem_read(menu + 0x30, 8)), (expected, 30))

    def test_native_sort_receives_descending_comparator_only_for_selected_menu(self):
        from deploy.client_warehouse_upgrade_filter import COMPARE

        warehouse, menu, collection, entries, entry, items = (
            MEMORY + offset for offset in (0x100, 0x500, 0x900, 0xa00, 0xb00, 0x3000))
        self.words(warehouse + 0xc, items)
        self.words(items - 4, 2)
        self.words(menu + 0x288, collection)
        self.words(collection + 4, entries, 1)
        self.words(entries, entry)
        self.words(STACK, STOP)
        stock = 0x9169f9 + DELTA
        sort = 0x7057a0 + DELTA
        for scope, holder in ((0, 0xac4bb4), (1, 0xac4998)):
            self.uc.mem_write(warehouse + 0x2d8, bytes((scope,)))
            self.words(holder + DELTA, menu)
            for category, selected, expected in ((30, 0, stock), (1, 1, stock), (30, 1, sort)):
                self.uc.mem_write(entry + 0xc, bytes((selected, category)))
                self.uc.reg_write(UC_X86_REG_ESP, STACK)
                self.uc.reg_write(UC_X86_REG_EAX, warehouse)
                self.assertEqual(self.run_to(0x9169f4 + DELTA, stock, sort), expected)
                if expected == sort:
                    self.assertEqual(self.uc.reg_read(UC_X86_REG_EAX), items)
                    self.assertEqual(self.uc.reg_read(UC_X86_REG_EDX), 1)
                    comparator = self.uc.reg_read(UC_X86_REG_ECX)
                    vtable = struct.unpack('<I', self.uc.mem_read(comparator, 4))[0]
                    self.assertEqual(struct.unpack('<I', self.uc.mem_read(vtable + 12, 4))[0],
                                     COMPARE + DELTA)

    def test_comparator_orders_unsigned_levels_descending(self):
        from deploy.client_warehouse_upgrade_filter import COMPARE

        left, right = MEMORY + 0x3000, MEMORY + 0x3300
        for a, b, expected in ((255, 11, -244), (1, 11, 10), (5, 5, 0)):
            self.uc.mem_write(left + 0x4e, bytes((a,)))
            self.uc.mem_write(right + 0x4e, bytes((b,)))
            self.uc.reg_write(UC_X86_REG_EDX, left)
            self.uc.reg_write(UC_X86_REG_ECX, right)
            self.uc.reg_write(UC_X86_REG_ESP, STACK)
            self.words(STACK, STOP)
            self.assertEqual(self.run_to(COMPARE + DELTA, STOP), STOP)
            self.assertEqual(self.uc.reg_read(UC_X86_REG_EAX), expected & 0xffffffff)
