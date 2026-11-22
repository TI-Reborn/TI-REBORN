import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from tools import build_combat_se_atlas as atlas


def lab(rgb):
    return atlas.rgb_to_lab(np.array([[rgb]], dtype=np.float64))[0, 0]


def recolor(rgb):
    return atlas.se_palette(np.array([[rgb]], dtype=np.uint8))[0, 0]


class ColourTests(unittest.TestCase):
    def test_lab_round_trip(self):
        colours = np.array([[[0, 0, 0], [255, 255, 255], [120, 80, 40], [200, 30, 30]]], dtype=np.uint8)
        back = atlas.lab_to_rgb(atlas.rgb_to_lab(colours.astype(np.float64)))
        self.assertLessEqual(int(np.abs(back.astype(int) - colours).max()), 1)

    def test_leather_becomes_grey_steel(self):
        leather = (140, 100, 65)
        before, after = lab(leather), lab(tuple(int(c) for c in recolor(leather)))
        self.assertLess(np.hypot(after[1], after[2]), 0.25 * np.hypot(before[1], before[2]))
        self.assertGreater(after[0], before[0])

    def test_dark_cloth_keeps_some_brown(self):
        cloth = (45, 32, 22)
        after = lab(tuple(int(c) for c in recolor(cloth)))
        self.assertGreater(after[2], 3)
        self.assertAlmostEqual(after[0], lab(cloth)[0], delta=1)

    def test_red_visor_is_kept(self):
        self.assertEqual(tuple(recolor((200, 25, 25))), (200, 25, 25))

    def test_skin_tone_is_not_an_accent(self):
        skin = (215, 140, 95)
        self.assertNotEqual(tuple(recolor(skin)), skin)


class BuildTests(unittest.TestCase):
    def test_build_keeps_combat_layout_and_mask(self):
        with tempfile.TemporaryDirectory() as folder:
            models, out = Path(folder, 'models'), Path(folder, 'out')
            models.mkdir()
            source = np.zeros((64, 64, 3), dtype=np.uint8)
            source[:32] = (140, 100, 65)  # leather island
            source[32:] = (80, 80, 82)  # steel island
            Image.fromarray(source).save(models / atlas.ATLAS, quality=100, subsampling=0)
            mask = Image.new('RGBA', (16, 16), (255, 255, 255, 0))
            mask.putpixel((3, 3), (255, 255, 255, 255))
            mask.save(models / atlas.MASK)

            report = atlas.build(models, out)

            built = Image.open(out / atlas.SE_ATLAS)
            self.assertEqual(built.size, (64, 64))
            self.assertEqual((out / atlas.SE_MASK).read_bytes(), (models / atlas.MASK).read_bytes())
            pixels = np.asarray(built.convert('RGB')).astype(int)
            top, bottom = pixels[:32].mean((0, 1)), pixels[32:].mean((0, 1))
            self.assertLess(top.max() - top.min(), 15)  # leather lost its brown
            self.assertGreater(top.mean(), bottom.mean())  # islands stay where they were
            saved = json.loads((out / 'combat-se-atlas.json').read_text(encoding='utf-8'))
            self.assertEqual(saved, report)
            self.assertEqual(saved['outputs'][atlas.SE_MASK], saved['source_mask_sha256'])


if __name__ == '__main__':
    unittest.main()
