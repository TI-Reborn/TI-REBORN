"""Visual bindings must preserve authoritative gameplay and other cities."""
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from tio.map_generation import generate_map
from tio.protocol.battle_ground import encode_battle_ground,decode_battle_ground

ROOT=Path(__file__).resolve().parents[1]

class ReservationVisualsTests(TestCase):
    def test_all_modes_variants_keep_gameplay_exactly(self):
        policy=json.loads((ROOT/'config/battle_map_profiles.json').read_text())['profiles']['reservation']
        for mode in (0,1,4,7):
            for variant in policy['variants']:
                for seed in range(8):
                    with patch('tio.map_generation.reservation_visuals',side_effect=lambda a,g:a):
                        original=generate_map(mode=mode,variant=variant['name'],seed=seed,deployment_size=6)
                    new=generate_map(mode=mode,variant=variant['name'],seed=seed,deployment_size=6)
                    self.assertEqual(original.layout,new.layout)
                    self.assertEqual(original.patrol,new.patrol)
                    for field in ('blocked','transparent_obstacles','player_spawns','bot_spawns','containers','doors'):
                        self.assertEqual(getattr(original.arena,field),getattr(new.arena,field))
                    ground=decode_battle_ground(encode_battle_ground(new.arena.ground))
                    self.assertEqual(ground.unknown_u8,0)
                    self.assertEqual(ground.second_layer,original.arena.ground.second_layer)
                    self.assertEqual(set(ground.first_layer),{10+original.layout['ground_id']})
                    self.assertEqual([(e.unknown_u8_01,e.unknown_u8_02) for e in ground.entries],
                                     [(e.unknown_u8_01,e.unknown_u8_02) for e in original.arena.ground.entries])

    def test_every_reservation_fragment_has_an_isolated_binding(self):
        p=json.loads((ROOT/'config/battle_map_profiles.json').read_text())['profiles']['reservation']
        bindings=json.loads((ROOT/'config/reservation_visuals.json').read_text())['entries']
        self.assertEqual(set(bindings),{Path(n).stem for pool in p['pools'].values() for n in pool})
        self.assertEqual(len(set(bindings.values())),len(bindings))
        self.assertTrue(all(len(a)==len(b) and a!=b for a,b in bindings.items()))

    def test_other_profiles_do_not_use_reservation_resources(self):
        profiles=json.loads((ROOT/'config/battle_map_profiles.json').read_text())['profiles']
        for name,policy in profiles.items():
            if name=='reservation' or not policy['enabled']:continue
            with patch('tio.map_generation.reservation_visuals',side_effect=AssertionError('Other city rebound')):
                scene=generate_map(name,seed=19)
            self.assertTrue(set(scene.arena.ground.first_layer).isdisjoint({10,11}))
