import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from tio.map_generation import generate_map, reachable_cells, connected
from tio.protocol.battle_ground import encode_battle_ground, decode_battle_ground

ROOT = Path(__file__).resolve().parents[1]


class MapGenerationTests(unittest.TestCase):
    def test_many_seeds_have_walls_and_accessible_crates_without_denver_scenery(self):
        layouts = set()
        for seed in range(100):
            scene = generate_map(seed=seed)
            arena = scene.arena
            ground = decode_battle_ground(encode_battle_ground(arena.ground))
            self.assertEqual((ground.width,ground.height), (38,38))
            self.assertIn(ground.unknown_u8,(0,1))
            self.assertEqual(len(ground.first_layer),38*38)
            names = [o['file'] for o in scene.layout['objects']]
            self.assertGreaterEqual(sum('concrete_wall' in n for n in names),2)
            self.assertFalse(any('village' in n or 'tree' in n for n in names))
            self.assertTrue(all(b'/' not in e.name and b'\\' not in e.name for e in ground.entries))
            self.assertFalse(any('forest' in n for n in names))
            reached = reachable_cells(arena)
            self.assertTrue(connected(arena,reached))
            self.assertTrue(all(p in reached for p in scene.patrol))
            self.assertGreaterEqual(len(arena.containers),3)
            self.assertEqual(len(arena.containers),len(set(arena.containers)))
            self.assertTrue(set(arena.containers) <= arena.blocked)
            self.assertTrue(set(arena.player_spawns+arena.bot_spawns).isdisjoint(arena.blocked))
            layouts.add(encode_battle_ground(ground))
        self.assertEqual(len(layouts),100)

    def test_all_variants_large_modes_full_deployment_and_protocol_roundtrip(self):
        policy=json.loads((ROOT/'config/battle_map_profiles.json').read_text())['profiles']['reservation']
        for mode in (0,1,4,7):
            for variant in policy['variants']:
                for seed in range(6):
                    scene=generate_map(mode=mode,variant=variant['name'],seed=seed,deployment_size=6)
                    size=57 if mode in (1,4) else 38
                    ground=decode_battle_ground(encode_battle_ground(scene.arena.ground))
                    self.assertEqual((ground.width,ground.height),(size,size))
                    self.assertEqual(scene.variant,variant['name'])
                    self.assertEqual(len(set(scene.arena.player_spawns+scene.arena.bot_spawns)),12)
                    self.assertTrue(connected(scene.arena,reachable_cells(scene.arena)))
                    self.assertEqual(len(scene.arena.doors),len(set((x,y) for x,y,_ in scene.arena.doors)))
        for mode in (-1,True,'1',2):
            with self.assertRaises(ValueError):generate_map(mode=mode)
        with self.assertRaises(ValueError):generate_map(variant='not-a-map')

    def test_seed_replays_scene_and_fresh_matches_use_new_seed(self):
        self.assertEqual(generate_map(seed=19),generate_map(seed=19))
        with patch('tio.map_generation.secrets.randbits',side_effect=(10,11)):
            a,b=generate_map(),generate_map()
        self.assertEqual((a.seed,b.seed),(10,11))
        self.assertNotEqual(a.layout,b.layout)
        for name in ('unknown',):
            with self.assertRaises(ValueError):generate_map(name)
        for seed in (-1,2**64,True,'19'):
            with self.assertRaises(ValueError):generate_map(seed=seed)

    def test_scene_loot_replay_refresh_and_exploration_preserve_save(self):
        from tio.abilities import AbilityCatalog, AbilityLevel
        from tio.owned_pets import OwnedPetStore
        from tio.matchmaking import SurvivalQueue
        from tio.arena_service import ArenaService
        from tio.protocol.battle_turn import encode_end_turn
        from tio.visibility import visible_actors
        from tio.training_bot import play_turn
        from tools.survival_scene import prepare_survival
        from dataclasses import replace
        from unittest.mock import patch
        source=json.loads((ROOT/'config/abilities.json').read_text())
        catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
        trial=json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        # Entering combat deliberately refreshes the rank-decay clock. Keep
        # wall time fixed so the save comparison measures scene mutations,
        # rather than occasionally failing across a one-second boundary.
        with patch('tio.ranks.time.time',return_value=1700000000), tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db'
            pets=OwnedPetStore(path)
            pets.ensure('alice',bytes.fromhex(trial['packet_hex']),bytes.fromhex(trial['inventory_packet_hex']),human=True)
            ticket=SurvivalQueue().join(42,pets.list('alice'))
            with closing(sqlite3.connect(path)) as db:before='\n'.join(db.iterdump())
            first=prepare_survival(path,'alice',ticket,catalog,seed=5)
            replay=prepare_survival(path,'alice',ticket,catalog,seed=5)
            second=prepare_survival(path,'alice',ticket,catalog,seed=6)
            self.assertEqual((first.field.width,first.field.height),(38,38))
            self.assertEqual(first.field.loot.boxes,replay.field.loot.boxes)
            self.assertNotEqual(first.field.loot.boxes,second.field.loot.boxes)
            self.assertTrue(all(first.field.loot.boxes.values()))
            self.assertFalse(first.field.loot.opened)
            ids=[i.instance_id for items in first.field.loot.boxes.values() for i in items]
            self.assertEqual(len(ids),len(set(ids)))
            self.assertEqual(set(ids),first.field.combat.temporary_items)
            first.field.loot.opened.add(next(iter(first.field.loot.boxes)))
            self.assertFalse(second.field.loot.opened)
            # Explicitly hide all enemies to exercise exploration rather than
            # accidentally passing through ordinary visible-enemy pursuit.
            field=first.field
            for i,a in tuple(field._actors.items()):
                field._actors[i]=replace(a,sight_radius=0)
            self.assertTrue(all(field.actor(i).owner_id==first.bot_owner for i in visible_actors(field,first.bot_owner)))
            arena=ArenaService()
            room,_=arena.start_survival(42,b'Alice',first)
            arena.member_loaded(42,b'\x36')
            arena.begin_turn_packets(42,first.actor_ids,40)
            arena.end_turn(42,encode_end_turn(first.actor_ids[0]))
            bot=field.actor_ids(first.bot_owner)[0]
            start=(field.actor(bot).x,field.actor(bot).y)
            packets=play_turn(arena,room.room_id,first.bot_owner,view=first.visibility)
            self.assertNotEqual((field.actor(bot).x,field.actor(bot).y),start)
            self.assertFalse(any(p[:1] in (b'\x3b',b'\x3d') for p in packets))
            with closing(sqlite3.connect(path)) as db:self.assertEqual('\n'.join(db.iterdump()),before)
