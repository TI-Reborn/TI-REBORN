"""SC goods and rental shop page layouts are well formed (standard library only)."""
import unittest

from deploy import client_page_windows as pages
from deploy.client_shop_a2 import MINIMUM_PAGE

SIZES = ((1728, 768), (1408, 588), MINIMUM_PAGE)


class LayoutTests(unittest.TestCase):
    def test_every_box_stays_inside_the_page(self):
        for window in pages.WINDOWS:
            for width, height in SIZES:
                for index, (x, y, w, h) in pages.layout(window, width, height).items():
                    with self.subTest(window=window.name, size=(width, height), child=index):
                        self.assertGreaterEqual(min(x, y), 0)
                        self.assertLessEqual(y+h, height)
                        if index != 0:
                            self.assertLessEqual(x+w, width)

    def test_lists_keep_their_native_row_width_and_grow_in_height(self):
        for window in pages.WINDOWS:
            (index,) = window.scrolled
            page = pages.layout(window, 1728, 768)[index]
            native = window.natives[index]
            self.assertEqual(page[2], native[2])
            self.assertGreater(page[3], native[3])

    def test_native_layout_is_the_layout_at_the_native_size(self):
        """Restoring returns every laid-out child to its native box."""
        for window in pages.WINDOWS:
            self.assertEqual(set(window.natives), set(window.boxes))
            self.assertEqual(pages.layout(window, *window.native_size)[0], window.natives[0])

    def test_window_draw_slot_is_redirected(self):
        (site, before, after), = pages.edits(0x8d7000)
        self.assertEqual(site, pages.WINDOW_DRAW_SLOT)
        self.assertEqual(int.from_bytes(before, 'little'), pages.WINDOW_DRAW)
        self.assertEqual(int.from_bytes(after, 'little'), pages.BASE+0x8d7000+pages.DRAW)


if __name__ == '__main__':
    unittest.main()
