"""Phase8 pure core checks; no hosted rollout or full client GUI assertion."""
from contextlib import closing
from dataclasses import replace
import hashlib
import importlib.util
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch

from tio.cities import CITIES,require_arena
from tio.locations import BASE_LOCATIONS,TOWNS,LocationStore,center,town_at,town_packets
from tio.map_generation import generate_map
from tio.protocol.battle_ground import decode_battle_ground,encode_battle_ground
from tio.protocol.town_info import decode_town_info
from tio.world_completion import location,location_bounds,prison_online,sentence

ROOT=Path(__file__).resolve().parents[1]


class WorldTravelCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'players.db';self.now=1000
        self.store=LocationStore(self.path,clock=lambda:self.now)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE characters(account TEXT,slot INTEGER)')
            db.executemany('INSERT INTO characters VALUES (?,1)',[('alice',),('bob',)])
            for account in ('alice','bob'):LocationStore._save(db,account,3,*center(3))

    @staticmethod
    def packet(town):return struct.pack('<Bii',0x1b,*center(town))

    def test_world_bounds_levels_and_no_capture_training(self):
        for town,bounds in location_bounds().items():
            self.assertEqual(TOWNS[town],bounds)
            self.assertEqual(town_at(*center(town)),town)
            self.assertEqual(decode_town_info(town_packets(town)[0]).unknown_bytes[:2],tuple(location(town)['levels']))
        self.assertIn(7,BASE_LOCATIONS)
        self.assertTrue(set((19,20,21,22)).isdisjoint(BASE_LOCATIONS))
        self.assertEqual(town_at(185,-336),14)
        self.assertEqual(town_at(*center(7)),7)

    def test_new_arena_bands_reject_noncombat_and_empty_roster(self):
        self.assertEqual(require_arena(4,(4,20)),CITIES[4])
        self.assertEqual(require_arena(18,(4,20)),CITIES[18])
        for town,levels in ((4,()),(18,(3,)),(18,(True,)),(4,(21,)),(10,(4,)),(19,(4,)),(7,(4,))):
            with self.assertRaises(ValueError):require_arena(town,levels)
        self.assertEqual((CITIES[4].pool,CITIES[4].influence,CITIES[18].kill_bonus),('starter',0,10))

    def test_native_travel_arrival_reopen_has_exact_new_town(self):
        for town in (4,18,19,20,21,22):
            with self.subTest(town=town):
                packets=self.store.travel('alice',self.packet(town),41)
                self.assertEqual(packets[-1][0],0x1d)
                self.assertTrue(self.store.travelling('alice'));self.assertIsNone(self.store.current('alice'))
                self.assertEqual(self.store.current('bob'),3)
                with closing(sqlite3.connect(self.path)) as db:arrives=db.execute('SELECT arrives FROM map_journeys WHERE account=?',('alice',)).fetchone()[0]
                self.now=arrives+1
                reopened=LocationStore(self.path,clock=lambda:self.now)
                arrived=reopened.refresh('alice',41)
                self.assertEqual(arrived[0][0],0x1e)
                self.assertEqual(decode_town_info(arrived[1]).town_id,town)
                self.assertEqual(reopened.current('alice'),town)
                self.assertEqual(reopened.position('alice'),center(town))
                self.assertEqual(reopened.refresh('alice',41),())

    def test_prison_gate_has_no_new_sentence_or_partial_route_mutation(self):
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):self.store.travel('alice',self.packet(10),41)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.store.current('alice'),3)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='world_prison'").fetchone())

    def test_trusted_sentence_blocks_only_prisoner_then_online_completion_releases(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');sentence(db,'alice',20,'moderation:1')
        self.assertEqual(self.store.current('alice'),10)
        with self.assertRaises(ValueError):self.store.travel('alice',self.packet(18),41)
        self.store.travel('bob',self.packet(18),42)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');prison_online(db,'alice','authenticated:1',now=1000)
            self.assertEqual(prison_online(db,'alice','authenticated:1',now=1020)['remaining'],0)
        self.assertEqual(self.store.current('alice'),3)
        self.store.travel('alice',self.packet(18),41)
        self.assertTrue(self.store.travelling('alice'))

    def test_old_route_inside_prison_finishes_on_map_without_prison_admission(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            LocationStore._save(db,'alice',None,*center(3))
            db.execute('INSERT INTO map_journeys VALUES (?,?,?,?,?,?,?)',('alice',*center(3),*center(10),0,10))
        packets=self.store.refresh('alice',41)
        self.assertEqual([p[0] for p in packets],[0x1e])
        self.assertIsNone(self.store.current('alice'))
        self.assertEqual(self.store.position('alice'),center(10))
        self.assertFalse(self.store.travelling('alice'))


class WorldMapDispatchTests(unittest.TestCase):
    def test_detroit_original_ground_and_sizes_all_modes(self):
        for mode,size in ((0,38),(7,38),(1,50),(4,50)):
            scene=generate_map('detroit',seed=23,mode=mode,deployment_size=6)
            ground=decode_battle_ground(encode_battle_ground(scene.arena.ground))
            self.assertEqual((ground.width,ground.height),(size,size))
            self.assertEqual(set(ground.first_layer),{6})
            self.assertEqual(scene.variant,'original_whole_map')
            self.assertEqual(len(scene.arena.player_spawns+scene.arena.bot_spawns),12)
        for kwargs in (dict(map_size=0),dict(map_size=5),dict(map_size=True),dict(variant='classic'),dict(deployment_size=7),dict(mode=True)):
            with self.assertRaises(ValueError):generate_map('detroit',**kwargs)

    def test_deployment_override_only_adds_detroit_to_actual_host_source(self):
        source=ROOT/'reports/gameplay-completion/stage8-world/source/map_generation.py'
        candidate=ROOT/'reports/gameplay-completion/stage8-world/runtime/tio/map_generation.py'
        raw=source.read_bytes();final=candidate.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'48ab66cd092e18d9908d9a70f19af19009173fd50d7396ecc3374d99e49f5f52')
        insertion=b"    if profile=='detroit':\n        if variant is not None:\n            raise ValueError('Detroit uses its original small/large map resources; custom variants are unavailable')\n        from .world_completion import generate_world_map\n        return generate_world_map(18,seed=seed,deployment_size=deployment_size,mode=mode,map_size=map_size)\n"
        self.assertEqual(final.replace(insertion,b''),raw)
        self.assertNotIn(b'profiles_data',final)
        spec=importlib.util.spec_from_file_location('tio._world_candidate_map_generation',candidate)
        module=importlib.util.module_from_spec(spec)
        # Dataclasses resolve their own module during class construction.
        import sys
        with patch.dict(sys.modules,{spec.name:module}):spec.loader.exec_module(module)
        module.ROOT=ROOT
        self.assertEqual(module.generate_map(seed=9).arena,generate_map(seed=9).arena)
        self.assertEqual(module.generate_map('detroit',seed=9).profile,'detroit')


class WorldSceneCoreTests(unittest.TestCase):
    def setUp(self):
        import test_shared_team_arena as helpers
        helpers.SharedTeamTests.setUp(self)
        from tio.owned_pets import OwnedPetStore
        from tio.protocol.pet_info import decode_pet_info,encode_pet_info
        from tio.matchmaking import SurvivalQueue
        self.seats=[]
        for index,session in enumerate(self.sessions[:2]):
            store=OwnedPetStore(self.path)
            identity,raw,inventory=store.list(session.account)[0]
            pet=decode_pet_info(raw,human_equipment=True)
            raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':4}))
            with closing(sqlite3.connect(self.path)) as db,db:
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(raw,session.account,identity))
            owner=51+index
            ticket=SurvivalQueue().join(owner,store.list(session.account))
            self.seats.append((owner,index,self.path,session.account,ticket,False))

    def prepare(self,town,seed=23,mode=0):
        from tio.team_scene import prepare
        with patch('tio.ranks.time.time',return_value=1700000000):
            return prepare(self.seats,mode,seed=seed,town_id=town,selected_ids=True)

    def test_real_two_account_detroit_scene_policy_ground_and_save_preserved(self):
        from tio.owned_pets import OwnedPetStore
        before=OwnedPetStore(self.path).list('alice'),OwnedPetStore(self.path).list('bob')
        field,views,ground,skills=self.prepare(18)
        self.assertEqual(set(views),{51,52})
        self.assertEqual(set(a.owner_id for a in field._actors.values()),{51,52})
        self.assertEqual(decode_battle_ground(ground).width,38)
        self.assertEqual(field.scene_metadata['world_policy']['town_id'],18)
        self.assertTrue(field.scene_metadata['world_policy']['carry_items'])
        self.assertTrue(field.scene_metadata['world_policy']['rank_gain'])
        self.assertEqual((OwnedPetStore(self.path).list('alice'),OwnedPetStore(self.path).list('bob')),before)

    def test_outpost_supplies_unique_temporary_seeded_policy_without_save_delete(self):
        from tio.owned_pets import OwnedPetStore
        before=OwnedPetStore(self.path).list('alice'),OwnedPetStore(self.path).list('bob')
        field,views,_,_=self.prepare(4)
        policy=field.scene_metadata['world_policy']
        self.assertEqual((policy['carry_items'],policy['rank_gain'],policy['max_upgrade']),(False,False,0))
        self.assertTrue(field.loot.boxes);self.assertTrue(all(field.loot.boxes.values()))
        items=[i for box in field.loot.boxes.values() for i in box]
        ids={i.instance_id for i in items}
        self.assertEqual(len(ids),len(items));self.assertEqual(ids,field.combat.temporary_items)
        self.assertFalse(field.loot.opened)
        replay=self.prepare(4)[0]
        self.assertEqual(field.loot.boxes,replay.loot.boxes)
        self.assertEqual(field.loot.rng.getstate(),replay.loot.rng.getstate())
        self.assertEqual((OwnedPetStore(self.path).list('alice'),OwnedPetStore(self.path).list('bob')),before)

    def test_world_scene_snapshot_roundtrip_keeps_policy_loot_rng_and_real_owners(self):
        from tio.battle_snapshot import dumps,loads
        field,views,ground,skills=self.prepare(4)
        restored=loads(dumps((field,views,ground,skills)))[0]
        new=restored[0]
        self.assertEqual(new.scene_metadata,field.scene_metadata)
        self.assertEqual(new.loot.boxes,field.loot.boxes)
        self.assertEqual(new.loot.rng.getstate(),field.loot.rng.getstate())
        self.assertIs(new.loot.combat,new.combat)
        self.assertEqual(set(restored[1]),{51,52})

if __name__=='__main__':unittest.main()
