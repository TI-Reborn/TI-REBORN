"""A2 shop layout and patch sites are well formed (standard library only)."""
import struct
import unittest

from deploy import client_shop_a2 as shop

ORIGIN, STATE = 0x8d0000, 0x89ff00
SIZES = ((1728, 768), (1408, 588), (1248, 588), (1200, 500))


def overlaps(a, b):
    return a.x < b.x+b.width and b.x < a.x+a.width and a.y < b.y+b.height and b.y < a.y+a.height


class LayoutTests(unittest.TestCase):
    def test_every_box_stays_inside_the_window(self):
        for width, height in SIZES:
            for warehouse in (False, True):
                for index, rect in shop.layout(width, height, warehouse=warehouse).items():
                    with self.subTest(size=(width, height), warehouse=warehouse, child=index):
                        self.assertGreaterEqual(rect.x, 0)
                        self.assertGreaterEqual(rect.y, 0)
                        if index != shop.CLOSE:
                            self.assertLessEqual(rect.x+rect.width, width)
                        self.assertLessEqual(rect.y+rect.height, height)

    def test_main_controls_do_not_overlap(self):
        main = (shop.FILTERS, shop.LIST, shop.SWITCH, shop.BAG, shop.BUY, shop.PREVIOUS, shop.MODEL, shop.WEIGHT)
        for width, height in SIZES:
            for warehouse in (False, True):
                rects = shop.layout(width, height, warehouse=warehouse)
                present = [i for i in main if i in rects]
                for a in present:
                    for b in present:
                        if a < b:
                            with self.subTest(size=(width, height), pair=(a, b)):
                                self.assertFalse(overlaps(rects[a], rects[b]))

    def test_catalogue_keeps_its_native_row_width(self):
        for width, height in SIZES:
            self.assertEqual(shop.layout(width, height, warehouse=False)[shop.LIST].width, shop.LIST_WIDTH)

    def test_warehouse_view_takes_the_whole_right_area(self):
        soldier = shop.layout(1728, 768, warehouse=False)[shop.BAG]
        stock = shop.layout(1728, 768, warehouse=True)[shop.BAG]
        self.assertGreater(stock.width, soldier.width)
        self.assertEqual(stock.x+stock.width, 1728-shop.MARGIN)

    def test_wide_pages_put_the_backpack_beside_the_soldier(self):
        wide = shop.layout(shop.wide_from(), 600, warehouse=False)
        narrow = shop.layout(shop.wide_from()-1, 600, warehouse=False)
        self.assertEqual(wide[shop.BAG].y, wide[shop.PREVIOUS].y)
        self.assertGreater(narrow[shop.BAG].y, narrow[shop.SOLDIER_NAME].y)

    def test_soldier_only_controls_leave_the_warehouse_layout(self):
        stock = shop.layout(1728, 768, warehouse=True)
        for index in shop.SOLDIER_ONLY:
            self.assertNotIn(index, stock)

    def test_fitting_room_moves_as_one_group(self):
        rects = shop.layout(1728, 768, warehouse=False)
        dx, dy = shop.fitting_offset()
        for index in shop.FITTING:
            native = shop.NATIVE[index]
            self.assertEqual((rects[index].x-native[0], rects[index].y-native[1]), (dx, dy))

    def test_banners_fit_beside_the_switch_on_the_smallest_page(self):
        room = shop.MINIMUM_PAGE[0] - shop.right_x() - shop.SWITCH_WIDTH - 14 - shop.MARGIN
        for banner in shop.BANNERS:
            self.assertLessEqual(len(banner)*8, room, banner)

    def test_native_layout_covers_every_laid_out_child(self):
        for warehouse in (False, True):
            self.assertLessEqual(set(shop.layout(1728, 768, warehouse=warehouse)), set(shop.NATIVE))


class PatchTests(unittest.TestCase):
    def test_owner_sites_jump_to_their_thunks(self):
        edits = shop.edits(ORIGIN)[:len(shop.OWNER_SITES)]
        for index, (site, before, after) in enumerate(edits):
            self.assertEqual(before, bytes.fromhex(shop.OWNER_CODE))
            self.assertEqual(len(after), len(before))
            self.assertEqual(after[0], 0xe9)
            target = site+5+struct.unpack('<i', after[1:5])[0]
            self.assertEqual(target, shop.BASE+ORIGIN+shop.OWNER_ENTRY+index*0x100)

    def test_refresh_sites_wrap_their_native_calls(self):
        start = len(shop.OWNER_SITES)
        edits = shop.edits(ORIGIN)[start:start+len(shop.REFRESH_SITES)]
        for (site, before, after), (expected, native) in zip(edits, shop.REFRESH_SITES, strict=True):
            self.assertEqual(site, expected)
            self.assertEqual(site+5+struct.unpack('<i', before[1:5])[0], native)
            self.assertEqual(after[0], 0xe8)

    def test_native_layout_jumps_to_its_wrapper(self):
        site, before, after = shop.edits(ORIGIN)[-1]
        self.assertEqual((site, before), (shop.NATIVE_LAYOUT, bytes.fromhex(shop.NATIVE_LAYOUT_PROLOGUE)))
        self.assertEqual(after[0], 0xe9)
        self.assertEqual(site+5+struct.unpack('<i', after[1:5])[0], shop.BASE+ORIGIN+shop.LAYOUT_WRAPPER)
        self.assertTrue(all(byte == 0x90 for byte in after[5:]))

    def test_sites_are_distinct(self):
        spans = sorted((site, site+len(before)) for site, before, _ in shop.edits(ORIGIN))
        for (_, end), (start, _) in zip(spans, spans[1:]):
            self.assertLessEqual(end, start)


if __name__ == '__main__':
    unittest.main()
