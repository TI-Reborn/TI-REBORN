import json,unittest
from pathlib import Path
from tio.map_generation import generate_map,connected,reachable_cells
from tio.protocol.battle_ground import encode_battle_ground,decode_battle_ground

ROOT=Path(__file__).resolve().parents[1]


class CitySceneryTests(unittest.TestCase):
    def test_city_rotation_paths_doors_and_resources(self):
        profiles=json.loads((ROOT/'config/battle_map_profiles.json').read_text())['profiles']
        for city in ('denver','new_york','military_zone'):
            expected={n for group in profiles[city]['pools'].values() for n in group};seen=set()
            for mode in (0,1,4,7):
                for seed in range(40):
                    scene=generate_map(city,seed=seed,mode=mode,deployment_size=6)
                    arena=scene.arena;seen.update(o['file'] for o in scene.layout['objects'])
                    self.assertTrue(connected(arena,reachable_cells(arena)))
                    self.assertEqual(len(arena.player_spawns),6)
                    self.assertEqual(len(arena.doors),len({d[:2] for d in arena.doors}))
                    decoded=decode_battle_ground(encode_battle_ground(arena.ground))
                    self.assertTrue(all(b'/' not in e.name for e in decoded.entries))
                    self.assertEqual(set(decoded.first_layer),{profiles[city]['ground_id']})
            self.assertFalse(expected-seen,(city,expected-seen))

    def test_reservation_keeps_its_approved_theme(self):
        for seed in range(20):
            scene=generate_map('reservation',seed=seed)
            self.assertFalse(any('forest' in o['file'] or 'ny_' in o['file'] for o in scene.layout['objects']))
