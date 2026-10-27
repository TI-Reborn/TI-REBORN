"""The displayed backpack and every native input loop use the same cells."""
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import (
    UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EDI,
    UC_X86_REG_ESP,
)

from deploy import client_barracks_bag as bag


class BackpackNativeGeometryTests(unittest.TestCase):
    def machine(self, width=414, enabled=True, owned=True):
        machine = Uc(UC_ARCH_X86, UC_MODE_32)
        machine.mem_map(0x400000, 0x900000)
        machine.mem_map(0x30000000, 0x10000)
        origin, state = 0x8c4000, 0x89ff00
        machine.mem_write(0x400000 + origin, bag.payload(origin, state))

        def put(address, value):
            machine.mem_write(address, struct.pack('<I', value & 0xffffffff))

        self.put = put
        self.get = lambda address: struct.unpack(
            '<I', machine.mem_read(address, 4))[0]
        self.frame, self.control = 0x30002000, 0x30004000
        put(0x400000 + state, int(enabled))
        put(bag.BAG, self.control if owned else self.control + 0x1000)
        put(self.control + 0x38, width)
        put(self.control + 0x3c, 1000)
        machine.reg_write(UC_X86_REG_EBP, self.frame)
        machine.reg_write(UC_X86_REG_EBX, self.control)
        machine.reg_write(UC_X86_REG_ESP, 0x3000f000)
        return machine, 0x400000 + origin

    def test_draw_hint_click_and_drag_wrap_after_the_fourth_cell(self):
        for width, cell_width in ((414, 94), (314, 69)):
            for index, (_, _, x_slot, y_slot, advance, _) in enumerate(bag.LOOPS):
                for column in range(4):
                    with self.subTest(width=width, loop=index, column=column):
                        machine, address = self.machine(width)
                        x = 3 + column * (cell_width + 6)
                        if x_slot is None:
                            machine.reg_write(UC_X86_REG_EDI, x)
                            self.put(self.frame + y_slot, 3)
                        else:
                            self.put(self.frame + x_slot, x)
                            machine.reg_write(UC_X86_REG_EDI, 3)
                        machine.emu_start(address + index * 0x400, advance,
                                          count=1000)
                        actual_x = (machine.reg_read(UC_X86_REG_EDI)
                                    if x_slot is None else self.get(self.frame + x_slot))
                        actual_y = (self.get(self.frame + y_slot) if y_slot is not None
                                    else machine.reg_read(UC_X86_REG_EDI))
                        self.assertEqual(actual_x, 3 if column == 3 else x + cell_width + 6)
                        self.assertEqual(actual_y, (65 if width==414 else 51) if column==3 else 3)
                        self.assertEqual(machine.reg_read(UC_X86_REG_EBX), self.control)
                        self.assertEqual(machine.reg_read(UC_X86_REG_ESP), 0x3000f000)

    def test_disabled_or_unrelated_list_keeps_native_cell_spacing(self):
        for enabled, owned in ((False, True), (True, False)):
            for index, (_, _, x_slot, y_slot, advance, _) in enumerate(bag.LOOPS):
                machine, address = self.machine(enabled=enabled, owned=owned)
                if x_slot is None:
                    machine.reg_write(UC_X86_REG_EDI, 3)
                    self.put(self.frame + y_slot, 3)
                else:
                    self.put(self.frame + x_slot, 3)
                    machine.reg_write(UC_X86_REG_EDI, 3)
                machine.emu_start(address + index * 0x400, advance, count=1000)
                actual_x = (machine.reg_read(UC_X86_REG_EDI) if x_slot is None
                            else self.get(self.frame + x_slot))
                self.assertEqual(actual_x, 69)

    def test_scroll_final_row_executes_both_sides_of_native_branch(self):
        for enabled in (False, True):
            for partial_row in (False, True):
                machine, address = self.machine(enabled=enabled)
                self.put(self.frame-4, 3)
                machine.mem_write(self.frame-5, bytes((int(partial_row),)))
                index = next(i for i, row in enumerate(bag.HITS)
                             if row[2] == 'scroll_last')
                machine.emu_start(address+0x1000+index*0x100,
                                  0x9bcb44, count=1000)
                self.assertEqual(self.get(self.frame-4),
                                 3+int(partial_row)*(62 if enabled else 37))

    def draw_background(self, index, width=414, enabled=True):
        """Enter a background draw with its native colour, frame and flags."""
        machine, address = self.machine(width, enabled)
        sp = 0x3000f000-12
        for offset, value in enumerate((0, 7, 0xff3090ff)):
            self.put(sp+4*offset, value)
        machine.reg_write(UC_X86_REG_ESP, sp)
        return machine, address+0x1000+index*0x100

    def backgrounds(self):
        rows = [i for i, row in enumerate(bag.HITS) if row[2] == 'background']
        self.assertEqual(len(rows), 2)
        return rows

    def test_backpack_backgrounds_fill_the_reference_cell(self):
        for index in self.backgrounds():
            for width, size in ((414, (94, 56)), (314, (69, 42))):
                with self.subTest(site=hex(bag.HITS[index][0]), width=width):
                    machine, entry = self.draw_background(index, width)
                    machine.emu_start(entry, bag.SCALED_DRAW, count=1000)
                    top = machine.reg_read(UC_X86_REG_ESP)
                    pushed = [self.get(top+4*i) for i in range(1, 6)]
                    self.assertEqual(pushed, [0, 0xff3090ff, 7, size[1], size[0]])
                    self.assertEqual(machine.reg_read(UC_X86_REG_EBX), self.control)

    def test_backpack_backgrounds_stay_native_elsewhere(self):
        for index in self.backgrounds():
            with self.subTest(site=hex(bag.HITS[index][0])):
                machine, entry = self.draw_background(index, enabled=False)
                machine.emu_start(entry, bag.NATIVE_DRAW, count=1000)
                top = machine.reg_read(UC_X86_REG_ESP)
                self.assertEqual([self.get(top+4*i) for i in range(1, 4)],
                                 [0, 7, 0xff3090ff])

    def test_background_sites_call_the_native_draw(self):
        for index in self.backgrounds():
            site, original, _ = bag.HITS[index]
            raw = bytes.fromhex(original)
            self.assertEqual(site+5+struct.unpack('<i', raw[1:])[0], bag.NATIVE_DRAW)


if __name__ == '__main__':
    unittest.main()
