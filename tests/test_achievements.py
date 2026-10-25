from wallet_fixture import fund_wallet
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tio.achievements import AchievementStore,BattleAchievements,catalog,update,upgraded,schema
from tio.battle_rewards import settle
from tio.battle_state import BattleActor,BattleField
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import encode_item_list
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.achievements import decode_request
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore

ROOT=Path(__file__).resolve().parents[1]


class AchievementTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'state.db'
        self.wallet=WalletStore(self.path);fund_wallet(self.wallet.path, 'alice', credits=10_000, gold=10_000)
        data=json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        self.pet=bytes.fromhex(data['packet_hex'])
        self.pets=OwnedPetStore(self.path)
        self.pets.ensure('alice',self.pet,encode_item_list(1,()),human=True)
        self.store=AchievementStore(self.path)

    def query(self,sql,args=()):
        with closing(sqlite3.connect(self.path)) as db:return db.execute(sql,args).fetchall()

    def progress(self,**kwargs):
        with closing(sqlite3.connect(self.path)) as db,db:update(db,'alice',**kwargs)

    def earned(self):
        return {r[0] for r in self.query('SELECT id FROM achievement_awards WHERE account=?',('alice',))}

    def test_catalog_request_unknown_target_and_no_query_awards(self):
        self.assertEqual(len(catalog()),58)
        self.assertEqual(decode_request(b'\xb5\x01\x00ProbeNew\0'),(0,'ProbeNew'))
        packet=self.store.handle('alice',b'\xb5\x01\x00ProbeNew\0',b'ProbeNew')
        self.assertEqual(packet[:3],b'\xb5\x02\0')
        for request in (b'\xb5\x01',b'\xb5\x01\0ProbeNew',b'\xb5\x01\0ProbeNew\0x',
                        b'\xb5\x01\1ProbeNew\0',b'\xb5\x01\0Bob\0',b'\xb5\x03\0ProbeNew\0'):
            with self.assertRaises(ValueError):self.store.handle('alice',request,'ProbeNew')
        self.assertFalse(self.earned())

    def test_tenth_kill_awards_original_items_once_and_survives_restart(self):
        self.progress(add={'kills':9});self.assertNotIn(4,self.earned())
        self.progress(add={'kills':1});self.assertIn(4,self.earned())
        self.assertFalse(WarehouseStore(self.path).items('alice'))
        replies=self.store.flush('alice')
        self.assertEqual(replies[0][:2],b'\xb5\x03')
        items=WarehouseStore(self.path).items('alice')
        self.assertEqual(sorted(i.template_id for i in items),[10,10,317,317,317])
        self.assertEqual(len({i.instance_id for i in items}),5)
        self.progress(add={'kills':20})
        again=AchievementStore(self.path)
        again.handle('alice',b'\xb5\x01\0ProbeNew\0','ProbeNew')
        self.assertEqual(again.flush('alice'),())
        self.assertEqual(WarehouseStore(self.path).items('alice'),items)

    def test_full_warehouse_keeps_prize_pending_then_delivers(self):
        self.progress(add={'kills':10})
        self.store.capacity=2;self.store.flush('alice')
        self.assertEqual([i.template_id for i in WarehouseStore(self.path).items('alice')],[10,10])
        self.assertEqual(self.query('SELECT position,delivered FROM achievement_prizes WHERE id=4 ORDER BY position'),[(0,0),(1,1)])
        self.store.capacity=5;self.store.flush('alice');self.store.flush('alice')
        self.assertEqual(len(WarehouseStore(self.path).items('alice')),5)

    def test_temporary_credits_once_and_other_account_isolation(self):
        self.progress(add={'shop_purchase':1})
        self.store.flush('bob')
        self.assertEqual(self.wallet.ensure('alice').credits,10000)
        self.store.flush('alice');self.store.flush('alice')
        self.assertEqual(self.wallet.ensure('alice').credits,10100)
        self.assertEqual(self.query('SELECT delivered FROM achievement_prizes WHERE id=38'),[(1,)])

    def test_transaction_failure_rolls_back_counter_award_and_wallet(self):
        with self.assertRaisesRegex(RuntimeError,'abort'):
            with closing(sqlite3.connect(self.path)) as db,db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('UPDATE wallets SET credits=1')
                update(db,'alice',add={'shop_purchase':1})
                raise RuntimeError('abort')
        self.assertEqual(self.wallet.ensure('alice').credits,10000)
        self.assertFalse(self.earned())

    def test_serialization_failure_rolls_back_delivery(self):
        self.progress(add={'kills':10})
        with patch('tio.achievements.encode_awards',side_effect=ValueError('bad packet')):
            with self.assertRaises(ValueError):self.store.flush('alice')
        self.assertFalse(WarehouseStore(self.path).items('alice'))
        self.assertEqual(self.query('SELECT notified FROM achievement_awards'),[(0,)])
        self.store.flush('alice')
        self.assertEqual(len(WarehouseStore(self.path).items('alice')),5)

    def test_distinct_upgrade_items_not_repeat_levels_or_se_resets(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            for _ in range(40):upgraded(db,'alice',1001)
        self.assertEqual(self.earned(),{39})
        with closing(sqlite3.connect(self.path)) as db,db:
            for n in range(1002,1031):upgraded(db,'alice',n)
        self.assertEqual(self.earned(),{39,41})

    def test_battle_settlement_retry_cannot_multiply_counters(self):
        report=dict(mode=4,clean=True,counters={'kills':10,'crates':2,'attack_kills':3})
        for _ in range(2):settle(self.path,'alice','battle1',1,achievement_report=report)
        values=dict(self.query('SELECT metric,value FROM achievement_counters'))
        self.assertEqual((values['kills'],values['crates'],values['battles'],values['wall_wins']),(10,2,1,1))
        self.assertIn(30,self.earned());self.assertNotIn(31,self.earned())
        settle(self.path,'alice','escape',0,escaped=True,achievement_report=report)
        values=dict(self.query('SELECT metric,value FROM achievement_counters'))
        self.assertEqual((values['battles'],values['wall_wins']),(2,1))

    def test_level_snapshots_and_million_are_current_state_not_invented_history(self):
        p=decode_pet_info(self.pet,human_equipment=True)
        p=replace(p,fields={**p.fields,'0x8c4aef':10})
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET pet_packet=?',(encode_pet_info(p),))
            db.execute('UPDATE wallets SET credits=1000000')
        self.store.handle('alice',b'\xb5\x01\0ProbeNew\0','ProbeNew')
        self.assertEqual(self.earned(),{8,15,16})

    def test_enhanced_prize_and_earned_rating_are_delivered_separately(self):
        self.progress(maximum={'attack_kills':2},add={'battles':1000})
        self.store.flush('alice')
        item,=WarehouseStore(self.path).items('alice')
        self.assertEqual((item.template_id,item.unknown_bytes_03[0]),(317,3))
        self.assertEqual(self.query('SELECT delivered FROM achievement_prizes WHERE id=10'),[(1,)])
        from tio.achievement_benefits import rating_bonus
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(rating_bonus(db,'alice'),75)

    def test_sc_purchase_and_real_enhancement_events(self):
        from tio.sc_shop import SCShopStore
        from test_sc_shop import request as sc_request
        shop=SCShopStore(self.path)
        lot=next(o.lot_id for o in shop.offers.values() if o.item_id==314 and o.enhancement==0)
        shop.handle('alice',sc_request(9,lot))
        self.assertNotIn(36,self.earned())
        with self.assertRaises(ValueError):shop.handle('alice',sc_request(6,lot,999,1))
        self.assertNotIn(36,self.earned())
        shop.handle('alice',sc_request(6,lot,1,1))  # Currency 1: SC accepts credits only.
        self.assertIn(36,self.earned())
        from tio.enhancement import EnhancementStore
        from test_enhancement import item,request
        def seed(template,level):
            with closing(sqlite3.connect(self.path)) as db,db:
                db.execute('UPDATE owned_pets SET inventory_packet=?',
                           (encode_item_list(1,(item(1001,template,level),item(1002,30))),))
        seed(301,2)
        EnhancementStore(self.path,randbelow=lambda n:0).handle('alice',request())
        self.assertIn(39,self.earned())
        seed(248,16)
        EnhancementStore(self.path,randbelow=lambda n:99).handle('alice',request())
        self.assertNotIn(49,self.earned())
        seed(301,15)
        EnhancementStore(self.path,randbelow=lambda n:99).handle('alice',request())
        self.assertNotIn(49,self.earned())
        seed(301,16)
        EnhancementStore(self.path,randbelow=lambda n:99).handle('alice',request())
        self.assertIn(49,self.earned())

    def test_loopback_answers_captured_b501(self):
        from tools.audit_unanswered_requests import replay
        replies=replay('b5010050726f62654e657700')
        self.assertEqual(len(replies),1)
        self.assertTrue(replies[0].startswith('b5020050726f62654e6577003a000000'))

    def test_awarded_prize_snapshot_survives_later_balance_edits(self):
        self.progress(add={'kills':10})
        original=self.store.handle('alice',b'\xb5\x01\0ProbeNew\0','ProbeNew')
        altered=[{**r,'prizes':[],'temporary_credits':9999} if r['id']==4 else r for r in catalog()]
        with patch('tio.achievements.catalog',return_value=altered):
            self.assertEqual(self.store.handle('alice',b'\xb5\x01\0ProbeNew\0','ProbeNew'),original)
            self.store.flush('alice')
        self.assertEqual(len(WarehouseStore(self.path).items('alice')),5)
        self.assertEqual(self.wallet.ensure('alice').credits,10000)


class BattleAchievementTests(unittest.TestCase):
    def test_streaks_per_actor_reset_on_hit_and_no_critical_bite_award(self):
        stats=BattleAchievements();actor=BattleActor(1,7,1,1,15,100,100);enemy=replace(actor,actor_id=2,owner_id=8,x=2)
        for _ in range(2):stats.attack(actor,0,301,'Light',[(enemy,False,False,False,True)])
        stats.attack(actor,0,301,'Light',[(enemy,True,False,False,True)])
        self.assertEqual(stats.counters[7]['miss_streak'],2)
        for _ in range(3):stats.attack(actor,0,301,'Light',[(enemy,False,False,False,True)])
        self.assertEqual((stats.counters[7]['miss_streak'],stats.counters[8]['dodge_streak']),(3,3))
        for _ in range(3):stats.attack(actor,0,333,'Melee',[(enemy,True,True,False,True)])
        self.assertEqual(stats.counters[7]['critical_streak'],0)
        for _ in range(3):stats.attack(actor,0,301,'Light',[(enemy,True,True,False,True)])
        self.assertEqual(stats.counters[7]['critical_streak'],3)

    def test_turn_and_attack_kills_are_different_and_clean_includes_allies(self):
        stats=BattleAchievements();a=BattleActor(1,7,1,1,15,100,100);b=replace(a,actor_id=2,owner_id=8,x=2)
        stats.attack(a,0,300,'Melee',[(b,True,False,True,False)])
        stats.attack(a,0,300,'Melee',[(b,True,False,True,True)])
        stats.attack(a,1,300,'Melee',[(b,True,False,True,True)])
        c=stats.counters[7]
        self.assertEqual((c['attack_kills'],c['turn_kills'],c['match_kills'],c['fist_kills'],c['unseen_kills']),(1,2,3,3,1))
        ally=replace(a,actor_id=3,owner_id=9,x=3,health=0)
        f=BattleField(8,8,[a,b,ally],step_cost=1,teams={7:0,9:0,8:1})
        self.assertFalse(stats.report(f,7,1)['clean'])

    def test_accepted_combat_only_and_actual_crate_reopen(self):
        from test_combat import CombatTests
        from tio.protocol.battle_attack import AttackRequest
        f,c=CombatTests().setup_combat()
        f._actors[2]=replace(f.actor(2),health=1)
        c.attack(7,AttackRequest(1,5,1))
        self.assertEqual(c.achievements.counters[7]['kills'],1)
        before=json.dumps(c.achievements.counters,sort_keys=True)
        with self.assertRaises(ValueError):c.attack(7,AttackRequest(1,5,1))
        self.assertEqual(json.dumps(c.achievements.counters,sort_keys=True),before)
        from tio.battle_loot import BattleLoot
        from tio.protocol.battle_position import BattlePositionRequest
        loot=BattleLoot(c,[(2,2)])
        loot.open(7,BattlePositionRequest(1,2,2),0)
        loot.open(7,BattlePositionRequest(1,2,2),0)
        self.assertEqual(c.achievements.counters[7]['crates'],1)
