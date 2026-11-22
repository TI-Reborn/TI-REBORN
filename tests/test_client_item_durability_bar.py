import struct
import unittest

from deploy import client_item_durability_bar as bar
from deploy.client_login_window import MODE

try:
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
    from unicorn.x86_const import (
        UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_ECX, UC_X86_REG_EDI,
        UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
    )
except ImportError:
    Uc = None


@unittest.skipUnless(Uc, 'Unicorn is required for native durability checks')
class ItemDurabilityBarTests(unittest.TestCase):
    def draw(self, current, maximum, *, scope=2, item_type=1, excluded=0, backpack_cell=None,
             original=False):
        base, data = 0x51000000, 0x31000000
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(base, 0x900000)
        uc.mem_map(data, 0x10000)

        def va(address):
            return base + address - bar.BASE

        def words(address, *values):
            uc.mem_write(address, struct.pack(f'<{len(values)}I', *values))

        ebp, esp = data + 0x1000, data + 0x3000
        metadata, link = data + 0x6000, data + 0x5000
        words(link, metadata)
        uc.mem_write(metadata + 0x118, struct.pack('<H', item_type))
        uc.mem_write(metadata + 0x68b, bytes([excluded]))
        uc.mem_write(ebp - 0x248, struct.pack('<HH', current, maximum))
        words(ebp - 0x298, 120)
        words(ebp - 0x29c, 200)
        words(base + MODE, int(original))
        words(base + bar.ART_STATE, scope)
        words(base + bar.ART_STATE + 8, 88)
        words(base + bar.ART_STATE + 0x10, 104, 160, 230, 232)
        words(base + bar.ART_STATE + 0x24, 151)
        words(base + bar.ART_STATE + 0x34, 190)
        if backpack_cell is not None:
            left, top, width, height = backpack_cell
            center_x, center_y = left + width//2, top + height//2
            art_left = center_x - (height-4)//2
            words(base + bar.ART_STATE + 4, width, height)
            words(base + bar.ART_STATE + 0x10, art_left, top)
            words(base + bar.ART_STATE + 0x30, center_x, center_y)
        registers = {UC_X86_REG_EBP: ebp, UC_X86_REG_ESP: esp, UC_X86_REG_EDI: 0,
                     UC_X86_REG_ESI: link, UC_X86_REG_EAX: 55, UC_X86_REG_EDX: 56, UC_X86_REG_ECX: 57}
        for reg, value in registers.items():
            uc.reg_write(reg, value)
        uc.mem_write(va(bar.ENTRY), bar.draw_code())
        draws = []

        def rectangle(uc, address, size, _):
            stack = uc.reg_read(UC_X86_REG_ESP)
            end, primitive, colour, mode, height = struct.unpack('<5I', uc.mem_read(stack, 20))
            self.assertEqual((primitive, mode), (0x102, 0))
            draws.append((uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_EDX),
                          uc.reg_read(UC_X86_REG_ECX), height, colour))
            # The original rectangle callback cleans its four stack arguments.
            uc.reg_write(UC_X86_REG_ESP, stack + 20)
            uc.reg_write(UC_X86_REG_EIP, end)

        uc.hook_add(UC_HOOK_CODE, rectangle, begin=va(0x4f2888), end=va(0x4f2888))
        if original:
            # The preserved stock JBE skips the original bar when durability is zero.
            uc.mem_write(va(bar.HOOK + 8), bytes.fromhex('0f860a010000'))
            original_body = va(bar.HOOK + 14)
            uc.hook_add(UC_HOOK_CODE, lambda uc, *_: uc.emu_stop(), begin=original_body, end=original_body)
        uc.emu_start(va(bar.ENTRY), va(bar.RESUME), count=1000)
        if original:
            self.assertEqual(uc.reg_read(UC_X86_REG_EIP), original_body if current else va(bar.RESUME))
        self.assertEqual({reg: uc.reg_read(reg) for reg in registers}, registers)
        return draws

    def test_original_interface_resumes_stock_bar_and_skips_broken_items(self):
        for current in (0, 1, 70):
            with self.subTest(current=current):
                self.assertEqual(self.draw(current, 100, original=True), [])

    def test_exact_thresholds_and_zero_remain_visible(self):
        for current, maximum, colour, expected_height in (
                (120, 100, 'green', 88), (70, 100, 'green', 61),
                (69, 100, 'yellow', 60), (40, 100, 'yellow', 35),
                (39, 100, 'orange', 34), (30, 100, 'red', 26),
                (0, 100, 'red', 2), (209, 300, 'yellow', 61)):
            with self.subTest(current=current, maximum=maximum):
                track, trough, fill = self.draw(current, maximum)
                self.assertEqual(track[:4], (104, 150, 6, 88))
                self.assertEqual(trough[:4], (105, 150, 4, 88))
                self.assertEqual(fill, (105, 238 - expected_height, 4, expected_height, bar.COLOURS[colour]))

    def test_full_durability_reaches_both_edges_of_each_cell_type(self):
        for scope, x, y, height in ((0, 90, 184, 32), (1, 104, 160, 72),
                                    (2, 104, 150, 88)):
            with self.subTest(scope=scope):
                track, trough, fill = self.draw(100, 100, scope=scope, item_type=9)
                self.assertEqual(track[:4], (x, y, 6, height))
                self.assertEqual(fill, (x + 1, y, 4, height, bar.COLOURS['green']))

    def test_backpack_bar_stays_inside_the_left_edge_of_each_cell(self):
        for width, height in ((69, 42), (94, 56)):
            for column, current in enumerate((100, 70, 40, 0)):
                for row in (0, 4):
                    left, top = 147 + column*(width+6), 399 + row*(height+6)
                    with self.subTest(width=width, column=column, row=row, current=current):
                        track, trough, fill = self.draw(
                            current, 100, scope=3, backpack_cell=(left, top, width, height),
                        )
                        self.assertEqual(track[:4], (left+2, top+1, 5, height-2))
                        self.assertEqual(trough[:4], (left+3, top+1, 3, height-2))
                        self.assertEqual((fill[0], fill[2]), (left+3, 3))
                        self.assertGreaterEqual(fill[1], top+1)
                        self.assertEqual(fill[1]+fill[3], top+height-1)

    def test_backpack_bar_is_skipped_if_the_frame_cannot_contain_it(self):
        for width, height in ((7, 42), (69, 7)):
            with self.subTest(width=width, height=height):
                self.assertEqual(self.draw(100, 100, scope=3, backpack_cell=(147, 399, width, height)), [])

    def test_consumables_placeholder_and_non_durable_objects_have_no_bar(self):
        for options in (dict(item_type=0), dict(excluded=1), dict()):
            maximum = 100 if options else 1
            self.assertEqual(self.draw(0, maximum, **options), [])
