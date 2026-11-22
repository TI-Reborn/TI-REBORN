import struct
import unittest

from deploy import client_barracks_equipment as client

try:
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
    from unicorn.x86_const import (
        UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESP,
    )
except ImportError:
    Uc = None

slot_rects = client.slot_rects


class BarracksEquipmentLayoutTests(unittest.TestCase):
    def test_armor_fits_between_equipment_and_model_above_navigation(self):
        for left in (330, 430):
            for height in (544, 639, 640, 682):
                with self.subTest(left=left, height=height):
                    armor = slot_rects(left, height)[:3]
                    self.assertTrue(all(slot.x == armor[0].x > left for slot in armor))
                    self.assertTrue(all(a.y + a.height + 18 < b.y for a, b in zip(armor, armor[1:])))
                    self.assertLessEqual(armor[-1].y + armor[-1].height + 18, height - 112 - 76)
                    self.assertGreater(armor[0].width, 110 if left == 430 else 84)
                    self.assertGreater(armor[0].height, 76 if left == 430 else 56)

    def test_weapon_captions_fit_between_the_wider_slots_and_the_device(self):
        for left in (330, 430):
            with self.subTest(left=left):
                primary, secondary, device = slot_rects(left, 544)[3:]
                self.assertEqual(primary.x, secondary.x)
                self.assertEqual(primary.width, left - 36)
                self.assertEqual(secondary.width, primary.width)
                self.assertGreater(primary.height, 76 if left == 430 else 56)
                self.assertLessEqual(primary.y + primary.height + 18, secondary.y)
                self.assertLessEqual(secondary.y + secondary.height + 18, device.y)
                self.assertLessEqual(device.y + device.height, 310 if left == 430 else 228)


@unittest.skipUnless(Uc, 'Unicorn is required for native barracks checks')
class BarracksEquipmentNativeTests(unittest.TestCase):
    def setUp(self):
        self.base = 0x51000000
        self.data = 0x30000000
        self.stop = self.data + 0xf00
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(self.base, 0x900000)
        self.uc.mem_map(self.data, 0x10000)

    def mapped(self, original):
        return self.base + original - client.BASE

    def words(self, address, *values):
        self.uc.mem_write(address, struct.pack(f'<{len(values)}I', *values))

    def run_code(self, address, *, unwind_layout=False, ebx=None):
        stack = self.data + 0x7000
        if unwind_layout:
            self.words(stack, self.base, 0, 0, 0, 0, 0, 0, 0, 2, self.stop)
        else:
            self.words(stack, self.stop)
        self.uc.reg_write(UC_X86_REG_EBX, self.base if ebx is None else ebx)
        self.uc.reg_write(UC_X86_REG_ESP, stack)
        self.uc.emu_start(self.mapped(address), self.stop, count=1000)
        self.assertEqual(self.uc.reg_read(UC_X86_REG_ESP), stack + (40 if unwind_layout else 4))

    def test_reflow_moves_owned_hitboxes_and_leaves_small_and_original_ui_alone(self):
        code, table = client._layout_code()
        self.uc.mem_write(self.mapped(client.LAYOUT_ENTRY), code)
        self.uc.mem_write(self.mapped(client.LAYOUT_TABLE), table)
        owner, root, vector, items = (self.data + n for n in (0x100, 0x200, 0x300, 0x400))
        self.words(self.mapped(client.LEFT), owner)
        self.words(owner + 0x2c, vector)
        self.words(owner + 0x4c, root)
        self.words(vector + 4, items, 27)
        children = [self.data + 0x1000 + i * 0x100 for i in range(27)]
        self.words(items, *children)
        for active, width, height, panel, owner_width in (
                (1, 1200, 544, 330, 732), (1, 1500, 700, 330, 932),
                (1, 1600, 544, 430, 956), (1, 2100, 682, 430, 1136),
                (0, 1920, 682, 430, 1200)):
            with self.subTest(active=active, width=width, height=height):
                self.words(self.base + client.STATE, active)
                self.words(root + 0x38, width, height)
                self.words(owner + 0x38, owner_width)
                for child in children:
                    self.words(child + 0x30, 10, 10, 384, 18)
                self.run_code(client.LAYOUT_ENTRY, unwind_layout=True)

                def rect(index):
                    return client.Rect(*struct.unpack('<4I', self.uc.mem_read(children[index] + 0x30, 16)))

                self.assertEqual(rect(0), client.Rect(10, 10, 384, 18))
                if not active:
                    self.assertEqual(rect(8), client.Rect(10, 10, 384, 18))
                    self.assertEqual(rect(2), client.Rect(10, 10, 384, 18))
                    continue
                slots = slot_rects(panel, height)
                for indices, slot in zip(client.SLOT_CHILDREN, slots, strict=True):
                    self.assertTrue(all(rect(i) == slot for i in indices))
                model = rect(2)
                self.assertGreaterEqual(model.x, slots[0].x + slots[0].width + 14)
                self.assertLessEqual(model.x + model.width, owner_width - 12)
                self.assertGreater(model.x + model.width // 2, (panel + owner_width) // 2)

    def test_draw_size_scales_wide_art_proportionally_and_preserves_other_scopes(self):
        self.uc.mem_write(self.mapped(client.ICON_SIZE), client._icon_size())
        self.uc.mem_write(self.mapped(client.ICON_RADII), struct.pack('<HH', 225, 90))
        row = self.base + client.ART_ROWS
        for state, width, height, art, expected in (
                (1, 72, 72, row, 72), (3, 84, 42, row, 38),
                (2, 104, 86, row, 88), (2, 294, 64, row + 32, 158),
                (2, 394, 88, row + 32, 226), (2, 394, 108, row + 32, 244)):
            with self.subTest(state=state, width=width, height=height):
                self.words(self.base + client.ART_STATE, state, width, height, art)
                self.run_code(client.ICON_SIZE)
                self.assertEqual(self.uc.reg_read(UC_X86_REG_EDX), expected)

    def test_rotation_paint_and_hitboxes_follow_tabs_when_model_moves(self):
        renderer, model, owner, tabs = (self.data + offset for offset in (0x100, 0x200, 0x300, 0x400))
        self.words(renderer + 0xc, model)
        self.words(model + 0x4c, owner)
        self.words(self.mapped(client.LEFT), owner)
        self.words(self.mapped(client.TABS), tabs)
        self.words(tabs + 0x30, 500, 600, 400, 56)
        self.words(self.base + client.ARROW_DX, 208)
        self.uc.mem_write(self.mapped(0xa4211c), bytes.fromhex('8b4030 c3'))
        self.uc.reg_write(UC_X86_REG_EDI, renderer)
        for index, (site, stock, _) in enumerate(client.ARROWS):
            address = client.NAVIGATION + index * 0x100
            self.uc.mem_write(self.mapped(address), client._rotation_arrow(index))
            self.uc.mem_write(self.mapped(site + len(bytes.fromhex(stock))), b'\xc3')
            for active, expected in ((1, (908, 492, 908, 460)),
                                     (0, (803, 757, 803, 725))):
                with self.subTest(index=index, active=active):
                    self.words(self.base + client.STATE, active)
                    self.uc.reg_write(UC_X86_REG_EDX, 700)
                    self.run_code(address, ebx=780)
                    self.assertEqual(self.uc.reg_read(UC_X86_REG_EAX), expected[index])
                    self.assertEqual(self.uc.reg_read(UC_X86_REG_EDX), 700)
                    self.assertEqual(self.uc.reg_read(UC_X86_REG_EBX), 780)
