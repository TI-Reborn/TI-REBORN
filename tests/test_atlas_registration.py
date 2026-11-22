import unittest

import numpy as np
from PIL import Image

from tools import atlas_registration as reg


def textured(size, seed):
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 255, (size // 4, size // 4, 3), dtype=np.uint8)
    return Image.fromarray(noise).resize((size, size), Image.Resampling.BICUBIC)


class RegisterTests(unittest.TestCase):
    def setUp(self):
        # A 64 px "original" with one textured island; the "HD" atlas carries
        # the same island shrunk to 0.8 around the top-left corner (as the
        # image generator did) and drawn at 4x resolution.
        self.original = Image.new('RGB', (64, 64), (90, 90, 90))
        self.original.paste(textured(24, 1), (30, 26))
        self.chart = np.zeros((64, 64), dtype=bool)
        self.chart[26:50, 30:54] = True
        big = self.original.resize((256, 256), Image.Resampling.BICUBIC)
        self.hd = Image.new('RGB', (256, 256), (40, 30, 20))
        self.hd.paste(big.resize((205, 205), Image.Resampling.BICUBIC), (0, 0))

    def test_finds_scale_and_shift_of_a_moved_island(self):
        place = reg.register(self.original, self.hd, self.chart, 64, scales=reg.SCALES, search=16)
        self.assertAlmostEqual(place.scale, 0.8, delta=0.03)
        self.assertAlmostEqual(place.dx, -0.2 * 42, delta=1.5)  # island centre x = 42
        self.assertAlmostEqual(place.dy, -0.2 * 38, delta=1.5)  # island centre y = 38
        self.assertGreater(place.score, 0.8)

    def test_in_place_check_reports_the_drift(self):
        place = reg.register(self.original, self.hd, self.chart, 64, scales=(1.0,), search=1)
        self.assertLess(place.score, 0.5)

    def test_compose_keeps_original_colours_and_layout(self):
        place = reg.register(self.original, self.hd, self.chart, 64, scales=reg.SCALES, search=16)
        out = np.asarray(reg.compose(self.original, self.hd, [self.chart], [place], reg.MIN_SCORE, 256), dtype=float)
        base = np.asarray(self.original.resize((256, 256), Image.Resampling.BICUBIC), dtype=float)
        inside = np.zeros((256, 256), dtype=bool)
        inside[112:192, 128:208] = True
        # Same mean colour as the original island and well correlated with it.
        self.assertLess(np.abs(out[inside].mean(0) - base[inside].mean(0)).max(), 4)
        corr = np.corrcoef(out[inside].ravel(), base[inside].ravel())[0, 1]
        self.assertGreater(corr, 0.9)
        # Outside the island nothing changes.
        self.assertTrue(np.allclose(out[:40, :40], base[:40, :40], atol=1))

    def test_poor_match_keeps_the_upscaled_original(self):
        weak = reg.Placement(1.0, 0.0, 0.0, reg.MIN_SCORE - 0.1)
        out = np.asarray(reg.compose(self.original, self.hd, [self.chart], [weak], reg.MIN_SCORE, 256))
        base = np.asarray(self.original.resize((256, 256), Image.Resampling.BICUBIC))
        self.assertTrue(np.array_equal(out, base))


class ChartTests(unittest.TestCase):
    def test_islands_are_separate_components(self):
        mask = np.zeros((32, 32), dtype=np.uint8)
        mask[2:8, 2:8] = 255
        mask[20:30, 15:25] = 255
        charts = reg.islands(Image.fromarray(mask), 0)
        self.assertEqual(sorted(int(c.sum()) for c in charts), [36, 100])

    def test_output_padding_never_takes_a_neighbours_pixels(self):
        a = np.zeros((16, 16), dtype=bool)
        b = np.zeros((16, 16), dtype=bool)
        a[2:6, 2:6] = True
        b[2:6, 7:11] = True
        grown = reg.output_charts([a, b], 64, pad=6)
        self.assertFalse((grown[0] & grown[1]).any())
        self.assertTrue(grown[0][8:24, 8:24].all())
        self.assertTrue(grown[1][8:24, 28:44].all())


if __name__ == '__main__':
    unittest.main()
