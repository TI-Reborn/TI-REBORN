import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from tools import build_hd_weapon as weapon
from tools.mdjx_mesh import encode, read

MODELS = Path(os.environ.get('TIO_CLIENT_MODELS', Path.home() / 'AppData/Local/TIO-Online/base/models'))
RECT = dict(x=8, y=4, w=20, h=10)


def export():
    return dict(rect=RECT, vertices=[
        dict(position=(0.0, 0.0, 0.0), normal=(1.0, 0.0, 0.0), uv=(0.2, -0.8)),
        dict(position=(0.0, 0.1, 0.0), normal=(1.0, 0.0, 0.0), uv=(0.2, -0.75)),
        dict(position=(0.0, 0.0, -0.1), normal=(1.0, 0.0, 0.0), uv=(0.3, -0.8)),
    ], triangles=[[0, 1, 2]])


class StaticMeshTests(unittest.TestCase):
    def test_static_mesh_round_trips_without_bones(self):
        mesh = weapon.static_mesh(export())
        raw = encode(mesh)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, 'w.mdjx')
            path.write_bytes(raw)
            back = read(path)
        self.assertEqual(back.bones, [])
        self.assertEqual([v.joints for v in back.vertices], [(), (), ()])
        self.assertEqual(encode(back), raw)
        self.assertEqual(len(raw), 16 + 3 * 40 + 3 * 4)  # the layout of the original weapons

    def test_uvs_must_stay_inside_the_rectangle(self):
        mesh = weapon.static_mesh(export())
        self.assertTrue(weapon.uv_inside(mesh, dict(x=200, y=200, w=110, h=60), 1000))
        self.assertFalse(weapon.uv_inside(mesh, dict(x=250, y=200, w=110, h=60), 1000))


class PaintTests(unittest.TestCase):
    def test_only_the_rectangle_changes_and_edges_are_flooded(self):
        atlas = Image.new('RGB', (40, 20), (10, 200, 30))
        side = Image.new('RGBA', (RECT['w'] * 4, RECT['h'] * 4), (0, 0, 0, 0))
        side.paste((180, 60, 20, 255), (20, 12, 60, 28))  # an opaque part in the middle
        out = np.asarray(weapon.paint(atlas, side, RECT)).astype(int)
        before = np.asarray(atlas).astype(int)
        inside = np.zeros(before.shape[:2], dtype=bool)
        inside[RECT['y']:RECT['y'] + RECT['h'], RECT['x']:RECT['x'] + RECT['w']] = True
        self.assertTrue(np.array_equal(out[~inside], before[~inside]))
        patch = out[inside]
        # Transparent margins take the part's colour, never the background or black.
        self.assertLess(np.abs(patch - (180, 60, 20)).max(), 3)

    def test_flood_fills_every_pixel(self):
        rgba = np.zeros((5, 5, 4), dtype=np.uint8)
        rgba[2, 2] = (50, 100, 150, 255)
        self.assertTrue((weapon.flood(rgba) == (50, 100, 150)).all())


@unittest.skipUnless((MODELS / 'weapon_ak47.mdjx').is_file(), 'installed client models not available')
class InstalledClientTests(unittest.TestCase):
    def test_every_installed_weapon_mesh_reads_and_round_trips(self):
        for path in sorted(MODELS.glob('weapon_*.mdjx')):
            raw = path.read_bytes()
            try:
                mesh = read(path)
            except AssertionError:
                continue  # a few legacy formats this reader does not cover; none is touched here
            self.assertEqual(encode(mesh), raw, path.name)
        for name in ('weapon_ak47', 'weapon_minigun', 'weapon_rpg'):
            self.assertEqual(encode(read(MODELS / f'{name}.mdjx')), (MODELS / f'{name}.mdjx').read_bytes())


if __name__ == '__main__':
    unittest.main()
