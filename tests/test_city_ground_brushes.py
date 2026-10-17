"""Native ground bytes must match the selected city's published resources."""
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tio.arena_map import build_arena_map, load_arena_map
from tio.map_generation import generate_map
from tio.protocol.battle_ground import decode_battle_ground, encode_battle_ground


ROOT = Path(__file__).resolve().parents[1]


class CityGroundBrushTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = json.loads((ROOT/'config/battle_map_profiles.json').read_text())['profiles']
        cls.visuals = json.loads((ROOT/'config/reservation_visuals.json').read_text())

    def decode(self, scene):
        packet = encode_battle_ground(scene.arena.ground)
        ground = decode_battle_ground(packet)
        self.assertEqual(packet[1], 0, 'Terrain must not enable persistent exploration')
        self.assertEqual(ground.second_layer, bytes(ground.width*ground.height))
        return ground

    def test_city_native_ground_all_modes_and_seeds_without_model_substitution(self):
        # IDs verified against the published client's base/ground.xml.
        for profile, brush in (('denver', 3), ('new_york', 2), ('military_zone', 1)):
            policy = self.profiles[profile]
            allowed = {name for pool in policy['pools'].values() for name in pool}
            for mode in (0, 1, 4, 7):
                for seed in range(6):
                    with self.subTest(profile=profile, mode=mode, seed=seed):
                        # The city fix may bind terrain, never Reservation art.
                        with patch('tio.map_generation.reservation_visuals',
                                   side_effect=AssertionError('Other city rebound')):
                            scene = generate_map(profile, seed=seed, mode=mode, deployment_size=6)
                        ground = self.decode(scene)
                        size = 57 if mode in (1, 4) else 38
                        self.assertEqual((ground.width, ground.height), (size, size))
                        self.assertEqual(ground.first_layer, bytes([brush])*(size*size))
                        self.assertEqual(scene.layout['ground_id'], brush)
                        self.assertEqual(scene.layout['ground_brush_id'], brush)
                        names = [obj['file'] for obj in scene.layout['objects']]
                        self.assertTrue(set(names) <= allowed)
                        self.assertEqual([entry.name for entry in ground.entries if not entry.name.startswith(b'as_')],
                                         [Path(name).stem.encode('ascii') for name in names])
                        if profile == 'denver':
                            self.assertTrue(any(name.startswith('forest_tree_') for name in names))
                            self.assertFalse(any(name.startswith('ny_') for name in names))
                        else:
                            self.assertFalse(any(name.startswith('forest_') for name in names))
                        if profile == 'new_york':
                            self.assertTrue(any(name.startswith('ny_') for name in names))
                        else:
                            self.assertFalse(any(name.startswith('ny_') for name in names))

    def test_reservation_keeps_isolated_brushes_and_model_bindings(self):
        seen_brushes = set()
        for mode in (0, 1, 4, 7):
            for variant in self.profiles['reservation']['variants']:
                for seed in range(6):
                    with self.subTest(mode=mode, variant=variant['name'], seed=seed):
                        scene = generate_map('reservation', seed=seed, mode=mode,
                                             variant=variant['name'], deployment_size=6)
                        ground = self.decode(scene)
                        brush = self.visuals['ground_ids'][str(scene.layout['ground_id'])]
                        seen_brushes.add(brush)
                        self.assertEqual(set(ground.first_layer), {brush})
                        expected = [self.visuals['entries'][Path(obj['file']).stem].encode('ascii')
                                    for obj in scene.layout['objects']]
                        self.assertEqual([entry.name for entry in ground.entries if not entry.name.startswith(b'as_')], expected)
        self.assertEqual(seen_brushes, {10, 11})

    def test_encounter_profiles_keep_their_native_biome_brushes(self):
        for profile, brush, size in (('encounter_ash', 7, 38),
                                     ('encounter_autumn', 8, 42),
                                     ('encounter_blight', 9, 40)):
            for seed in range(6):
                with self.subTest(profile=profile, seed=seed):
                    scene = generate_map(profile, seed=seed)
                    ground = self.decode(scene)
                    self.assertEqual((ground.width, ground.height), (size, size))
                    self.assertEqual(ground.first_layer, bytes([brush])*(size*size))
                    self.assertFalse(scene.arena.containers)

    def test_brush_selection_changes_no_authoritative_layout_or_models(self):
        fragments = json.loads((ROOT/'config/arena_fragments.json').read_text())
        for profile in ('denver', 'new_york', 'military_zone'):
            scene = generate_map(profile, seed=19)
            legacy = build_arena_map({key: value for key, value in scene.layout.items()
                                      if key != 'ground_brush_id'}, fragments)
            self.assertEqual(legacy.ground.first_layer, bytes(legacy.ground.width*legacy.ground.height))
            self.assertEqual(replace(scene.arena, ground=legacy.ground), legacy)

    def test_fixed_layout_defaults_stay_compatible_and_explicit_brush_is_validated(self):
        source = json.loads((ROOT/'config/arena_map.json').read_text())
        fragments = json.loads((ROOT/'config/arena_fragments.json').read_text())
        arena = load_arena_map(ROOT/'config/arena_map.json')
        self.assertEqual(set(arena.ground.first_layer), {0})
        for brush in (-1, 256, True, '3'):
            with self.subTest(brush=brush), self.assertRaises(ValueError):
                build_arena_map({**source, 'ground_brush_id': brush}, fragments)
        explicit = build_arena_map({**source, 'ground_brush_id': 3}, fragments)
        self.assertEqual(set(explicit.ground.first_layer), {3})
        self.assertEqual(replace(explicit, ground=arena.ground), arena)
