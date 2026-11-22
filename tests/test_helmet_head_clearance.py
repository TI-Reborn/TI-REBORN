import os
import unittest
from pathlib import Path

import numpy as np

from tools import helmet_head_clearance as clearance
from tools.mdjx_mesh import Mesh, Vertex, encode, read

MODELS = Path(os.environ.get('TIO_CLIENT_MODELS', Path.home() / 'AppData/Local/TIO-Online/base/models'))


def vertex(position, normal):
    return Vertex(tuple(position), tuple(normal), (0.0, 0.0), 0, (0,), (1.0,))


def plate(z=0.0, size=0.04, cells=4, recess=0.0):
    """A shell sheet at depth z facing +z (back of the skull); the middle vertex is recessed."""
    vertices, indices = [], []
    step = 2 * size / cells
    for j in range(cells + 1):
        for i in range(cells + 1):
            middle = i == j == cells // 2
            vertices.append(vertex((-size + i * step, -size + j * step, z - (recess if middle else 0)), (0, 0, 1)))
    for j in range(cells):
        for i in range(cells):
            a = j * (cells + 1) + i
            indices += [a, a + 1, a + cells + 2, a, a + cells + 2, a + cells + 1]
    bones = [dict(name=clearance.BONE, parent=0, children=(), head=(0, 0, 0), tip=(0, 0, 1))]
    return Mesh(vertices, tuple(indices), bones, 1, b'')


def skin(points, normal=(0, 0, 1)):
    return Mesh([vertex(p, normal) for p in points], (0, 0, 0), [], 1, b'')


class ClipTests(unittest.TestCase):
    def clips(self, head, shell):
        return clearance.back_clips(clearance.positions(head), clearance.unit_normals(head),
                                    clearance.positions(shell), clearance.triangles(shell), clearance.facing(shell))

    def test_skin_outside_the_shell_clips_by_its_depth(self):
        depth, crossed = self.clips(skin([(0.005, 0.005, 0.006)]), plate())
        self.assertAlmostEqual(depth[0], 0.006, places=6)
        self.assertGreaterEqual(crossed[0], 0)

    def test_covered_skin_does_not_clip(self):
        depth, crossed = self.clips(skin([(0.005, 0.005, -0.006)]), plate())
        self.assertEqual((depth[0], crossed[0]), (0.0, -1))

    def test_shell_far_behind_the_skin_is_an_inner_part(self):
        depth, _ = self.clips(skin([(0.005, 0.005, clearance.REACH + 0.002)]), plate())
        self.assertEqual(depth[0], 0.0)

    def test_only_the_back_of_the_skull_is_checked(self):
        depth, _ = self.clips(skin([(0.005, 0.005, 0.006)], normal=(0, 1, 0.1)), plate())
        self.assertEqual(depth[0], 0.0)


class BulgeTests(unittest.TestCase):
    def test_full_push_at_source_and_none_beyond_radius(self):
        shell = np.array([[0, 0, 0], [0, 0, 0], [0.02, 0, 0], [0.2, 0, 0]], dtype=float)
        offset = clearance.bulge(shell, np.array([[0, 0, 0.0]]), np.array([[0, 0, 0.01]]), radius=0.05)
        self.assertTrue(np.allclose(offset[0], (0, 0, 0.01)))
        self.assertTrue(np.array_equal(offset[0], offset[1]))  # seam duplicates stay together
        self.assertTrue(0 < offset[2, 2] < 0.01)
        self.assertTrue(np.array_equal(offset[3], (0, 0, 0)))


class ClearBackTests(unittest.TestCase):
    def test_recessed_shell_is_pushed_clear_and_only_positions_change(self):
        helmet = plate(recess=0.008)
        head = skin([(x, y, 0.002) for x in (-0.01, 0, 0.01) for y in (-0.01, 0, 0.01)])
        fixed, report = clearance.clear_back(helmet, [head])
        self.assertGreater(report['max_clip_before_m'], 0.005)
        depth, _ = clearance.back_clips(clearance.positions(head), clearance.unit_normals(head),
                                        clearance.positions(fixed), clearance.triangles(fixed),
                                        clearance.facing(fixed))
        self.assertEqual(depth.max(), 0.0)
        self.assertEqual(fixed.indices, helmet.indices)
        for old, new in zip(helmet.vertices, fixed.vertices):
            self.assertEqual((old.normal, old.uv, old.joints, old.weights), (new.normal, new.uv, new.joints, new.weights))

    def test_move_never_exceeds_reach_plus_margin(self):
        helmet = plate(recess=0.03)
        head = skin([(x, y, 0.0) for x in (-0.01, 0, 0.01) for y in (-0.01, 0, 0.01)])
        _, report = clearance.clear_back(helmet, [head])
        self.assertGreater(report['max_move_m'], 0)
        self.assertLessEqual(report['max_move_m'], clearance.REACH + clearance.MARGIN + 1e-9)


@unittest.skipUnless((MODELS / 'tio_vet_head.mdjx').is_file(), 'installed client models not available')
class InstalledClientTests(unittest.TestCase):
    def test_installed_combat_helmets_cover_the_male_heads(self):
        # The client installs the published (2026.11.16.2+) helmets.
        heads = {name: read(MODELS / (name + '.mdjx')) for name in clearance.HEADS}
        for name in clearance.HELMETS:
            raw = (MODELS / (name + '.mdjx')).read_bytes()
            helmet = read(MODELS / (name + '.mdjx'))
            self.assertEqual(encode(helmet), raw, name)  # the writer reproduces the asset
            after = clearance.clip_depths(helmet, heads)
            self.assertLessEqual(after['chr_man_head'], 0.0005, name)
            self.assertLessEqual(after['chr_man_afro_head'], 0.0005, name)


if __name__ == '__main__':
    unittest.main()
