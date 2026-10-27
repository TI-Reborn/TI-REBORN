"""Item overlay sites are well-formed coordinate loads of the native centre."""
import unittest

from deploy import client_item_overlays as overlays

X, Y = '68fdffff', '64fdffff'  # [ebp-0x298], [ebp-0x29c]


class OverlaySiteTests(unittest.TestCase):
    def test_each_site_loads_the_native_centre(self):
        for site, original, register, edge, _ in overlays.SITES:
            raw = bytes.fromhex(original)
            self.assertIn(raw[2:6].hex(), (X, Y), hex(site))
            horizontal = raw[2:6].hex() == X
            self.assertEqual(edge in overlays.HORIZONTAL, horizontal, hex(site))

    def test_patches_fit_their_original_instructions(self):
        for (site, old, new), (_, original, *_rest) in zip(overlays.edits(0x89f800), overlays.SITES):
            self.assertEqual(old, bytes.fromhex(original))
            self.assertEqual(len(new), len(old))
            self.assertEqual(new[0], 0xe9)
            self.assertTrue(all(byte == 0x90 for byte in new[5:]))

    def test_sites_are_unique_and_do_not_overlap(self):
        spans = sorted((site, site+len(bytes.fromhex(original))) for site, original, *_ in overlays.SITES)
        for (start, end), (following, _) in zip(spans, spans[1:]):
            self.assertLessEqual(end, following)

    def test_texts_stay_inside_a_backpack_cell(self):
        # The smallest A2 cell is a 38 px backpack square.
        side = 38
        for _, _, _, edge, offset in overlays.SITES:
            if edge in (overlays.CENTRE_X, overlays.CENTRE_Y):
                continue
            if edge in (overlays.TOP, overlays.LEFT):
                self.assertLess(abs(offset), side//2)
            else:
                self.assertLessEqual(-offset, side, offset)

    def test_all_patched_spans_are_distinct(self):
        spans = sorted((site, site+len(old)) for site, old, _ in overlays.edits(0x89f800))
        self.assertEqual(len(spans), len(overlays.SITES)+len(overlays.GRID_FRAMES)+1)
        for (start, end), (following, _) in zip(spans, spans[1:]):
            self.assertLessEqual(end, following)

    def test_wear_images_are_centred_in_the_cell(self):
        centred = [(edge, offset) for _, _, _, edge, offset in overlays.SITES if edge in (overlays.CENTRE_X, overlays.CENTRE_Y)]
        self.assertEqual(len(centred), 8)
        for edge, offset in centred:
            self.assertEqual(-offset, (overlays.WEAR_WIDTH if edge == overlays.CENTRE_X else overlays.WEAR_HEIGHT)//2)


if __name__ == '__main__':
    unittest.main()
