from wallet_fixture import fund_wallet
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from tio.weapon_proficiency import ProficiencyRules,SAVED,BASE,CAPS,bits,number,damage_endpoint
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.protocol.item_list import encode_item_list
from tio.owned_pets import OwnedPetStore
from tio.combat import Combat
from tio.weapons import WeaponCatalog
from tio.battle_state import BattleActor,BattleField
from tio.arena_service import ArenaService
from test_combat import item,FixedRandom

ROOT=Path(__file__).resolve().parents[1]

def profile(level=1):
    raw=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
    p=decode_pet_info(raw,human_equipment=True)
    f={**p.fields,'0x8c43eb':1,'0x8c4aef':level,**{k:bits(10) for k in (*SAVED,*BASE)},**{k:0 for k in CAPS}}
    return ProficiencyRules().normalize(encode_pet_info(replace(p,fields=f)),True)

def change(packet,values):
    p=decode_pet_info(packet,human_equipment=True)
    return encode_pet_info(replace(p,fields={**p.fields,**values}))

def setup(weapon=304,packet=None,miss=False):
    catalog=WeaponCatalog();w=catalog.weapons[weapon]
    inv=encode_item_list(1,(item(1,weapon,equipped=True),item(2,w.ammo_id,100)) if w.ammo_id else (item(1,weapon,3,True),))
    field=BattleField(12,12,[BattleActor(1,7,1,1,40,100,100),BattleActor(2,8,5,1,40,1000,1000)],step_cost=1)
    combat=Combat(field,catalog,rng=SimpleNamespace(randrange=lambda n:99,randint=lambda a,b:a) if miss else FixedRandom())
    combat.register(1,inv,human=True,pet_packet=packet or profile())
    return field,combat

class WeaponProficiencyTests(unittest.TestCase):
    def test_initial_caps_and_fractional_progress_preserved(self):
        rules=ProficiencyRules();p=profile();f=decode_pet_info(p,human_equipment=True).fields
        self.assertEqual([number(f[k]) for k in SAVED],[35,35,35,35,35,35,0,35])
        self.assertEqual(tuple(f[k] for k in CAPS),(75,285,75))
        self.assertEqual(rules.caps(10,True),(120,465))
        self.assertEqual(rules.caps(26,True),(200,785))
        self.assertEqual(rules.caps(255,False),(200,200))
        p=change(p,{SAVED[4]:bits(55.125)})
        normalized=rules.normalize(p,True)
        self.assertEqual(rules.value(normalized,True,'Automatic'),55.125)
        self.assertEqual(rules.normalize(normalized,True),normalized)

    def test_all_catalog_categories_damage_and_slowdown(self):
        r=ProficiencyRules();p=profile(26)
        for w in WeaponCatalog().weapons.values():
            trained=r.train(p,True,w.weapon_type,w.attack_ap,True)
            self.assertGreater(r.value(trained,True,w.weapon_type),35)
        self.assertEqual(damage_endpoint(50,35),42)
        self.assertEqual(damage_endpoint(75,35),63)
        self.assertEqual(damage_endpoint(120,200),267)
        hit=r.train(p,True,'Automatic',5,True)
        miss=r.train(p,True,'Automatic',5,False)
        self.assertAlmostEqual(r.value(hit,True,'Automatic')-35,.2,places=4)
        self.assertAlmostEqual(r.value(miss,True,'Automatic')-35,.07,places=4)
        high=change(p,{SAVED[4]:bits(100)})
        self.assertAlmostEqual(r.value(r.train(high,True,'Automatic',5,True),True,'Automatic')-100,.07,places=4)
        for v in (float('nan'),float('inf'),-1):
            with self.assertRaises(ValueError):r.normalize(change(p,{SAVED[0]:bits(v)}),True)

    def test_individual_total_and_absolute_caps(self):
        r=ProficiencyRules()
        p=change(profile(),{SAVED[4]:bits(74.99)})
        out=r.train(p,True,'Automatic',100,True)
        self.assertEqual(r.value(out,True,'Automatic'),75)
        self.assertEqual(r.train(out,True,'Automatic',100,True),out)
        # Total ceiling can stop another skill even below its individual ceiling.
        out=r.train(out,True,'Light',100,True)
        self.assertEqual(r.value(out,True,'Light'),35)
        p=change(profile(26),{SAVED[4]:bits(199.99)})
        self.assertEqual(r.value(r.train(p,True,'Automatic',100,True),True,'Automatic'),200)

    def test_attack_persists_only_used_skill_and_atomic_failure(self):
        field,c=setup();p=c.proficiencies[1]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.db';store=OwnedPetStore(path)
            store.ensure('alice',p,c.inventories[1],human=True)
            c.persistence[1]=(path,'alice')
            c.attack(7,AttackRequest(1,5,1))
            saved=store.list('alice')[0][1]
            # AK47 at four cells: 50 -> 45 after falloff -> 38 at skill35.
            self.assertEqual(field.actor(2).health,962)
            self.assertGreater(c.proficiency_rules.value(saved,True,'Automatic'),35)
            self.assertEqual(c.proficiency_rules.value(saved,True,'Distance'),35)
            # Failed CAS must roll back ammunition, AP, health, skill and statistics.
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('UPDATE owned_pets SET pet_packet=?',(change(saved,{SAVED[4]:bits(50)}),))
            before=(dict(field._actors),dict(c.proficiencies),dict(c.inventories),dict(c.statistics))
            inv=c.inventories[1]
            with self.assertRaisesRegex(ValueError,'proficiency changed'):c.attack(7,AttackRequest(1,5,1))
            self.assertEqual((field._actors,c.proficiencies,c.inventories,c.statistics),before)
            self.assertEqual(store.inventory('alice',1),inv)

    def test_miss_awp_grenade_and_no_extra_award_per_victim(self):
        f,c=setup(312,miss=True);f._actors[2]=replace(f.actor(2),x=8)
        c.attack(7,AttackRequest(1,8,1))
        self.assertEqual(f.actor(2).health,1000)
        self.assertGreater(c.proficiency_rules.value(c.proficiencies[1],True,'Distance'),35)
        self.assertEqual(c.proficiency_rules.value(c.proficiencies[1],True,'Automatic'),35)
        profiles=[]
        for extra in (False,True):
            f,c=setup(317)
            if extra:f._actors[3]=BattleActor(3,8,5,2,40,1000,1000)
            c.attack(7,AttackRequest(1,5,1));profiles.append(c.proficiencies[1])
        self.assertEqual(*profiles)
        f,c=setup(317);c.attack(7,AttackRequest(1,1,6))
        self.assertGreater(c.proficiency_rules.value(c.proficiencies[1],True,'Throwing'),35)

    def test_no_training_after_terminal_turn_or_invalid_action(self):
        f,c=setup();f.combat=c;f._actors[2]=replace(f.actor(2),health=1)
        arena=ArenaService(clock=lambda:10)
        arena.rooms=SimpleNamespace(snapshot=lambda:(SimpleNamespace(room_id=1,members=(7,8)),))
        arena._fields[1]=f;arena._turns={1:(7,{1},20)}
        before=c.proficiencies[1]
        with self.assertRaises(ValueError):arena.attack(8,encode_attack_request(AttackRequest(1,5,1)))
        self.assertEqual(c.proficiencies[1],before)
        arena.attack(7,encode_attack_request(AttackRequest(1,5,1)))
        after=c.proficiencies[1]
        with self.assertRaises(ValueError):arena.attack(7,encode_attack_request(AttackRequest(1,5,1)))
        self.assertEqual(c.proficiencies[1],after)

    def test_dog_melee_city_reload_and_battle_update(self):
        from tio.hiring import HireStore
        from tio.city_catalogs import CityCatalogs
        from tio.wallets import WalletStore
        from tio.protocol.battle_soldier import decode_battle_soldier
        from tools.battle_actor_fixture import actor_packet
        from tio.visibility import VisibilityView
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.db';fund_wallet(path, 'alice', credits=10_000, gold=10_000)
            template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
            hire=HireStore(path,CityCatalogs(ROOT/'config/city_catalogs.json'),template)
            p,inv,_=hire.hire('alice',3)
            pet=decode_pet_info(p,human_equipment=False);owner=pet.fields['0x8c43eb']
            self.assertEqual([number(pet.fields[k]) for k in SAVED],[35,0,0,0,0,0,0,0])
            f=BattleField(10,10,[BattleActor(owner,7,1,1,17,100,100),BattleActor(99,8,2,1,17,100,100)],step_cost=1)
            c=Combat(f,WeaponCatalog(),rng=FixedRandom())
            c.register(owner,inv,human=False,path=path,account='alice',pet_packet=p)
            template=decode_battle_soldier(actor_packet(p,7,inv,human=False,x=1,y=1),human_equipment=False)
            view=VisibilityView(f,7,{owner:template});view.visible=frozenset((owner,99))
            replies=c.attack(7,AttackRequest(owner,2,1),view=view)
            self.assertEqual(f.actor(99).health,58)
            update=decode_battle_soldier(replies[-1],human_equipment=False)
            self.assertAlmostEqual(number(update.fields['0x8c54cc']),35.2,places=4)
            self.assertEqual(update.fields['0x8c571d'],12)
            saved=OwnedPetStore(path).list('alice')[0][1]
            self.assertEqual(c.proficiencies[owner],saved)
            # Death/disconnect need no successful battle settlement to retain gains.
            f._actors[owner]=replace(f.actor(owner),health=0)
            c2=Combat(f,WeaponCatalog())
            c2.register(owner,c.inventories[owner],human=False,pet_packet=saved)
            self.assertAlmostEqual(c2.proficiency_rules.value(c2.proficiencies[owner],False,'Melee'),35.2,places=4)
            with self.assertRaises(ValueError):c2.proficiency_rules.train(saved,False,'Automatic',5,True)
