"""Decorative resources are shared but never become authoritative game cells."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tio.arena_map import load_arena_map
from tio.arena_surroundings import (CITY_RESOURCES, add_arena_surroundings,
                                    load_surroundings_policy, select_surroundings)
from tio.map_generation import generate_map
from tio.protocol.battle_ground import GroundEntry, decode_battle_ground, encode_battle_ground


ROOT = Path(__file__).resolve().parents[1]


class ArenaSurroundingsTests(unittest.TestCase):
    def test_every_city_variant_mode_keeps_exact_playable_layout_and_wire_layers(self):
        for profile, (_, prefix) in CITY_RESOURCES.items():
            for mode in (0, 1, 4, 7):
                size = 57 if mode in (1, 4) else 38
                seeds = {}
                for seed in range(128):
                    metadata = select_surroundings(profile, seed, size, size, mode=mode)
                    seeds.setdefault(metadata['variant'], seed)
                    if len(seeds) == 3:
                        break
                self.assertEqual(set(seeds), {prefix+str(i) for i in (1, 2, 3)})
                for variant, seed in seeds.items():
                    with self.subTest(profile=profile, mode=mode, variant=variant, seed=seed):
                        with patch('tio.map_generation.add_arena_surroundings',
                                   side_effect=lambda arena, *args, **kwargs: (arena, None)):
                            baseline = generate_map(profile, seed=seed, mode=mode, deployment_size=6)
                        scene = generate_map(profile, seed=seed, mode=mode, deployment_size=6)
                        replay = generate_map(profile, seed=seed, mode=mode, deployment_size=6)
                        self.assertEqual(scene, replay)
                        self.assertEqual(scene.layout, baseline.layout)
                        self.assertEqual(scene.patrol, baseline.patrol)
                        self.assertEqual(scene.variant, baseline.variant)
                        self.assertEqual(scene.surroundings['variant'], variant)
                        self.assertFalse(any(o['file'].startswith('as_') for o in scene.layout['objects']))
                        ground = decode_battle_ground(encode_battle_ground(scene.arena.ground))
                        original = decode_battle_ground(encode_battle_ground(baseline.arena.ground))
                        self.assertEqual((ground.width, ground.height), (size, size))
                        self.assertEqual(ground.unknown_u8, 0)
                        self.assertEqual(ground.first_layer, original.first_layer)
                        self.assertEqual(ground.second_layer, original.second_layer)
                        self.assertEqual(ground.entries[:-1], original.entries)
                        self.assertEqual(ground.entries[-1], GroundEntry(scene.surroundings['scene'].encode(), 0, 0))
                        self.assertEqual(sum(e.name.startswith(b'as_') for e in ground.entries), 1)
                        self.assertEqual(replace(scene.arena, ground=baseline.arena.ground), baseline.arena)

    def test_existing_scene_is_idempotent_but_foreign_duplicate_and_shifted_scenes_fail(self):
        scene = generate_map('denver', seed=19)
        arena, metadata = add_arena_surroundings(scene.arena, 'denver', 19)
        self.assertIs(arena, scene.arena)
        self.assertEqual(metadata, scene.surroundings)
        entries = scene.arena.ground.entries
        for invalid in (entries+entries[-1:],
                        (*entries[:-1], GroundEntry(b'as_ny_1_38', 0, 0)),
                        (*entries[:-1], replace(entries[-1], unknown_u8_01=1))):
            broken = replace(scene.arena, ground=replace(scene.arena.ground, entries=invalid))
            with self.subTest(entries=invalid[-1:]), self.assertRaises(ValueError):
                add_arena_surroundings(broken, 'denver', 19)

    def test_fixed_maps_and_encounters_do_not_read_or_apply_city_surroundings(self):
        fixed = load_arena_map(ROOT/'config/arena_map.json')
        with patch('tio.arena_surroundings.load_surroundings_policy',
                   side_effect=AssertionError('Non-city scene used decorative city policy')):
            for profile in ('shooting_range', 'mines', 'fixed_fixture'):
                arena, metadata = add_arena_surroundings(fixed, profile, 19, mode=16)
                self.assertIs(arena, fixed)
                self.assertIsNone(metadata)
            for profile, brush in (('encounter_ash', 7), ('encounter_autumn', 8), ('encounter_blight', 9)):
                scene = generate_map(profile, seed=19)
                ground = decode_battle_ground(encode_battle_ground(scene.arena.ground))
                self.assertEqual(set(ground.first_layer), {brush})
                self.assertFalse(any(e.name.startswith(b'as_') for e in ground.entries))
                self.assertIsNone(scene.surroundings)

    def test_current_config_fixture_disables_art_without_mutating_gameplay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'config').mkdir()
            for name in ('battle_map_profiles.json', 'arena_fragments.json', 'reservation_visuals.json'):
                (root/'config'/name).write_bytes((ROOT/'config'/name).read_bytes())
            policy = load_surroundings_policy()
            path = root/'config/arena_surroundings.json'
            policy['profiles']['denver']['enabled'] = False
            path.write_text(json.dumps(policy))
            with patch('tio.map_generation.ROOT', root):
                disabled = generate_map('denver', seed=19)
            ordinary = generate_map('denver', seed=19)
            self.assertIsNone(disabled.surroundings)
            self.assertFalse(any(e.name.startswith(b'as_') for e in disabled.arena.ground.entries))
            self.assertEqual(disabled.layout, ordinary.layout)
            self.assertEqual(replace(ordinary.arena, ground=disabled.arena.ground), disabled.arena)
            policy['profiles']['denver']['enabled'] = True
            policy['profiles']['denver']['variants'][0]['scene_by_size']['38'] = 'as_ny_1_38'
            path.write_text(json.dumps(policy))
            with patch('tio.map_generation.ROOT', root), self.assertRaises(ValueError):
                generate_map('denver', seed=19)

    def test_unsafe_policy_paths_cross_city_resources_and_invalid_seed_size_mode_are_rejected(self):
        source = load_surroundings_policy()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'policy.json'
            for name in ('../as_de_1_38', 'as_ny_1_38', 'as_de_1_57', 'as_de_1_38.s'):
                changed = deepcopy(source)
                changed['profiles']['denver']['variants'][0]['scene_by_size']['38'] = name
                path.write_text(json.dumps(changed))
                with self.subTest(name=name), self.assertRaises(ValueError):
                    select_surroundings('denver', 19, 38, 38, config_path=path)
        for seed in (-1, 2**64, True, '19'):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                select_surroundings('denver', seed, 38, 38)
        for width, height in ((32, 32), (38, 57), (38.0, 38), (38, 38.0), (True, True)):
            with self.subTest(size=(width, height)), self.assertRaises(ValueError):
                select_surroundings('denver', 19, width, height)
        for mode in (16, True, '0'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                select_surroundings('denver', 19, 38, 38, mode=mode)

    def test_two_real_account_scenes_and_snapshot_keep_one_shared_variant(self):
        # Use the production TeamArena admission and snapshot path with separate
        # account saves; no bot demonstrations stand in for shared state.
        from test_cities import CityTests
        from tio.battle_snapshot import dumps, loads
        from tio.cities import CITIES
        for profile in CITY_RESOURCES:
            town = next(town for town, city in CITIES.items() if city.profile == profile)
            level = CITIES[town].levels[0]
            for mode in (0, 1):
                with self.subTest(profile=profile, mode=mode):
                    case = CityTests()
                    case.setUp()
                    try:
                        count = 2 if mode == 0 else 4
                        for index in range(count):
                            case.locate(index, town, level)
                        for index in (0, 1):
                            case.send(index, bytes((0xba, 3, mode, 1)))
                        if mode == 1:
                            for index, captain in ((2, 0), (3, 1)):
                                room = case.hub.lobbies.room(case.hub.identities[case.sessions[captain]])
                                case.send(index, b'\xba\4'+room.identity.to_bytes(4, 'little'))
                                case.send(index, b'\x2c\1')
                            case.send(0, b'\x2e')
                            case.send(1, b'\x2e')
                        owners = [case.hub.identities[case.sessions[i]] for i in range(count)]
                        battle = case.hub.battles[owners[0]]
                        self.assertFalse(battle['bots'])
                        self.assertEqual(len(battle['humans']), count)
                        packets = []
                        for owner in owners:
                            case.hub.queues[owner].clear()
                            case.hub.send_scene(owner, reconnect=True)
                            packets.append(next(p for p in case.hub.queues[owner] if p[:1] == b'\x35'))
                        self.assertEqual(len(set(packets)), 1)
                        ground = decode_battle_ground(packets[0])
                        self.assertEqual(sum(e.name.startswith(b'as_') for e in ground.entries), 1)
                        size = 38 if mode == 0 else 57
                        self.assertEqual((ground.width, ground.height), (size, size))
                        restored = loads(dumps({'battle': battle}))[0]['battle']
                        self.assertEqual(restored['ground'], packets[0])
                        self.assertEqual(restored['match_id'], battle['match_id'])
                        self.assertEqual(restored['field'].width, size)
                        self.assertEqual(restored['field'].blocked, battle['field'].blocked)
                    finally:
                        case.doCleanups()
