"""Warehouse filter toggle and skin execute in Unicorn with native fixtures."""
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

from deploy import client_barracks_warehouse as warehouse

ORIGIN, STATE, OPEN = 0x89a000, 0x89ff00, 0x89ff08
TABLE_OBJECT, CHILDREN, VALUES = 0x30002000, 0x30003000, 0x30004000
RETURN = 0x3000ff00
SAVED = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)


class Machine:
    def __init__(self, enabled=1, opened=0):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(0x400000, 0x900000)
        self.uc.mem_map(0x30000000, 0x20000)
        self.uc.mem_write(0x400000+ORIGIN, warehouse.payload(ORIGIN, STATE, OPEN))
        self.put(0x400000+STATE, enabled)
        self.put(0x400000+OPEN, opened)
        self.put(warehouse.TABLE, TABLE_OBJECT)
        self.put(TABLE_OBJECT+0x2c, CHILDREN)
        self.put(CHILDREN+4, VALUES)
        self.put(CHILDREN+8, 17)
        self.children = []
        for index in range(17):
            child = 0x30005000+index*0x400
            self.put(VALUES+4*index, child)
            self.put(child+0x4c, TABLE_OBJECT)
            self.put(child+0x38, 150)
            self.put(child+0x3c, 28)
            self.uc.mem_write(child+0x49, b'\x01\x01')
            self.children.append(child)
        self.events = []
        self.uc.hook_add(UC_HOOK_CODE, self.native)

    def put(self, address, value):
        self.uc.mem_write(address, struct.pack('<I', value & 0xffffffff))

    def get(self, address):
        return struct.unpack('<I', self.uc.mem_read(address, 4))[0]

    def byte(self, address):
        return self.uc.mem_read(address, 1)[0]

    def returned(self, extra=0):
        sp = self.uc.reg_read(UC_X86_REG_ESP)
        self.uc.reg_write(UC_X86_REG_EIP, self.get(sp))
        self.uc.reg_write(UC_X86_REG_ESP, sp+4+extra)

    def native(self, uc, address, size, unused):
        if address in (warehouse.CLICK, warehouse.BUTTON_DRAW):
            self.events.append((address, uc.reg_read(UC_X86_REG_EAX)))
            self.returned()
        elif address in (0xa4211c, 0xa42140):
            uc.reg_write(UC_X86_REG_EAX, 100)
            self.returned()
        elif address == 0x4f2888:
            self.events.append(('fill',))
            self.returned(16)
        elif address == 0x67571c:
            pointer = uc.reg_read(UC_X86_REG_EAX)
            text = bytes(uc.mem_read(pointer, self.get(pointer-4))).decode('utf-16le')
            self.events.append(('text', text))
            self.returned(12)

    def run(self, entry, eax):
        for register, value in zip(SAVED, (111, 222, 333, 444)):
            self.uc.reg_write(register, value)
        self.put(0x3000f000, RETURN)
        self.uc.reg_write(UC_X86_REG_EAX, eax)
        self.uc.reg_write(UC_X86_REG_ESP, 0x3000f000)
        self.uc.emu_start(0x400000+entry, RETURN, count=50000)
        assert [self.uc.reg_read(r) for r in SAVED] == [111, 222, 333, 444]
        assert self.uc.reg_read(UC_X86_REG_ESP) == 0x3000f004


class ToggleTests(unittest.TestCase):
    def test_filter_button_opens_the_list_without_the_native_click(self):
        machine = Machine()
        machine.run(ORIGIN, machine.children[warehouse.TOGGLE])
        self.assertEqual(machine.get(0x400000+OPEN), 1)
        self.assertNotIn(warehouse.CLICK, [event[0] for event in machine.events])
        self.assertEqual(machine.byte(machine.children[warehouse.FILTERS]+0x49), 1)
        # The grid keeps its own state byte; +4A switches its display mode.
        self.assertEqual(machine.byte(machine.children[warehouse.GRID]+0x4a), 1)

    def test_second_press_closes_the_list(self):
        machine = Machine(opened=1)
        machine.run(ORIGIN, machine.children[warehouse.TOGGLE])
        self.assertEqual(machine.get(0x400000+OPEN), 0)
        self.assertEqual(machine.byte(machine.children[warehouse.FILTERS]+0x49), 0)
        self.assertEqual(machine.byte(machine.children[warehouse.FILTER_TOOL]+0x49), 0)

    def test_other_buttons_keep_their_native_click(self):
        machine = Machine()
        refresh = machine.children[11]
        machine.run(ORIGIN, refresh)
        self.assertEqual(machine.events, [(warehouse.CLICK, refresh)])
        self.assertEqual(machine.get(0x400000+OPEN), 0)

    def test_stock_layout_never_intercepts_the_button(self):
        machine = Machine(enabled=0)
        toggle = machine.children[warehouse.TOGGLE]
        machine.run(ORIGIN, toggle)
        self.assertEqual(machine.events, [(warehouse.CLICK, toggle)])


def list_rect(machine, x=0, y=30, width=200, height=300):
    filters = machine.children[warehouse.FILTERS]
    for offset, value in zip((0x30, 0x34, 0x38, 0x3c), (x, y, width, height)):
        machine.put(filters+offset, value)


def press(machine, entry, control, x, y):
    """A virtual input call with x in ECX, y on the stack (RET 4)."""
    for register, value in zip(SAVED, (111, 222, 333, 444)):
        machine.uc.reg_write(register, value)
    machine.put(0x3000f000, RETURN)
    machine.put(0x3000f004, y)
    machine.uc.reg_write(UC_X86_REG_EAX, control)
    machine.uc.reg_write(UC_X86_REG_ECX, x)
    machine.uc.reg_write(UC_X86_REG_ESP, 0x3000f000)
    machine.uc.emu_start(0x400000+entry, RETURN, count=50000)
    assert [machine.uc.reg_read(r) for r in SAVED] == [111, 222, 333, 444]
    assert machine.uc.reg_read(UC_X86_REG_ESP) == 0x3000f008


class OpenListInputTests(unittest.TestCase):
    def machine(self, opened=1):
        machine = Machine(opened=opened)
        list_rect(machine)
        original = {warehouse.GRID_DOWN[1], warehouse.FILTERS_DOWN[1]}

        def native(uc, address, size, unused):
            if address in original:
                machine.events.append((address, uc.reg_read(UC_X86_REG_EAX)))
                machine.returned(4)
        machine.uc.hook_add(UC_HOOK_CODE, native)
        return machine

    def test_grid_press_under_the_list_is_left_to_the_list(self):
        machine = self.machine()
        press(machine, ORIGIN+0x500, machine.children[warehouse.GRID], 50, 100)
        self.assertEqual(machine.get(0x400000+OPEN), 1)
        self.assertEqual(machine.events, [])

    def test_grid_press_outside_the_list_closes_it_without_acting(self):
        machine = self.machine()
        press(machine, ORIGIN+0x500, machine.children[warehouse.GRID], 400, 100)
        self.assertEqual(machine.get(0x400000+OPEN), 0)
        self.assertEqual(machine.byte(machine.children[warehouse.FILTERS]+0x49), 0)
        self.assertEqual(machine.events, [])

    def test_closed_list_keeps_the_native_grid_press(self):
        machine = self.machine(opened=0)
        grid = machine.children[warehouse.GRID]
        press(machine, ORIGIN+0x500, grid, 50, 100)
        self.assertEqual(machine.events, [(warehouse.GRID_DOWN[1], grid)])

    def test_choosing_a_category_runs_natively_then_closes_the_list(self):
        machine = self.machine()
        filters = machine.children[warehouse.FILTERS]
        press(machine, ORIGIN+0x600, filters, 50, 100)
        self.assertEqual(machine.events, [(warehouse.FILTERS_DOWN[1], filters)])
        self.assertEqual(machine.get(0x400000+OPEN), 0)

    def test_press_beside_the_list_keeps_it_open(self):
        machine = self.machine()
        filters = machine.children[warehouse.FILTERS]
        press(machine, ORIGIN+0x600, filters, 400, 100)
        self.assertEqual(machine.get(0x400000+OPEN), 1)


class ToggleDownTests(unittest.TestCase):
    def machine(self, enabled=1):
        machine = Machine(enabled=enabled)
        hooked = {warehouse.CONTROL_DOWN, warehouse.BUTTON_DOWN[1]}

        def native(uc, address, size, unused):
            if address in hooked:
                machine.events.append((address, uc.reg_read(UC_X86_REG_EAX), machine.get(uc.reg_read(UC_X86_REG_ESP)+4)))
                machine.returned(4)
        machine.uc.hook_add(UC_HOOK_CODE, native)
        return machine

    def test_filter_button_press_only_captures_the_mouse(self):
        machine = self.machine()
        toggle = machine.children[warehouse.TOGGLE]
        press(machine, ORIGIN+0x300, toggle, 10, 7)
        self.assertEqual(machine.events, [(warehouse.CONTROL_DOWN, toggle, 7)])

    def test_other_buttons_keep_their_press_action(self):
        machine = self.machine()
        refresh = machine.children[11]
        press(machine, ORIGIN+0x300, refresh, 10, 7)
        self.assertEqual(machine.events, [(warehouse.BUTTON_DOWN[1], refresh, 7)])

    def test_stock_layout_keeps_the_view_switch(self):
        machine = self.machine(enabled=0)
        toggle = machine.children[warehouse.TOGGLE]
        press(machine, ORIGIN+0x300, toggle, 10, 7)
        self.assertEqual(machine.events, [(warehouse.BUTTON_DOWN[1], toggle, 7)])


class EmptyCellTests(unittest.TestCase):
    """Empty-slot frames follow the native 72/76 px item wrap of the grid."""

    def cells(self, width, height):
        from deploy.client_item_icon_render import payload as items
        origin = 0x8a0000
        machine = Machine()
        machine.uc.mem_write(0x400000+origin, items(origin, STATE, (17, 30)))
        grid = machine.children[warehouse.GRID]
        machine.put(grid+0x38, width)
        machine.put(grid+0x3c, height)
        machine.run(origin+0x9800, grid)
        return sum(1 for event in machine.events if event == ('fill',))//2

    @staticmethod
    def native_columns(width):
        columns, x = 0, 3
        while x < width-16-72+1:
            columns += 1
            x += 76
        return columns

    def test_full_hd_column_frames_every_visible_column(self):
        self.assertEqual(self.native_columns(554), 7)
        self.assertEqual(self.cells(554, 444), 7*5)

    def test_compact_column_matches_its_items(self):
        self.assertEqual(self.cells(430, 306), self.native_columns(430)*4)


class DrawTests(unittest.TestCase):
    def owners(self, machine):
        panel, owner_children, owner_values = 0x30010000, 0x30011000, 0x30012000
        machine.put(warehouse.OWNERS, panel)
        machine.put(panel+0x2c, owner_children)
        machine.put(owner_children+4, owner_values)
        machine.put(owner_children+8, 3)
        buttons = []
        for index in range(3):
            button = 0x30013000+index*0x400
            machine.put(owner_values+4*index, button)
            machine.put(button+0x4c, panel)
            machine.put(button+0x38, 82)
            machine.put(button+0x3c, 28)
            machine.uc.mem_write(button+0x49, b'\x01\x01')
            buttons.append(button)
        return buttons

    def test_each_owner_tab_draws_its_caption_without_the_native_draw(self):
        for index, caption in enumerate(warehouse.OWNER_CAPTIONS):
            with self.subTest(caption=caption):
                machine = Machine()
                machine.run(ORIGIN+0x1000, self.owners(machine)[index])
                self.assertIn(('text', caption), machine.events)
                self.assertNotIn(warehouse.BUTTON_DRAW, [event[0] for event in machine.events])

    def test_filter_button_draws_its_own_frame(self):
        machine = Machine()
        machine.run(ORIGIN+0x1000, machine.children[warehouse.TOGGLE])
        self.assertIn(('fill',), machine.events)
        self.assertNotIn(warehouse.BUTTON_DRAW, [event[0] for event in machine.events])

    def test_settings_button_draws_a_compact_cog_inside_its_rect(self):
        machine = Machine()
        panel, tab_children, tab_values = 0x30014000, 0x30015000, 0x30016000
        machine.put(warehouse.TABS, panel)
        machine.put(panel+0x2c, tab_children)
        machine.put(tab_children+4, tab_values)
        machine.put(tab_children+8, 7)
        settings = 0x30017000
        machine.put(tab_values+4*warehouse.SETTINGS, settings)
        machine.put(settings+0x4c, panel)
        machine.put(settings+0x38, 15)
        machine.put(settings+0x3c, 15)
        machine.uc.mem_write(settings+0x49, b'\x01\x01')
        machine.run(ORIGIN+0x1000, settings)
        self.assertNotIn(warehouse.BUTTON_DRAW, [event[0] for event in machine.events])
        self.assertEqual(machine.events.count(('fill',)), 2+len(warehouse._runs(warehouse.COG)))
        width = max(len(row) for row in warehouse.COG)
        self.assertLessEqual(2+width, 15)

    def test_other_buttons_continue_to_the_native_draw(self):
        machine = Machine()
        refresh = machine.children[11]
        machine.run(ORIGIN+0x1000, refresh)
        self.assertEqual(machine.events, [(warehouse.BUTTON_DRAW, refresh)])


if __name__ == '__main__':
    unittest.main()
