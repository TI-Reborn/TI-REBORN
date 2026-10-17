from wallet_fixture import fund_wallet
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from tio import ranks
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.protocol.item_list import encode_item_list
from tio.battle_rewards import settle, receipt

ROOT=Path(__file__).resolve().parents[1]


class RankRulesTests(unittest.TestCase):
    def test_all_original_thresholds_and_negative_points(self):
        self.assertEqual(len(ranks.THRESHOLDS),29)
        for i,points in enumerate(ranks.THRESHOLDS,1):
            self.assertEqual(ranks.rank_id(points),i)
            if i>1:self.assertEqual(ranks.rank_id(points-1),i-1)
        self.assertEqual(ranks.rank_id(-100),1)
        self.assertEqual(ranks.rank_id(99999),29)
        self.assertEqual(ranks.RULES['ranks'][0]['english'],'Recruit')

    def test_kill_difference_rounding_minimum_and_level_table(self):
        for diff,expected in ((-9000,1),(-1000,8),(-500,9),(-499,10),(0,10),(499,10),(500,11),(9999,20)):
            self.assertEqual(ranks.kill_points(20,10000,20,10000+diff),expected)
        for level,minimum in enumerate(ranks.RULES['minimum_victim_level'],1):
            if minimum>1:self.assertEqual(ranks.kill_points(level,0,minimum-1,35000),0)
            self.assertEqual(ranks.kill_points(level,0,minimum,0),10)
        self.assertEqual(ranks.kill_points(9,0,9,0),0) # User chose literal manual.
        self.assertEqual(ranks.kill_points(10,0,14,0),0)
        self.assertEqual([ranks.level_cap(i) for i in (1,2,4,6,9,13,17,20)],
                         [120,320,1050,2400,5400,12000,22000,35000])


class RankStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.db'
        self.store=OwnedPetStore(self.path)
        self.wallet=WalletStore(self.path);fund_wallet(self.wallet.path, 'alice', credits=10_000, gold=10_000)
        data=json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        self.baseline=bytes.fromhex(data['packet_hex'])
        self.store.ensure('alice',self.baseline,encode_item_list(1,()),human=True)

    def fields(self,owner=1):
        with closing(sqlite3.connect(self.path)) as db:
            h,p=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?',('alice',owner)).fetchone()
        return decode_pet_info(p,human_equipment=bool(h)).fields

    def state(self,owner=1):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT points,debt FROM soldier_ranks WHERE account=? AND pet_id=?',('alice',owner)).fetchone()

    def seed(self,points,*,owner=1,level=1,debt=0):
        with closing(sqlite3.connect(self.path)) as db,db:
            pet=decode_pet_info(self.baseline,human_equipment=True)
            packet=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c43eb':owner,'0x8c4aef':level}))
            db.execute('INSERT OR REPLACE INTO owned_pets VALUES (?,?,?,?,?)',('alice',owner,1,packet,encode_item_list(owner,())))
            db.execute('INSERT OR REPLACE INTO soldier_ranks VALUES (?,?,?,?)',('alice',owner,points,debt))
            ranks.sync(db,'alice',now=100,active=True)

    def test_migration_and_restart_do_not_reset(self):
        f=self.fields();original=decode_pet_info(self.baseline,human_equipment=True).fields
        self.assertEqual((f['0x8c4bbc'],f['0x8c4bd0'],f['0x8c4bf6']),(1,0,20))
        for key in set(f)-{'0x8c4bbc','0x8c4bf6'}:self.assertEqual(f[key],original[key])
        settle(self.path,'alice','win',1,rank_report={1:(10,False)})
        self.store.ensure('alice',self.baseline,encode_item_list(1,()),human=True)
        self.assertEqual(self.state(),(20,0))
        self.assertEqual(self.fields()['0x8c4bbc'],2)
        self.assertEqual(self.fields()['0x8c4bf6'],30)
        settle(self.path,'alice','win',1,rank_report={1:(99,True)})
        self.assertEqual(self.state(),(20,0))
        self.assertEqual(self.wallet.ensure('alice').credits,10000)

    def test_death_escape_negative_and_recovery_are_distinct(self):
        settle(self.path,'alice','loss',0,rank_report={1:(10,True)})
        self.assertEqual(self.state(),(5,0))
        settle(self.path,'alice','flee',0,rank_report={1:(100,False)},escaped=True)
        self.assertEqual(self.state(),(-15,0))
        self.assertEqual(self.fields()['0x8c4bd0'],0xfffffff1)
        self.assertEqual(self.fields()['0x8c4bf6'],35)
        settle(self.path,'alice','win',1,rank_report={1:(10,False)})
        self.assertEqual(self.state(),(5,0))
        settle(self.path,'alice','leave_after_death',0,rank_report={1:(10,True)},escaped=True)
        self.assertEqual(self.state(),(10,0))

    def test_level_cap_and_commander_rank_not_overwritten_by_seed(self):
        self.seed(0,owner=2)
        settle(self.path,'alice','merc',1,rank_report={2:(200,False)})
        self.assertEqual(self.state(2),(120,0))
        self.assertEqual(self.fields(2)['0x8c4bbc'],1)
        # Personal points stay earned; promotion waits for commander advancement.
        settle(self.path,'alice','avatar',1,rank_report={1:(10,False)})
        self.assertEqual(self.fields(2)['0x8c4bbc'],2)
        self.seed(35000,level=20)
        settle(self.path,'alice','max',1,rank_report={1:(100,False)})
        self.assertEqual(self.fields()['0x8c4bbc'],29)
        self.assertEqual(self.fields()['0x8c4bf6'],0)

    def test_daily_decay_repeat_login_and_half_cost_recovery(self):
        self.seed(5000,level=18)
        ranks.refresh(self.path,'alice',now=100+ranks.DAY-1)
        self.assertEqual(self.state(),(5000,0))
        ranks.refresh(self.path,'alice',now=100+ranks.DAY)
        self.assertEqual(self.state(),(4950,50))
        ranks.refresh(self.path,'alice',now=100+ranks.DAY)
        self.assertEqual(self.state(),(4950,50))
        with closing(sqlite3.connect(self.path)) as db,db:
            ranks.settle_ranks(db,'alice','restore',0,{1:(25,False)},now=101+ranks.DAY)
        self.assertEqual(self.state(),(5000,0))
        self.seed(100,level=1)
        ranks.refresh(self.path,'alice',now=100+1000*ranks.DAY)
        self.assertEqual(self.state(),(99,1))
        self.seed(-30)
        ranks.refresh(self.path,'alice',now=100+1000*ranks.DAY)
        self.assertEqual(self.state(),(-30,0))

    def test_squad_weighting_and_credit_bonus_retry(self):
        self.seed(5000,level=18)
        self.seed(5000,owner=2,level=18)
        self.seed(5000,owner=3,level=18)
        self.seed(1500,owner=4,level=1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(ranks.squad_points(db,'alice'),5100)
            self.assertEqual(ranks.credit_percent(db,'alice'),20)
        # Zero rental units, +20% to a verified level-one PvP reward.
        from tio.reward_policy import RewardContext
        context=RewardContext((1,), (('bob',(1,)),), True)
        assets=settle(self.path,'alice','bonus',1,rank_report={1:(10,False)},rental_units=(),reward_context=context)
        self.assertEqual(assets.credits,10120)
        self.assertEqual(receipt(self.path,'alice','bonus'),(120,0))
        self.assertEqual(settle(self.path,'alice','bonus',1,rank_report={1:(10,False)},rental_units=(),reward_context=context),assets)
        self.seed(-50000,owner=4)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(ranks.credit_percent(db,'alice'),-23)
        self.seed(-1000000,owner=4)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(ranks.credit_percent(db,'alice'),-90)

    def test_invalid_actor_rolls_back_wallet_wounds_rank_and_journal(self):
        with self.assertRaises(ValueError):
            settle(self.path,'alice','bad',1,health={1:1},rank_report={1:(10,False),999:(10,False)})
        self.assertEqual(self.fields()['0x8c4ab1'],100)
        self.assertEqual(self.state(),(0,0))
        self.assertEqual(self.wallet.ensure('alice').credits,10000)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rank_battle_audit').fetchone()[0],0)

    def test_only_owned_killer_gets_points_and_escape_is_once(self):
        from tio.battle_state import BattleActor,BattleField
        from tio.combat import Combat
        from tio.weapons import WeaponCatalog
        from tio.arena_service import ArenaService
        from tio.protocol.battle_ground import BattleGround,encode_battle_ground
        field=BattleField(8,8,[BattleActor(1,7,1,1,15,100,100),BattleActor(2,8,4,4,15,100,100)],step_cost=1)
        field.combat=Combat(field,WeaponCatalog())
        field.combat.register(1,encode_item_list(1,()),human=True,path=self.path,account='alice',pet_packet=self.baseline)
        field.combat.register(2,encode_item_list(2,()),human=True,pet_packet=self.baseline)
        field.combat.rank_kills=[(1,2),(2,1)]
        self.assertEqual(ranks.battle_report(field.combat,7),{1:(10,False)})
        ground=encode_battle_ground(BattleGround(0,8,8,bytes(64),(),bytes(64)))
        scene=SimpleNamespace(field=field,packets=(ground,b'\x41'),actor_ids=(1,),bot_owner=8)
        arena=ArenaService();arena.start_survival(7,b'Alice',scene)
        arena.leave(7,b'\x2a\x01');arena.disconnect(7)
        self.assertEqual(self.state(),(-20,0))
        self.assertEqual(self.wallet.ensure('alice').credits,10000)
        roster=arena.city_roster_refresh(7,b'\x50\x01',self.path,'alice')
        self.assertEqual(ranks.signed(decode_pet_info(roster[0],human_equipment=True).fields['0x8c4bd0']),-20)

    def test_real_attack_victory_and_post_battle_roster(self):
        from tio.battle_state import BattleActor,BattleField
        from tio.combat import Combat
        from tio.weapons import WeaponCatalog
        from tio.arena_service import ArenaService
        from tio.protocol.battle_attack import AttackRequest,encode_attack_request
        from tio.protocol.battle_ground import BattleGround,encode_battle_ground
        field=BattleField(8,8,[BattleActor(1,7,1,1,15,100,100),BattleActor(2,8,2,1,15,1,100)],step_cost=1)
        combat=field.combat=Combat(field,WeaponCatalog(),rng=SimpleNamespace(randrange=lambda n:0,randint=lambda a,b:a))
        combat.register(1,encode_item_list(1,()),human=False,path=self.path,account='alice')
        combat.register(2,encode_item_list(2,()),human=False)
        ground=encode_battle_ground(BattleGround(0,8,8,bytes(64),(),bytes(64)))
        scene=SimpleNamespace(field=field,packets=(ground,b'\x41'),actor_ids=(1,),bot_owner=8)
        arena=ArenaService();arena.start_survival(7,b'Alice',scene)
        arena.member_loaded(7,b'\x36');arena.begin_turn_packets(7,(1,),40)
        arena.attack(7,encode_attack_request(AttackRequest(1,2,1)))
        self.assertEqual(combat.rank_kills,[(1,2)])
        replies=arena.finish_training(7,self.path,'alice')
        self.assertEqual(replies[-1][0],0x4c)
        self.assertEqual(self.state(),(20,0))
        self.assertEqual(self.wallet.ensure('alice').credits,10000)
        roster=arena.city_roster_refresh(7,b'\x50\x01',self.path,'alice')
        f=decode_pet_info(roster[0],human_equipment=True).fields
        self.assertEqual((f['0x8c4bbc'],f['0x8c4bd0'],f['0x8c4bf6']),(2,20,30))


if __name__=='__main__':unittest.main()
