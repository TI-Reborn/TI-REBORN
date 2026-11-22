"""UI font package: metrics the native adapter writes into ti.exe font records."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools import build_ui_font_metrics as builder
from tools.font_kerning import Kerning


class KerningTest(unittest.TestCase):
    def setUp(self):
        self.kern = Kerning(builder.PLEX.path)

    def test_known_latin_and_cyrillic_pairs_tighten(self):
        self.assertLess(self.kern.units(ord("A"), ord("V")), 0)
        self.assertLess(self.kern.units(ord("Т"), ord("о")), 0)

    def test_unknown_or_unkerned_pairs_are_zero(self):
        self.assertEqual(self.kern.units(0x10FFFF, ord("A")), 0)
        self.assertEqual(self.kern.units(ord("н"), ord("н")), 0)


class ShadowTest(unittest.TestCase):
    def test_shadow_is_black_under_white_ink(self):
        alpha = Image.new("L", (3, 3), 0)
        alpha.putpixel((0, 0), 255)
        cell = builder.shadowed(alpha, 1)
        self.assertEqual(cell.size, (4, 4))
        self.assertEqual(cell.getpixel((0, 0)), (255, 255, 255, 255))
        self.assertEqual(cell.getpixel((1, 1))[:3], (0, 0, 0))
        self.assertEqual(cell.getpixel((1, 1))[3], round(255 * builder.SHADOW_ALPHA))

    def test_empty_space_cell_stays_transparent(self):
        cell = builder.shadowed(Image.new("L", (1, 1), 0), 2)
        self.assertEqual(cell.size, (1, 1))
        self.assertEqual(cell.getpixel((0, 0))[3], 0)


class PackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.manifest = builder.build(cls.out)
        cls.roles = {role["font"]: role for role in cls.manifest["fonts"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_roles_follow_the_adapter_order(self):
        self.assertEqual(tuple(self.roles), tuple(role.name for role in builder.ROLES))

    def test_title_uses_tektur_on_native_pixel_lines(self):
        title, pixel = self.roles["title"], self.roles["pixel"]
        self.assertEqual(title["family"], "Tektur")
        self.assertEqual(title["native_xml"], "pixel")
        self.assertEqual(title["logical_line_metrics"], pixel["logical_line_metrics"])
        self.assertEqual(title["native_baseline"], pixel["native_baseline"])

    def test_every_original_glyph_is_kept_and_marks_are_added(self):
        for role in self.roles.values():
            native = {g["codepoint"] for g in builder.native_role(role["native_xml"])[1]}
            mine = {g["codepoint"] for g in role["glyphs"]}
            self.assertLessEqual(native, mine)
            self.assertIn(ord("–"), mine)
            self.assertIn(ord("«"), mine)
            self.assertLessEqual(len(mine), builder.GLYPH_LIMIT)

    def test_records_are_drawable_by_the_native_loops(self):
        for role in self.roles.values():
            for glyph in role["glyphs"]:
                self.assertGreaterEqual(glyph["advance"], 1)
                self.assertGreaterEqual(glyph["height"], 1)
                self.assertEqual(len(glyph["source_rects"]), len(builder.SCALES))

    def test_kerning_is_nonzero_and_fits_a_shortint(self):
        for role in self.roles.values():
            self.assertTrue(role["kerning"])
            for first, second, shift in role["kerning"]:
                self.assertNotEqual(shift, 0)
                self.assertTrue(-128 <= shift <= 127)

    def test_space_is_a_record_that_breaks_kerning(self):
        """Native loops keep the previous glyph across a record-less space; ours resets it."""
        for role in self.roles.values():
            space = next(g for g in role["glyphs"] if g["codepoint"] == 32)
            self.assertEqual(space["advance"], role["space_advance"])
            self.assertFalse([p for p in role["kerning"] if 32 in p[:2]])

    def test_native_width_matches_the_face(self):
        """Whole-pixel advances plus kerning stay within a few pixels of the face's own layout."""
        role = self.roles["pixel"]
        glyphs = {g["codepoint"]: g for g in role["glyphs"]}
        kerning = {(a, b): s for a, b, s in role["kerning"]}
        text = "Обмундирование и Автоматическое оружие"
        native = sum(glyphs[ord(c)]["advance"] for c in text)
        native += sum(kerning.get((ord(a), ord(b)), 0) for a, b in zip(text, text[1:]))
        face = builder.PLEX.font(role["uniform_font_pixel_size_100"], role["weight"])
        self.assertLessEqual(abs(native - face.getlength(text)), 6)

    def test_glyph_boxes_include_the_shadow(self):
        glyph = next(g for g in self.roles["pixel"]["glyphs"] if g["codepoint"] == ord("Ш"))
        rect_100 = glyph["source_rects"][0]
        self.assertEqual(glyph["visual_logical_box"][2:], rect_100[2:])

    def test_assets_match_the_manifest(self):
        for asset in self.manifest["assets"]:
            path = self.out / asset["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), asset["sha256"])
            if path.suffix == ".png":
                with Image.open(path) as image:
                    self.assertEqual((image.width, image.height), (asset["width"], asset["height"]))
                    self.assertEqual(image.mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
