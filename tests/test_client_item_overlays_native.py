"""Overlay box and coordinate thunks execute in Unicorn."""
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
    UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

from deploy import client_item_overlays as overlays

ORIGIN, STATE = 0x89f800, 0x899000
RETURN = 0x3000ff00
CENTRE_X, CENTRE_Y = 500, 300
REGISTERS = {'eax': UC_X86_REG_EAX, 'ecx': UC_X86_REG_ECX, 'edx': UC_X86_REG_EDX}


class Machine:
    def __init__(self, scope, width=0, height=0):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(0x400000, 0x900000)
        self.uc.mem_map(0x30000000, 0x20000)
        self.uc.mem_write(0x400000+ORIGIN, overlays.payload(ORIGIN, STATE))
        for field, value in ((0, scope), (4, width), (8, height)):
            self.put(0x400000+STATE+field, value)

    def put(self, address, value):
        self.uc.mem_write(address, struct.pack('<i', value))

    def get(self, address):
        return struct.unpack('<i', self.uc.mem_read(address, 4))[0]

    def box(self, x, y):
        saved = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
        for register, value in zip(saved, (111, 222, 333, 444)):
            self.uc.reg_write(register, value)
        self.put(0x3000f000, RETURN)
        self.uc.reg_write(UC_X86_REG_EAX, x)
        self.uc.reg_write(UC_X86_REG_EDX, y)
        self.uc.reg_write(UC_X86_REG_ESP, 0x3000f000)
        self.uc.emu_start(overlays.box_entry(ORIGIN), RETURN, count=1000)
        assert [self.uc.reg_read(r) for r in saved] == [111, 222, 333, 444]
        assert self.uc.reg_read(UC_X86_REG_EAX) == x and self.uc.reg_read(UC_X86_REG_EDX) == y
        return tuple(self.get(0x400000+STATE+field) for field in
                     (overlays.LEFT, overlays.TOP, overlays.RIGHT, overlays.BOTTOM))

    def coordinate(self, index):
        """Run one thunk from its site with the native frame; return the register."""
        site, original, register, _, _ = overlays.SITES[index]
        frame = 0x30008000
        self.put(frame-0x298, CENTRE_X)
        self.put(frame-0x29c, CENTRE_Y)
        self.uc.reg_write(UC_X86_REG_EBP, frame)
        self.uc.reg_write(UC_X86_REG_EBX, 111)
        self.uc.reg_write(UC_X86_REG_ESP, 0x3000f000)
        resume = site+len(bytes.fromhex(original))
        self.uc.emu_start(0x400000+ORIGIN+overlays.BOX_SIZE+index*overlays.THUNK, resume, count=100)
        assert self.uc.reg_read(UC_X86_REG_EBX) == 111
        assert self.uc.reg_read(UC_X86_REG_ESP) == 0x3000f000
        return self.uc.reg_read(REGISTERS[register])


def native_value(original, centre):
    raw = bytes.fromhex(original)
    if len(raw) == 6:
        return centre
    immediate = raw[8]
    return centre-immediate if raw[7] in (0xe8, 0xe9, 0xea) else centre+immediate


class BoxTests(unittest.TestCase):
    def test_warehouse_tile_is_the_72_px_square(self):
        self.assertEqual(Machine(1).box(100, 50), (104-36, 70-36, 104+36, 70+36))

    def test_equipment_slot_keeps_its_caption_row(self):
        # Native slot position: (left+32, top+16) of a 196x76 slot at (200, 400).
        box = Machine(2, 196, 76).box(232, 416)
        self.assertEqual(box, (204, 403, 392, 456))

    def test_backpack_square_follows_the_cell_height(self):
        box = Machine(3, 94, 56).box(332, 216)
        self.assertEqual(box, (347-26, 228-26, 347+26, 228+26))

    def test_no_scope_leaves_the_box_untouched(self):
        machine = Machine(0)
        self.assertEqual(machine.box(1, 2), (0, 0, 0, 0))


class ThunkTests(unittest.TestCase):
    def test_a2_scopes_measure_from_the_box(self):
        machine = Machine(1)
        left, top, right, bottom = machine.box(CENTRE_X-4, CENTRE_Y-20)
        edges = {overlays.LEFT: left, overlays.TOP: top, overlays.RIGHT: right, overlays.BOTTOM: bottom,
                 overlays.CENTRE_X: (left+right)//2, overlays.CENTRE_Y: (top+bottom)//2}
        for index, (site, _, _, edge, offset) in enumerate(overlays.SITES):
            with self.subTest(site=hex(site)):
                self.assertEqual(machine.coordinate(index), edges[edge]+offset)

    def test_other_interfaces_keep_native_offsets(self):
        machine = Machine(0)
        for index, (site, original, _, edge, _) in enumerate(overlays.SITES):
            centre = CENTRE_X if edge in overlays.HORIZONTAL else CENTRE_Y
            with self.subTest(site=hex(site)):
                self.assertEqual(machine.coordinate(index), native_value(original, centre))

    def test_coordinates_stay_inside_the_tile(self):
        machine = Machine(1)
        left, top, right, bottom = machine.box(CENTRE_X-4, CENTRE_Y-20)
        for index, (_, _, _, edge, _) in enumerate(overlays.SITES):
            value = machine.coordinate(index)
            low, high = (left, right) if edge in overlays.HORIZONTAL else (top-2, bottom)
            self.assertTrue(low <= value <= high, (index, value))


class PayloadTests(unittest.TestCase):
    def test_payload_holds_every_thunk(self):
        raw = overlays.payload(ORIGIN, STATE)
        self.assertEqual(len(raw), overlays.SIZE)
        self.assertLessEqual(overlays.SLOT_FRAME_AT+0x80, overlays.SIZE)
        for index in range(len(overlays.SITES)):
            self.assertNotEqual(raw[overlays.BOX_SIZE+index*overlays.THUNK], 0)


class EditOwnershipTests(unittest.TestCase):
    def test_item_overlay_sites_do_not_overlap_other_a2_edits(self):
        from deploy import client_barracks_a2 as a2
        mine = {site for site, _, _ in overlays.edits(a2.OVERLAYS)}
        spans = sorted((site, site+len(before), site in mine) for site, before, _ in a2._presentation_edits())
        for (start, end, _), (following, _, _) in zip(spans, spans[1:]):
            self.assertLessEqual(end, following, hex(start))
        self.assertEqual(sum(1 for *_, own in spans if own), len(mine))


class FrameTests(unittest.TestCase):
    def run_grid(self, scope, index):
        machine = Machine(scope)
        site, original, _ = overlays.GRID_FRAMES[index]
        resume = site+len(bytes.fromhex(original))
        machine.uc.reg_write(UC_X86_REG_EBX, 111)
        machine.uc.reg_write(UC_X86_REG_ECX, 7)
        machine.uc.reg_write(UC_X86_REG_ESP, 0x3000f000)
        machine.uc.emu_start(0x400000+ORIGIN+overlays.GRID_FRAME_AT+index*overlays.THUNK, resume, count=100)
        self.assertEqual(machine.uc.reg_read(UC_X86_REG_EBX), 111)
        sp = machine.uc.reg_read(UC_X86_REG_ESP)
        pushed = [machine.get(sp+4*i) for i in range((0x3000f000-sp)//4)]
        return pushed, machine.uc.reg_read(UC_X86_REG_ECX)

    def test_warehouse_shade_and_upgrade_frame_cover_the_tile(self):
        pushed, _ = self.run_grid(1, 0)
        self.assertEqual(pushed[-1], overlays.SQUARE)
        _, width = self.run_grid(1, 1)
        self.assertEqual(width, overlays.SQUARE)
        pushed, _ = self.run_grid(1, 2)
        self.assertEqual(pushed[-1], overlays.SQUARE)
        self.assertEqual(pushed[0] & 0xffffffff, overlays.UPGRADE_FRAME)
        _, width = self.run_grid(1, 3)
        self.assertEqual(width, overlays.SQUARE)

    def test_other_lists_keep_native_sizes(self):
        self.assertEqual(self.run_grid(0, 0)[0][-1], 0x20)
        self.assertEqual(self.run_grid(0, 1)[1], 0x3e)
        self.assertEqual(self.run_grid(3, 2)[0][-1], 0x23)
        self.assertEqual(self.run_grid(2, 3)[1], 0x40)

    def test_equipment_upgrade_frame_outlines_the_whole_slot(self):
        machine = Machine(2, 196, 76)
        machine.box(232, 416)
        site, _, call = overlays.SLOT_FRAME
        machine.uc.reg_write(UC_X86_REG_EBX, 111)
        machine.uc.reg_write(UC_X86_REG_ESP, 0x3000f000)
        machine.uc.emu_start(0x400000+ORIGIN+overlays.SLOT_FRAME_AT, call, count=100)
        self.assertEqual(machine.uc.reg_read(UC_X86_REG_EBX), 111)
        self.assertEqual(machine.uc.reg_read(UC_X86_REG_ESP), 0x3000f000-16)
        self.assertEqual((machine.uc.reg_read(UC_X86_REG_EAX), machine.uc.reg_read(UC_X86_REG_EDX),
                          machine.uc.reg_read(UC_X86_REG_ECX)), (201, 401, 194))
        self.assertEqual(machine.get(0x3000f000-4), 74)
        self.assertEqual(machine.get(0x3000f000-12) & 0xffffffff, overlays.UPGRADE_FRAME)


if __name__ == '__main__':
    unittest.main()
