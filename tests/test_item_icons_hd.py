"""HD item icon pipeline: classification, native mesh reading and framing."""
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest

from tools.item_icons_hd import catalog, framing, mesh

ROOT = Path(__file__).resolve().parents[1]


def mdjx(positions, triangles, *, bones=0):
    raw = bytearray(struct.pack('<4I', len(positions), 3 * len(triangles), bones, 1))
    for x, y, z in positions:
        influences = 1 if bones else 0
        raw += struct.pack('<I8fI', influences, x, y, z, 0, 0, 1, 0.5, 0.5, 0)
        if influences:
            raw += struct.pack('<If', 0, 1.0)
    for triangle in triangles:
        raw += struct.pack('<3I', *triangle)
    return bytes(raw)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.items = {i.item_id: i for i in catalog.load()}

    def test_every_inventory_item_has_exactly_one_pipeline(self):
        self.assertTrue(all(i.pipeline in ('existing', 'render', 'redraw') for i in self.items.values()))
        for excluded in (0, 1, 2, 353, 65500, 65508, 65513):
            self.assertNotIn(excluded, self.items)

    def test_released_weapon_icons_are_reused(self):
        for item_id in (304, 327, 5013, 65489):
            self.assertEqual(self.items[item_id].pipeline, 'existing')

    def test_armor_renders_its_piece_without_the_hand_mesh(self):
        chest = self.items[210]
        self.assertEqual((chest.pipeline, chest.slot), ('render', 'body'))
        self.assertEqual(chest.models, ('man_armor_combat_light_chest',))
        self.assertEqual(chest.textures, ('armor_combat.jpg',))
        self.assertEqual(self.items[211].slot, 'head')
        self.assertEqual(self.items[212].slot, 'legs')

    def test_known_models_missing_from_the_catalogue_are_used(self):
        self.assertEqual(self.items[5002].models, ('man_item_nightvision',))
        self.assertEqual(self.items[5002].pipeline, 'render')

    def test_items_without_models_are_redrawn(self):
        for item_id in (17, 18, 19, 30, 9, 3):
            self.assertEqual(self.items[item_id].pipeline, 'redraw')

    def test_committed_manifest_matches_the_catalogue(self):
        committed = json.loads((ROOT / 'assets/item-icons-hd-v1/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(committed, catalog.manifest(catalog.load()))


class MeshTests(unittest.TestCase):
    TRIANGLE = ((0, 1, 0), (1, 1, 0), (0, 2, 0))

    def test_static_weapon_layout_without_bones(self):
        geometry = mesh.parse(mdjx(self.TRIANGLE, ((0, 1, 2),)))
        self.assertFalse(geometry.skinned)
        self.assertEqual(geometry.triangles, ((0, 1, 2),))
        self.assertEqual(geometry.positions[2], (0.0, 2.0, 0.0))

    def test_skinned_layout_with_bone_influences(self):
        geometry = mesh.parse(mdjx(self.TRIANGLE, ((0, 1, 2),), bones=1))
        self.assertTrue(geometry.skinned)
        self.assertEqual(geometry.uvs[0], (0.5, 0.5))

    def test_corrupt_files_are_rejected(self):
        good = mdjx(self.TRIANGLE, ((0, 1, 2),))
        for bad in (good[:10], good[:-4], mdjx(self.TRIANGLE, ((0, 1, 5),))):
            with self.assertRaises(ValueError):
                mesh.parse(bad)
        mismatched = bytearray(good)
        struct.pack_into('<I', mismatched, 8, 1)  # bones but no influences
        with self.assertRaises(ValueError):
            mesh.parse(bytes(mismatched))

    def test_reads_from_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'w.mdjx'
            path.write_bytes(mdjx(self.TRIANGLE, ((0, 1, 2),)))
            self.assertEqual(len(mesh.read(path).positions), 3)


class FramingTests(unittest.TestCase):
    CUBE = [(x, y, z) for x in (-.2, .3) for y in (1.1, 1.9) for z in (-.1, .15)]

    def test_y_up_native_points_become_z_up(self):
        self.assertEqual(framing.to_blender((1, 2, 3)), (1, -3, 2))

    def test_every_slot_fits_inside_the_margins(self):
        for slot in framing.VIEWS:
            for canvas in ((1024, 1024), (2048, 1024), (512, 1024)):
                frame = framing.frame(self.CUBE, slot, canvas)
                local = [tuple(a - b for a, b in zip(framing.to_blender(p), frame.center)) for p in self.CUBE]
                width, height = framing.projected_extent(local, frame.yaw, frame.pitch)
                long_side = max(canvas)
                visible_w = frame.ortho_scale * canvas[0] / long_side
                visible_h = frame.ortho_scale * canvas[1] / long_side
                usable = 1 - 2 * framing.MARGIN
                self.assertLessEqual(width, visible_w * usable + 1e-9, (slot, canvas))
                self.assertLessEqual(height, visible_h * usable + 1e-9, (slot, canvas))
                self.assertTrue(math.isclose(max(width / visible_w, height / visible_h), usable, rel_tol=1e-6))

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            framing.frame(self.CUBE, 'unknown')
        with self.assertRaises(ValueError):
            framing.frame([], 'head')
        with self.assertRaises(ValueError):
            framing.frame(self.CUBE, 'head', (0, 10))


try:
    import PIL  # noqa: F401
except ImportError:  # CI installs no third-party packages.
    PIL = None


@unittest.skipIf(PIL is None, 'Pillow is optional for the export step')
class ExportTests(unittest.TestCase):
    def test_all_sizes_keep_alpha_and_centre_the_item(self):
        from PIL import Image
        from tools.item_icons_hd import export
        with tempfile.TemporaryDirectory() as folder:
            master = Path(folder) / '17.png'
            image = Image.new('RGBA', (400, 300), (0, 0, 0, 0))
            image.paste((200, 120, 40, 255), (50, 100, 350, 200))
            image.save(master)
            written = export.export(master, Path(folder) / 'out', 'tio_ii_17')
            self.assertEqual(len(written), 8)
            for path in written:
                result = Image.open(path)
                self.assertEqual(result.mode, 'RGBA')
                left, top, right, bottom = result.getbbox()
                self.assertLessEqual(abs(left - (result.width - right)), 1)
            with self.assertRaises(ValueError):
                Image.new('RGBA', (8, 8)).save(master)
                export.export(master, Path(folder) / 'out', 'empty')


if __name__ == '__main__':
    unittest.main()
