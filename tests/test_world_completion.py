from contextlib import closing
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tio import world_completion as world
from tio.protocol.pet_info import decode_pet_info,encode_pet_info


class WorldCompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'players.sqlite3';self.db=sqlite3.connect(self.path);self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE accounts(login TEXT PRIMARY KEY);
            CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB,name_key TEXT);
            CREATE TABLE owned_pets(account TEXT,pet_id INTEGER,human INTEGER,pet_packet BLOB,inventory_packet BLOB,PRIMARY KEY(account,pet_id));
            CREATE TABLE soldier_ratings(account TEXT,pet_id INTEGER,rating INTEGER);
            CREATE TABLE battle_rewards(account TEXT,result INTEGER,calculation TEXT);
            CREATE TABLE player_battle_statistics(account TEXT,damage_dealt INTEGER);
            CREATE TABLE character_identities(login TEXT,slot INTEGER,owner TEXT);
            CREATE TABLE character_locations(account TEXT PRIMARY KEY,town_id INTEGER,x REAL,y REAL);
            CREATE TABLE map_journeys(account TEXT PRIMARY KEY);
        ''')
        trial=json.loads((world.ROOT/'evidence/owned_pet_trial.json').read_text());self.pet=decode_pet_info(bytes.fromhex(trial['packet_hex']),human_equipment=True)

    def add(self,owner,name,*,login=None,slot=None,points=0,rating=0,xp=0,wins=0,damage=0):
        if login is None:self.db.execute('INSERT INTO accounts VALUES (?)',(owner,))
        else:self.db.execute('INSERT INTO character_identities VALUES (?,?,?)',(login,slot,owner))
        self.db.execute('INSERT INTO characters VALUES (?,1,?,?)',(owner,name.encode(),name.lower()))
        fields={**self.pet.fields,'0x8c4bbc':1,'0x8c4bd0':points&0xffffffff,'0x8c4b05':xp}
        self.db.execute('INSERT INTO owned_pets VALUES (?,1,1,?,?)',(owner,encode_pet_info(replace(self.pet,fields=fields)),b''))
        self.db.execute('INSERT INTO soldier_ratings VALUES (?,1,?)',(owner,rating))
        self.db.executemany('INSERT INTO battle_rewards VALUES (?,1,?)',[(owner,'{}')]*wins)
        self.db.execute('INSERT INTO player_battle_statistics VALUES (?,?)',(owner,damage))
        self.db.execute('INSERT INTO character_locations VALUES (?,3,-154,-318)',(owner,))

    def test_top100_reads_every_offline_account_not_recent_or_online_and_stable_tie(self):
        for i in range(130):self.add(f'account{i:03}',f'Player{i:03}',rating=i%3)
        self.db.commit();before=self.path.read_bytes();rows=world.player_top100(self.path)
        self.assertEqual(len(rows),100);self.assertEqual(rows[0]['name'],b'Player002')
        self.assertEqual(rows[1]['name'],b'Player005');self.assertEqual([r['place'] for r in rows],list(range(1,101)))
        self.assertEqual(world.player_top100(self.path),rows);self.assertEqual(self.path.read_bytes(),before)

    def test_all_manual_sorts_and_valid_character_aliases(self):
        self.add('alice','Alice',rating=-3,points=30,xp=100,wins=4,damage=2)
        self.add('bob','Bob',rating=8,points=3,xp=1000,wins=1,damage=80)
        self.add('@character:alice:2','AliceTwo',login='alice',slot=2,rating=11)
        self.db.execute("INSERT INTO characters VALUES ('orphan',1,X'4f727068616e','orphan')")
        self.db.commit()
        for sort,name in [('rating',b'AliceTwo'),('rank',b'Alice'),('wins',b'Alice'),('damage',b'Bob'),('experience',b'Bob')]:
            self.assertEqual(world.player_top100(self.path,sort=sort)[0]['name'],name)
        self.assertEqual(len(world.player_top100(self.path)),3)

    def test_dismissed_rating_xp_rank_removed_wager_wins_excluded(self):
        self.add('alice','Alice',rating=10,points=300,xp=123,wins=2)
        self.db.execute("INSERT INTO soldier_ratings VALUES ('alice',99,999)")
        self.db.execute("INSERT INTO battle_rewards VALUES ('alice',1,'{\"wager\":true}')")
        self.db.commit();r=world.player_top100(self.path)[0]
        self.assertEqual((r['rating'],r['experience'],r['rank'],r['wins']),(10,123,100,2))
        self.db.execute("DELETE FROM owned_pets WHERE account='alice'");self.db.commit()
        r=world.player_top100(self.path)[0];self.assertEqual((r['rating'],r['experience'],r['rank'],r['wins']),(0,0,0,2))

    def test_rating_bonus_adapter_uses_earned_backend_and_empty_schema_read_only(self):
        self.add('alice','Alice',rating=7);self.db.commit()
        import sys,types
        module=types.ModuleType('tio.achievement_benefits');module.total_rating=lambda db,account,base:base+(75 if account=='alice' else 0)
        with patch.dict(sys.modules,{'tio.achievement_benefits':module}):self.assertEqual(world.player_top100(self.path)[0]['rating'],82)
        with sqlite3.connect(':memory:') as db:self.assertEqual(world.players(db),())
        for bad in ('unknown',None,1):
            with self.assertRaises(ValueError):world.players(self.db,sort=bad)

    def test_rating_tie_casefolds_name_and_alias_requires_real_account_login(self):
        self.add('a','alice',rating=8);self.add('b','Bob',rating=8)
        self.db.execute("UPDATE characters SET name_key='ALICE' WHERE account='a'")
        self.db.execute("INSERT INTO character_identities VALUES ('a',2,'@character:a:2')")
        self.db.execute("INSERT INTO character_identities VALUES ('@character:a:2',2,'@character:@character:a:2:2')")
        self.db.execute("INSERT INTO characters VALUES ('@character:@character:a:2:2',1,X'46616b65','fake')")
        self.db.commit();rows=world.player_top100(self.path)
        self.assertEqual([r['owner'] for r in rows],['a','b'])
        record=world.location(4);record['bounds'][0]=0
        self.assertEqual(world.location(4)['bounds'][0],225)

    def test_global_hourly_coefficients_fixed_manual_city_and_balanced_rotation(self):
        a=world.city_coefficients(2,now=100);b=world.city_coefficients(2,now=3600)
        self.assertNotEqual(a['profit'],b['profit']);self.assertEqual(a,world.city_coefficients(2,now=3599))
        self.assertEqual(sum(Fraction(world.city_coefficients(i,now=100)['profit']) for i in (2,5,8,18)),16)
        self.assertEqual(world.city_coefficients(4,now=0)['experience'],'3/4')
        self.assertEqual(world.city_coefficients(4,now=0)['influence'],'0')
        self.assertEqual(world.city_coefficients(3,now=0)['profit'],'1')
        self.assertEqual(world.city_coefficients(3,now=0)['influence'],'0')
        for bad in (-1,True,None):
            with self.assertRaises(ValueError):world.city_coefficients(bad)

    def test_match_freeze_survives_restart_retry_hour_change_and_transaction_rollback(self):
        self.db.execute('BEGIN');a=world.freeze_city(self.db,'uuid-match',18,now=100);self.db.commit()
        self.db.execute('BEGIN');self.assertEqual(world.freeze_city(self.db,'uuid-match',18,now=8000),a);self.db.commit()
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(world.frozen_city(db,'uuid-match'),a)
        self.db.execute('BEGIN')
        with self.assertRaises(ValueError):world.freeze_city(self.db,'uuid-match',2,now=100)
        world.freeze_city(self.db,'rollback',18,now=100);self.db.rollback()
        with self.assertRaises(ValueError):world.frozen_city(self.db,'rollback')
        with self.assertRaises(ValueError):world.freeze_city(self.db,'no-transaction',18)

    def test_source_outpost_prison_and_explicit_extensions_capture_guards(self):
        self.assertEqual(world.location(4)['bounds'],[225,-437,305,-357])
        self.assertFalse(world.require_location(4,(4,20))['carry_items'])
        self.assertTrue(world.require_location(18,(4,20))['carry_items'])
        self.assertEqual(world.location(10)['bounds'],[-330,59,-304,85])
        self.assertEqual(world.location(7)['original_bounds'],[175,-346,195,-326])
        for t,l in ((19,4),(20,7),(21,11),(22,16)):
            self.assertFalse(world.require_location(t,(l,),training=True)['capture'])
            with self.assertRaises(ValueError):world.require_location(t,(l,))
        with self.assertRaises(ValueError):world.require_location(10,(1,))
        with self.assertRaises(ValueError):world.require_location(4,(3,))

    def test_prison_real_account_online_only_reconnect_gaps_idempotent_and_restore(self):
        self.add('alice','Alice');self.add('bob','Bob');self.db.commit()
        self.db.execute('BEGIN');world.sentence(self.db,'alice',100,'sentence1');world.sentence(self.db,'alice',100,'sentence1');self.db.commit()
        self.db.execute('BEGIN');self.assertEqual(world.prison_online(self.db,'alice','session1',now=100)['remaining'],100)
        self.assertEqual(world.prison_online(self.db,'alice','session1',now=120,active=False)['remaining'],80);self.db.commit()
        self.db.execute('BEGIN');self.assertEqual(world.prison_online(self.db,'alice','session2',now=100000)['remaining'],80)
        self.assertEqual(world.prison_online(self.db,'alice','session1',now=100010,active=False)['remaining'],80)
        self.assertEqual(world.prison_online(self.db,'alice','session2',now=100060)['remaining'],20)
        self.assertEqual(world.prison_online(self.db,'alice','session2',now=100500)['remaining'],20)
        with self.assertRaises(ValueError):world.require_travel(self.db,'alice')
        self.assertEqual(world.prison_online(self.db,'alice','session2',now=100520)['remaining'],0);self.db.commit()
        self.assertEqual(self.db.execute("SELECT town_id FROM character_locations WHERE account='alice'").fetchone()[0],3)
        self.assertIsNone(world.prison_state(self.db,'bob'));world.require_travel(self.db,'alice')

    def test_prison_mutation_rollback_conflicting_retry_and_clock_backwards(self):
        self.add('alice','Alice');self.db.commit();self.db.execute('BEGIN')
        world.sentence(self.db,'alice',100,'s1');self.db.rollback()
        self.assertIsNone(world.prison_state(self.db,'alice'))
        self.db.execute('BEGIN');world.sentence(self.db,'alice',100,'s1')
        with self.assertRaises(ValueError):world.sentence(self.db,'alice',101,'s1')
        world.prison_online(self.db,'alice','s',now=100);world.prison_online(self.db,'alice','s',now=90)
        self.assertEqual(world.prison_online(self.db,'alice','s',now=110)['remaining'],90)
        with self.assertRaises(ValueError):world.require_travel(self.db,'bob',10)
        self.db.commit()

    def test_new_prison_sentence_after_completion_restores_current_location(self):
        self.add('alice','Alice');self.db.commit();self.db.execute('BEGIN')
        world.sentence(self.db,'alice',10,'old');world.prison_online(self.db,'alice','s',now=0)
        self.assertEqual(world.prison_online(self.db,'alice','s',now=10)['remaining'],0)
        self.db.execute("UPDATE character_locations SET town_id=18,x=-120,y=80 WHERE account='alice'")
        world.sentence(self.db,'alice',10,'new');world.prison_online(self.db,'alice','newsession',now=100)
        self.assertEqual(world.prison_online(self.db,'alice','newsession',now=110)['remaining'],0)
        self.assertEqual(self.db.execute("SELECT town_id,x,y FROM character_locations WHERE account='alice'").fetchone(),(18,-120,80))
        self.db.commit()

    def test_detroit_original_grid_map_doors_containers_connected_native_ground6(self):
        from tio.map_generation import reachable_cells,connected
        from tio.protocol.battle_ground import encode_battle_ground,decode_battle_ground
        for mode,dimension in ((0,38),(1,50),(4,50)):
            m=world.generate_world_map(18,seed=7,deployment_size=6,mode=mode)
            self.assertEqual((m.arena.ground.width,m.arena.ground.height),(dimension,dimension))
            self.assertEqual(set(m.arena.ground.first_layer),{6});self.assertTrue(connected(m.arena,reachable_cells(m.arena)))
            self.assertEqual(decode_battle_ground(encode_battle_ground(m.arena.ground)),m.arena.ground)
            self.assertTrue(m.arena.doors);self.assertTrue(m.arena.containers)
            self.assertEqual(world.generate_world_map(18,seed=7,deployment_size=6,mode=mode).layout,m.layout)


if __name__=='__main__':unittest.main()
