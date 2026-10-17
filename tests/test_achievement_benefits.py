from contextlib import closing
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch
import json
import sqlite3
import tempfile
import unittest

from server.public_profile import read_profile
from tio.achievement_benefits import rating_bonus,influence_multiplier,total_rating,bonus_value
from tio.achievements import schema,update,event,assault_result,influence_received,ranked_result,AchievementStore,snapshots
from tio.db_transaction import transaction
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import encode_item_list
from tio.protocol.pet_info import decode_pet_info,encode_pet_info,PetInfo,SCHEMAS
from tio.warehouse import WarehouseStore

ROOT=Path(__file__).resolve().parents[1]


class BenefitReadTests(unittest.TestCase):
    def test_empty_database_is_read_only_and_neutral(self):
        with closing(sqlite3.connect(':memory:')) as db:
            self.assertEqual(rating_bonus(db,'alice'),0)
            self.assertEqual(influence_multiplier(db,'alice'),Fraction(1))
            self.assertEqual(total_rating(db,'alice',-2),-2)
            self.assertEqual(db.total_changes,0)
            self.assertEqual(db.execute('SELECT count(*) FROM sqlite_master').fetchone()[0],0)

    def test_earned_snapshot_bonuses_ignore_delivery_and_other_accounts(self):
        with closing(sqlite3.connect(':memory:')) as db,db:
            update(db,'alice',add={'clan_capture':1,'clan_defense':1,'battles':1000,'clan_influence':7500,'assault_top20':1})
            for delivered,notified in ((0,0),(1,1),(0,1),(1,0)):
                db.execute('UPDATE achievement_prizes SET delivered=?',(delivered,))
                db.execute('UPDATE achievement_awards SET notified=?',(notified,))
                before=db.total_changes
                self.assertEqual(rating_bonus(db,'alice'),200)
                self.assertEqual(influence_multiplier(db,'alice'),Fraction(11,10))
                self.assertEqual(rating_bonus(db,'bob'),0)
                self.assertEqual(influence_multiplier(db,'bob'),Fraction(1))
                self.assertEqual(db.total_changes,before)

    def test_duplicate_legacy_rows_do_not_multiply_and_conflicts_reject(self):
        with closing(sqlite3.connect(':memory:')) as db,db:
            db.execute('CREATE TABLE achievement_awards(account TEXT,id INTEGER,body TEXT)')
            body=json.dumps({'prizes':[{'kind':3,'value':75},{'kind':1,'value':1.05}]})
            db.executemany('INSERT INTO achievement_awards VALUES (?,?,?)',[('alice',1,body)]*2)
            self.assertEqual(rating_bonus(db,'alice'),75)
            self.assertEqual(influence_multiplier(db,'alice'),Fraction(21,20))
            db.execute('INSERT INTO achievement_awards VALUES (?,?,?)',('alice',1,json.dumps({'prizes':[]})))
            with self.assertRaises(ValueError):rating_bonus(db,'alice')

    def test_bounds_saturate_sum_and_reject_malformed_bonuses(self):
        for kind,values in ((3,(True,-1,0x100000000,1.5)),(1,(True,0,.5,float('nan'),float('inf'),0x100000000))):
            for value in values:
                with self.subTest(kind=kind,value=value),self.assertRaises(ValueError):bonus_value({'kind':kind,'value':value})
        with closing(sqlite3.connect(':memory:')) as db,db:
            schema(db)
            for i in (1,2):db.execute('INSERT INTO achievement_awards(account,id,body) VALUES (?,?,?)',('alice',i,json.dumps({'prizes':[{'kind':3,'value':0xffffffff}]})))
            self.assertEqual(rating_bonus(db,'alice'),0xffffffff)
            self.assertEqual(total_rating(db,'alice',100),0x7fffffff)
            self.assertEqual(total_rating(db,'bob',-(1<<32)),-(1<<31))
            for body in ('bad','[]','{"prizes": [1]}'):
                db.execute('DELETE FROM achievement_awards')
                db.execute('INSERT INTO achievement_awards(account,id,body) VALUES (?,?,?)',('alice',1,body))
                with self.assertRaises(ValueError):rating_bonus(db,'alice')


class AchievementHooksTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.path=Path(folder.name)/'players.db'
        data=json.loads((ROOT/'evidence/owned_pet_trial.json').read_text());self.pet=bytes.fromhex(data['packet_hex'])
        pets=OwnedPetStore(self.path)
        for a in ('alice','bob'):pets.ensure(a,self.pet,encode_item_list(1,()),human=True)
        self.store=AchievementStore(self.path,capacity=0)
        with transaction(self.path) as db:
            db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB,name_key TEXT)')
            db.execute('CREATE TABLE wallets(account TEXT PRIMARY KEY,credits INTEGER,gold INTEGER)')
            db.execute('CREATE TABLE soldier_ratings(account TEXT,pet_id INTEGER,rating INTEGER)')
            for a in ('alice','bob'):
                db.execute('INSERT INTO characters VALUES (?,1,?,?)',(a,a.title().encode(),a))
                db.execute('INSERT INTO wallets VALUES (?,1000,0)',(a,))
                db.execute('INSERT INTO soldier_ratings VALUES (?,1,-2)',(a,))

    def call(self,fn,*args,**kwargs):
        with transaction(self.path) as db:return fn(db,*args,**kwargs)

    def query(self,sql,args=()):
        with closing(sqlite3.connect(self.path)) as db:return db.execute(sql,args).fetchall()

    def test_public_rating_adds_earned_bonus_read_only_and_preserves_negative_base(self):
        self.call(update,'alice',add={'clan_capture':1,'clan_defense':1})
        before=self.path.read_bytes()
        self.assertEqual(read_profile(self.path,account='alice').rating,123)
        self.assertEqual(read_profile(self.path,account='bob').rating,-2)
        self.assertEqual(read_profile(self.path,account='alice',include_history=False).rating,0)
        self.assertEqual(self.path.read_bytes(),before)
        with transaction(self.path) as db:db.execute("UPDATE soldier_ratings SET rating=4294967295 WHERE account='alice'")
        self.assertEqual(read_profile(self.path,account='alice').rating,0x7fffffff)

    def test_bonus_delivery_finishes_even_with_full_warehouse_without_double_rating(self):
        self.call(update,'alice',add={'battles':1000,'clan_influence':7500,'kills':10})
        self.store.flush('alice');self.store.flush('alice')
        self.assertEqual(self.query('SELECT id,delivered FROM achievement_prizes WHERE id IN (10,12) ORDER BY id'),[(10,1),(12,1)])
        self.assertEqual(self.query('SELECT delivered FROM achievement_prizes WHERE id=4'),[(0,),(0,)])
        self.assertEqual(WarehouseStore(self.path).items('alice'),())
        self.assertEqual(read_profile(self.path,account='alice').rating,73)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(influence_multiplier(db,'alice'),Fraction(21,20))
        self.store.capacity=5;self.store.flush('alice')
        self.assertEqual(len(WarehouseStore(self.path).items('alice')),5)
        self.assertEqual(read_profile(self.path,account='alice').rating,73)

    def test_serialization_failure_rolls_back_delivery_and_earned_bonus_is_retained(self):
        self.call(update,'alice',add={'battles':1000})
        with patch('tio.achievements.encode_awards',side_effect=ValueError('fixture')):
            with self.assertRaises(ValueError):self.store.flush('alice')
        self.assertEqual(self.query('SELECT delivered FROM achievement_prizes'),[(0,)])
        self.assertEqual(self.query('SELECT notified FROM achievement_awards'),[(0,)])
        self.assertEqual(read_profile(self.path,account='alice').rating,73)
        self.store.flush('alice');self.assertEqual(self.query('SELECT delivered FROM achievement_prizes'),[(1,)])
        self.assertEqual(read_profile(self.path,account='alice').rating,73)

    def test_saved_prizes_survive_catalog_edits_and_unknown_rewards_stay_pending(self):
        self.call(update,'alice',add={'battles':1000})
        with patch('tio.achievements.catalog',return_value=()):self.store.flush('alice')
        self.assertEqual(read_profile(self.path,account='alice').rating,73)
        with transaction(self.path) as db:
            row=dict(id=999,level=0,prizes=[dict(kind=2,value=10)])
            db.execute('INSERT INTO achievement_awards(account,id,body) VALUES (?,?,?)',('alice',999,json.dumps(row)))
            db.execute('INSERT INTO achievement_prizes(account,id,position) VALUES (?,999,0)',('alice',))
        self.store.flush('alice')
        self.assertEqual(self.query('SELECT delivered FROM achievement_prizes WHERE id=999'),[(0,)])

    def test_event_replay_conflict_and_rollback_are_shared_authoritative(self):
        self.assertTrue(self.call(event,'alice','shared1',add={'kills':9}))
        self.assertFalse(self.call(event,'alice','shared1',add={'kills':9}))
        with self.assertRaises(ValueError):self.call(event,'alice','shared1',add={'kills':10})
        self.call(event,'bob','shared1',add={'kills':1})
        self.assertEqual(self.query('SELECT account,value FROM achievement_counters WHERE metric=? ORDER BY account',('kills',)),[('alice',9),('bob',1)])
        with transaction(self.path) as db:db.execute("CREATE TRIGGER fail_event BEFORE INSERT ON achievement_events BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.call(event,'alice','new',add={'kills':1})
        self.assertEqual(self.query("SELECT value FROM achievement_counters WHERE account='alice' AND metric='kills'"),[(9,)])
        self.assertFalse(self.query('SELECT id FROM achievement_awards WHERE id=4'))

    def test_counter_bounds_bad_metrics_and_missing_transaction_reject(self):
        self.call(event,'alice','max',add={'kills':0xffffffff})
        self.call(event,'alice','more',add={'kills':0xffffffff})
        self.assertEqual(self.query("SELECT value FROM achievement_counters WHERE account='alice' AND metric='kills'"),[(0xffffffff,)])
        for metric,value in (('bad.metric',1),('kills',True),('kills',-1)):
            with self.assertRaises(ValueError):self.call(event,'bob','bad',add={metric:value})
        with closing(sqlite3.connect(self.path)) as db:
            with self.assertRaises(RuntimeError):event(db,'alice','no_unit',add={'kills':1})

    def test_assault_cutoff_capture_defense_and_actual_influence_are_idempotent(self):
        self.call(assault_result,'alice','siege1',captured=True,place=20)
        self.call(assault_result,'alice','siege1',captured=True,place=20)
        self.call(assault_result,'bob','siege1',defended=True,place=21)
        self.call(influence_received,'alice','actual1',7499)
        self.call(influence_received,'alice','actual2',1)
        self.call(influence_received,'alice','actual2',1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(rating_bonus(db,'alice'),75);self.assertEqual(rating_bonus(db,'bob'),50)
            self.assertEqual(influence_multiplier(db,'alice'),Fraction(11,10));self.assertEqual(influence_multiplier(db,'bob'),Fraction(1))
        with self.assertRaises(ValueError):self.call(assault_result,'alice','invalid',captured=True,defended=True)
        with self.assertRaises(ValueError):self.call(assault_result,'alice','invalid',place=0)

    def test_league_tie_win_promotion_streak_and_snapshot_recovery(self):
        self.call(ranked_result,'alice','draw',result=2,league_before=3,league_after=3,streak=0)
        self.assertFalse(self.query('SELECT id FROM achievement_awards WHERE id=60'))
        self.call(ranked_result,'alice','win',result=1,league_before=3,league_after=2,streak=3)
        self.call(ranked_result,'alice','win',result=1,league_before=3,league_after=2,streak=3)
        self.assertEqual({r[0] for r in self.query("SELECT id FROM achievement_awards WHERE account='alice'")},{60,61,64})
        with self.assertRaises(ValueError):self.call(ranked_result,'bob','fake',result=2,league_before=3,league_after=3,streak=3)
        with transaction(self.path) as db:
            from tio.ranked import schema as ranked_schema
            ranked_schema(db);db.execute("INSERT INTO ranked_players VALUES ('bob',25,1,350,0,50,0,0,50,0,1)")
            snapshots(db,'bob')
        self.assertTrue({61,62,63,64,65,66,67}<={r[0] for r in self.query("SELECT id FROM achievement_awards WHERE account='bob'")})

    def test_actual_dog_level_and_clan_contribution_snapshots_do_not_invent_human_levels(self):
        fields=decode_pet_info(self.pet,human_equipment=True).fields
        dog={**fields,'0x8c43eb':2,'0x8c446f':3,'0x8c4aef':20}
        dog={k:dog.get(k,0) for k,_,_ in SCHEMAS[(False,bool(fields['0x6d0203']),bool(fields['0x8c4565']))]}
        packet=encode_pet_info(PetInfo(False,dog))
        with transaction(self.path) as db:
            db.execute('INSERT INTO owned_pets VALUES (?,2,0,?,?)',('alice',packet,encode_item_list(2,())))
            db.execute('CREATE TABLE clan_members(account TEXT,contribution INTEGER)')
            db.execute("INSERT INTO clan_members VALUES ('alice',7500)")
            snapshots(db,'alice');snapshots(db,'alice')
        earned={r[0] for r in self.query("SELECT id FROM achievement_awards WHERE account='alice'")}
        self.assertTrue({12,13}<=earned)
        self.assertFalse(earned&{15,16,17,18})
        self.assertEqual(self.query("SELECT value FROM achievement_counters WHERE account='alice' AND metric='clan_influence'"),[(7500,)])


if __name__=='__main__':unittest.main()
