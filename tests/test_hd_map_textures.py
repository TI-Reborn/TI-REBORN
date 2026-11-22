"""Compose HD map frames into native-size client sheets."""
from pathlib import Path
import io
import json
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_hd_map_textures import RESERVATION_GROUND, build, compose, hd_path, png_bytes  # noqa: E402
from tools.reservation_texture_ground import ground_double_density  # noqa: E402


class HdMapTextureTests(unittest.TestCase):
    def test_listed_frame_is_replaced_and_others_keep_client_art(self):
        original = Image.new('RGBA', (8, 4), (10, 20, 30, 255))
        hd = Image.new('RGBA', (32, 16), (0, 0, 0, 0))
        hd.paste((200, 100, 50, 255), (0, 0, 16, 16))
        result = compose(original, hd, [[0, 0, 4, 4]], 4)
        self.assertEqual(result.getpixel((1, 1)), (200, 100, 50, 255))
        self.assertEqual(result.getpixel((6, 1)), (10, 20, 30, 255))

    def test_transparent_hd_pixels_replace_alpha_without_dark_fringe(self):
        original = Image.new('RGBA', (4, 4), (10, 20, 30, 255))
        hd = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
        hd.paste((240, 240, 240, 255), (0, 0, 8, 16))
        result = compose(original, hd, [[0, 0, 4, 4]], 4)
        self.assertEqual(result.getpixel((3, 1))[3], 0)
        edge = result.getpixel((1, 1))
        self.assertGreater(edge[3], 200)
        self.assertGreater(min(edge[:3]), 200)

    def test_frame_past_the_sheet_edge_is_clipped(self):
        original = Image.new('RGBA', (4, 4), (1, 2, 3, 255))
        hd = Image.new('RGBA', (16, 16), (90, 90, 90, 255))
        result = compose(original, hd, [[2, 2, 4, 4], [8, 0, 2, 2]], 4)
        self.assertEqual(result.getpixel((3, 3)), (90, 90, 90, 255))
        self.assertEqual(result.getpixel((0, 0)), (1, 2, 3, 255))

    def test_wrong_hd_scale_is_rejected(self):
        with self.assertRaises(ValueError):
            compose(Image.new('RGBA', (4, 4)), Image.new('RGBA', (8, 8)), [[0, 0, 4, 4]], 4)

    def test_double_density_preserves_frame_rectangles_and_unused_pixels(self):
        original = Image.new('RGBA', (4, 2), (10, 20, 30, 255))
        hd = Image.new('RGBA', (16, 8), (0, 0, 0, 0))
        hd.paste((80, 100, 120, 255), (4, 0, 8, 8))
        result = compose(original, hd, [[1, 0, 1, 2]], 4, output_scale=2)
        self.assertEqual(result.size, (8, 4))
        self.assertEqual(result.getpixel((3, 3)), (80, 100, 120, 255))
        self.assertEqual(result.getpixel((4, 3)), (10, 20, 30, 255))
        self.assertEqual(png_bytes(result, output_scale=2)[33:41], b'\0\0\0\0tiOs')
        self.assertNotEqual(png_bytes(original)[33:41], b'\0\0\0\0tiOs')

    def test_ground_density_keeps_material_color_and_a_soft_native_mask(self):
        original = Image.new('RGBA', (4, 4), (50, 60, 70, 255))
        original.paste((50, 60, 70, 0), (0, 0, 1, 4))
        master = Image.new('RGBA', (8, 8), (160, 180, 200, 255))

        result = ground_double_density(original, master)

        self.assertEqual(result.size, (8, 8))
        self.assertEqual(result.getpixel((6, 6)), (50, 60, 70, 255))
        self.assertEqual(result.getchannel('A'), original.getchannel('A').resize(result.size, Image.Resampling.BILINEAR))

    def test_reservation_build_prefers_authored_ground_over_legacy_blend(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            assets, client, output = (root / part for part in ('assets', 'client', 'output'))
            index = {}
            for path in RESERVATION_GROUND:
                index[path] = dict(scale=2, frames=[[0, 0, 4, 4]])
                for target, size, color in (
                    (assets / 'hd' / path, (8, 8), (170, 100, 80, 117)),
                    (client / path, (4, 4), (20, 30, 40, 255)),
                ):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    Image.new('RGBA', size, color).save(target)
            (assets / 'hd/hd_index.json').write_text(json.dumps(index), encoding='utf-8')
            rows = build(assets, client, output, double_density_reservation=True)
            self.assertEqual({row['source'] for row in rows}, set(RESERVATION_GROUND))
            for row in rows:
                with Image.open(output / row['path']) as atlas:
                    self.assertEqual(atlas.getpixel((4, 4)), (170, 100, 80, 117))

    def test_double_density_marker_precedes_the_embedded_color_profile(self):
        atlas = Image.new('RGBA', (16, 8))
        atlas.info['icc_profile'] = b'profile'
        encoded = png_bytes(atlas, output_scale=2)
        self.assertEqual(encoded[33:41], b'\0\0\0\0tiOs')
        with Image.open(io.BytesIO(encoded)) as decoded:
            self.assertEqual(decoded.info['icc_profile'], b'profile')

    def test_selected_map_build_only_writes_requested_double_density_sheets(self):
        selected = 'base/setting/forest/selected.png'
        excluded = 'base/setting/forest/excluded.png'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            assets, client, output = (root / part for part in ('assets', 'client', 'output'))
            index = {path: dict(scale=4, frames=[[0, 0, 4, 4]]) for path in (selected, excluded)}
            source = assets / 'hd' / selected
            source.parent.mkdir(parents=True)
            (assets / 'hd/hd_index.json').write_text(json.dumps(index), encoding='utf-8')
            Image.new('RGBA', (16, 16), (88, 99, 77, 255)).save(source)
            (client / selected).parent.mkdir(parents=True)
            Image.new('RGBA', (4, 4), (1, 2, 3, 255)).save(client / selected)
            rows = build(assets, client, output, selected_map_paths=[selected])
            self.assertEqual([row['path'] for row in rows], [hd_path(selected, output_scale=2)])
            with Image.open(output / rows[0]['path']) as atlas:
                self.assertEqual(atlas.size, (8, 8))
                self.assertEqual(atlas.getpixel((0, 0)), (88, 99, 77, 255))

    def test_double_density_requires_higher_density_art(self):
        original = Image.new('RGBA', (4, 2), (255, 0, 0, 255))
        with self.assertRaisesRegex(ValueError, 'Unsupported output scale'):
            compose(original, original, [[0, 0, 4, 2]], 1, output_scale=2)

    def test_already_double_density_frame_keeps_exact_translucent_pixels(self):
        original = Image.new('RGBA', (4, 2), (4, 5, 6, 255))
        master = Image.new('RGBA', (8, 4), (173, 71, 19, 17))

        composed = compose(original, master, [[1, 0, 1, 2]], 2, output_scale=2)

        self.assertEqual(composed.crop((2, 0, 4, 4)).tobytes(), master.crop((2, 0, 4, 4)).tobytes())

    def test_hd_path_is_outside_the_native_resolver_names(self):
        self.assertEqual(hd_path('base/setting/assault/Assault_v1.png'),
                         'base/hd/setting/assault/Assault_v1.png.hd')
        for bad in ('base/items/a.png', 'base/setting/../x.png', 'setting/a.png'):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                hd_path(bad)


if __name__ == '__main__':
    unittest.main()
