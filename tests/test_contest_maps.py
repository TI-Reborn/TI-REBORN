import unittest
from tio.contest_maps import generate,catalogue
from tio.map_generation import connected,reachable_cells
from tio.protocol.battle_ground import encode_battle_ground,decode_battle_ground


class ContestMapTests(unittest.TestCase):
    def test_all_nine_original_layouts_and_authored_points(self):
        used=set()
        for seed in range(100):
            for size in (1,3,4,6):
                scene=generate(seed=seed,deployment_size=size);arena=scene.arena;used.add(scene.variant)
                row=next(r for r in catalogue() if r['file']==scene.variant)
                self.assertEqual((arena.ground.width,arena.ground.height),(38,38))
                self.assertEqual(len(arena.player_spawns),size)
                self.assertTrue(connected(arena,reachable_cells(arena)))
                self.assertEqual(set(scene.layout['control_points']),set(map(tuple,row['flags'])))
                self.assertTrue(set(scene.layout['control_points'])<=arena.blocked)
                self.assertFalse(set(arena.player_spawns+arena.bot_spawns)&set(arena.blocked))
                decoded=decode_battle_ground(encode_battle_ground(arena.ground))
                self.assertEqual(len(decoded.entries),1)
                self.assertEqual(decoded.entries[0].name,scene.variant.split('/')[-1][:-2].encode())
                self.assertEqual(set(decoded.first_layer),{row['ground_brush_id']})
        self.assertEqual(len(used),9)

    def test_determinism_and_invalid_requests(self):
        self.assertEqual(generate(seed=77),generate(seed=77))
        for size in (0,7,True):
            with self.assertRaises(ValueError):generate(seed=77,deployment_size=size)
        with self.assertRaises(ValueError):generate(seed=-1)
