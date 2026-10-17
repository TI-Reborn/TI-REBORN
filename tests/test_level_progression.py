from wallet_fixture import fund_wallet
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tio import level_progression as levels
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.pet_info import PetInfo,SCHEMAS,decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
from tio.battle_rewards import settle
from tio.battle_state import BattleActor,BattleField
from tio.combat import Combat
from tio.weapons import WeaponCatalog

ROOT=Path(__file__).resolve().parents[1]


class ProgressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.db'
        self.store=OwnedPetStore(self.path);fund_wallet(self.path, 'alice', credits=10_000, gold=10_000)
        self.base=decode_pet_info(bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex']),human_equipment=True).fields

    def seed(self,owner=1,resource=1,level=1,xp=0,hp=60):
        human=resource in (1,2,6)
        f={**self.base,'0x8c43eb':owner,'0x8c446f':resource,levels.LEVEL:level,levels.XP:xp,
           '0x8c4a07':(98 if resource==6 else 85)+5*(level-1),'0x8c4ab1':hp}
        f={k:f.get(k,0) for k,_,_ in SCHEMAS[(human,bool(f['0x6d0203']),bool(f['0x8c4565']))]}
        pet=encode_pet_info(PetInfo(human,f));inventory=encode_item_list(owner,())
        self.store.ensure('alice',pet,inventory,human=human)
        return pet

    def fields(self,owner=1,projected=False):
        if projected:
            row=next(p for i,p,_ in self.store.list('alice') if i==owner)
            return decode_pet_info(row,human_equipment=self.human(owner)).fields
        with closing(sqlite3.connect(self.path)) as db:
            h,p=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?',('alice',owner)).fetchone()
        return decode_pet_info(p,human_equipment=bool(h)).fields

    def human(self,owner):
        with closing(sqlite3.connect(self.path)) as db:return bool(db.execute('SELECT human FROM owned_pets WHERE pet_id=?',(owner,)).fetchone()[0])

    def test_all_native_boundaries_and_invalid_values(self):
        for level,floor in enumerate(levels.FLOORS,1):
            self.assertEqual(levels.level_for_xp(floor),level)
            if level>1:self.assertEqual(levels.level_for_xp(floor-1),level-1)
        self.assertEqual(levels.level_for_xp(levels.MAX_XP),20)
        for bad in (-1,levels.MAX_XP+1,1.5,True):
            with self.assertRaises(ValueError):levels.level_for_xp(bad)

    def test_all_six_species_gain_levels_hp_capacity_and_caps(self):
        for resource in range(1,7):
            self.seed(resource,resource)
        before={i:self.fields(i,True) for i in range(1,7)}
        settle(self.path,'alice','multi',1,experience_report={i:7355 for i in range(1,7)})
        for i in range(1,7):
            after=self.fields(i,True)
            self.assertEqual((after[levels.LEVEL],after[levels.XP]),(4,7355))
            self.assertEqual(after['0x8c4a07'],before[i]['0x8c4a07']+15)
            self.assertEqual(after['0x8c4b57'],before[i]['0x8c4b57']+150)
            self.assertGreater(after['0x8c49b9'],before[i]['0x8c49b9'])
            self.assertEqual(after['0x8c4ab1'],60)
        restored={i:self.fields(i) for i in range(1,7)}
        settle(self.path,'alice','multi',1,experience_report={i:99999 for i in range(1,7)})
        self.assertEqual(restored,{i:self.fields(i) for i in range(1,7)})

    def test_manual_level_migration_and_clamp_do_not_demote_or_repeat(self):
        self.seed(level=4,xp=0,resource=6)
        f=self.fields();self.assertEqual((f[levels.LEVEL],f[levels.XP]),(4,7355))
        for _ in range(3):self.store.list('alice')
        self.assertEqual(self.fields(),f)
        settle(self.path,'alice','cap',1,experience_report={1:levels.MAX_XP})
        f=self.fields();self.assertEqual((f[levels.LEVEL],f[levels.XP]),(20,levels.MAX_XP))
        settle(self.path,'alice','cap2',1,experience_report={1:500})
        self.assertEqual(self.fields(),f)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT gain FROM experience_battle_audit WHERE match_id='cap2'").fetchone()[0],0)

    def test_death_and_escape_save_experience_without_reviving(self):
        self.seed()
        settle(self.path,'alice','lost',0,health={1:0},experience_report={1:1400})
        self.assertEqual((self.fields()[levels.LEVEL],self.fields()['0x8c4ab1']),(2,0))
        settle(self.path,'alice','escaped',0,escaped=True,experience_report={1:100})
        self.assertEqual(self.fields()[levels.XP],1500)

    def test_rollback_isolation_and_retry(self):
        self.seed();before=self.fields()
        with self.assertRaises(ValueError):
            settle(self.path,'alice','bad',1,health={1:0},experience_report={1:1400,999:1400})
        self.assertEqual(self.fields(),before)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,10000)
        settle(self.path,'alice','bad',1,experience_report={1:1400})
        self.assertEqual(self.fields()[levels.LEVEL],2)
        fund_wallet(self.path, 'bob', credits=10_000, gold=10_000)
        with self.assertRaises(ValueError):settle(self.path,'bob','other',1,experience_report={1:1400})

    def combat(self):
        actors=[BattleActor(1,7,1,1,30,85,85),BattleActor(2,8,2,1,30,85,85),BattleActor(3,7,1,2,30,85,85)]
        field=BattleField(8,8,actors,step_cost=1)
        combat=field.combat=Combat(field,WeaponCatalog(),rng=SimpleNamespace(randrange=lambda n:0,randint=lambda a,b:a))
        for i in (1,2,3):combat.register(i,encode_item_list(i,()),human=False)
        return field,combat

    def test_actual_attack_miss_failed_action_friendly_fire_and_healing_budget(self):
        from tio.protocol.battle_attack import AttackRequest
        f,c=self.combat()
        c.rng=SimpleNamespace(randrange=lambda n:99)
        c.attack(7,AttackRequest(1,2,1));self.assertEqual(c.experience.totals,{})
        c.rng=SimpleNamespace(randrange=lambda n:0,randint=lambda a,b:a)
        c.attack(7,AttackRequest(1,2,1))
        damage=85-f.actor(2).health
        self.assertEqual(c.experience.totals,{1:damage*4,2:damage*2})
        before=dict(c.experience.totals)
        with self.assertRaises(ValueError):c.attack(8,AttackRequest(1,2,1))
        self.assertEqual(c.experience.totals,before)
        c.experience.damage(c,f.actor(1),f.actor(3),40)
        self.assertEqual(c.experience.totals,before)
        c.experience.damage(c,f.actor(1),f.actor(2),85)
        self.assertEqual(c.experience.totals,{1:340,2:170})
        c.experience.damage(c,f.actor(1),f.actor(2),85)
        self.assertEqual(c.experience.totals,{1:340,2:170})

    def test_failed_inventory_commit_does_not_award_experience(self):
        from tio.protocol.battle_attack import AttackRequest
        f,c=self.combat()
        with patch.object(c,'_persist_batch',side_effect=ValueError('CAS')):
            with self.assertRaises(ValueError):c.attack(7,AttackRequest(1,2,1))
        self.assertEqual(c.experience.totals,{})
        self.assertEqual(f.actor(2).health,85)

    def test_strength_fractional_earnings_and_only_participating_owned_fighters(self):
        f,c=self.combat();c.rank_profiles[2]=(4,0)
        c.experience.damage(c,f.actor(1),f.actor(2),1)
        c.experience.damage(c,f.actor(1),f.actor(2),1)
        self.assertEqual(c.experience.totals[1],Fraction(58,5))
        c.persistence={1:(self.path,'alice'),2:(self.path,'other'),999:(self.path,'alice')}
        self.assertEqual(c.experience.report(c,7),{1:11})

    def test_finished_battle_updates_native_actor_before_result_and_city_roster(self):
        from tio.arena_service import ArenaService
        from tio.protocol.battle_ground import BattleGround,encode_battle_ground
        from tio.protocol.battle_soldier import decode_battle_soldier
        from tools.battle_actor_fixture import actor_packet
        from tio.visibility import VisibilityView
        pet=self.seed(resource=3,xp=1390)
        f,c=self.combat();f._actors.pop(3);f._actors[2]=replace(f.actor(2),health=0)
        c.register(1,encode_item_list(1,()),human=False,path=self.path,account='alice',pet_packet=pet)
        c.experience.totals[1]=20
        template=decode_battle_soldier(actor_packet(pet,7,encode_item_list(1,()),human=False),human_equipment=False)
        view=VisibilityView(f,7,{1:template})
        scene=SimpleNamespace(field=f,visibility=view,actor_ids=(1,),bot_owner=8,
            packets=(encode_battle_ground(BattleGround(0,8,8,bytes(64),(),bytes(64))),b'\x41'))
        arena=ArenaService();arena.start_survival(7,b'Alice',scene)
        replies=arena.finish_training(7,self.path,'alice')
        self.assertEqual([p[0] for p in replies],[0x39,0xc8,0x3b,0x4e,0x4c])
        actor=decode_battle_soldier(replies[2],human_equipment=False).fields
        self.assertEqual((actor['0x8c5134'],actor['0x8c514b'],actor['0x8c566a']),(2,1410,90))
        self.assertEqual(replies[-1][28],1)
        self.assertEqual(int.from_bytes(replies[-1][33:37],'little'),20)
        self.assertFalse(arena.finish_training(7,self.path,'alice'))
        self.assertEqual(self.fields()[levels.XP],1410)
        self.assertEqual(self.fields(1,True)['0x8c4b57'],200)


if __name__=='__main__':unittest.main()
