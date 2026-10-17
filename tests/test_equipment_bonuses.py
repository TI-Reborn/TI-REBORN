from contextlib import closing
from dataclasses import replace
import sqlite3
import unittest
import test_equipment
from tio.equipment_bonuses import bonuses,project
from tio.protocol.item_list import decode_item_list,encode_item_list
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.weapon_proficiency import ProficiencyRules,SAVED,BASE,number
from tio.battle_state import BattleActor,BattleField
from tio.combat import Combat
from tio.weapons import WeaponCatalog
from tio.protocol.item_action import ItemAction
from tio.armor import ArmorCatalog


class EquipmentBonusTests(unittest.TestCase):
    setUp=test_equipment.EquipmentTests.setUp

    def setup_gear(self,template,resource,slot):
        p=decode_pet_info(ProficiencyRules().normalize(self.pet,True),human_equipment=True)
        p.fields.update({'0x8c446f':resource,'0x8c4aef':5,'0x8c4a1b':8 if resource==6 else 9,'0x8c4b57':1000})
        raw=encode_pet_info(p)
        item=replace(decode_item_list(self.inventory)[1][0],instance_id=1001,template_id=template,
                     unknown_u8_01=1,location_raw=slot,unknown_bytes_02=bytes(4))
        inv=encode_item_list(1,(item,))
        return raw,inv

    def test_all_effects_only_in_valid_slots_and_species(self):
        for template,resource,slot,stat,value in ((254,1,4,'melee',25),(256,2,4,'melee',25),
               (262,6,1,'sight',1),(263,2,4,'carry',200),(264,2,4,'carry',200),(341,6,16,'armor',85)):
            with self.subTest(template=template):
                raw,inv=self.setup_gear(template,resource,slot)
                self.assertEqual(bonuses(inv,resource)[stat],value)
                item=decode_item_list(inv)[1][0]
                for altered in (replace(item,unknown_u8_01=0,location_raw=0),replace(item,location_raw=128)):
                    self.assertEqual(bonuses(encode_item_list(1,(altered,)),resource)[stat],0)
                self.assertEqual(bonuses(inv,3)[stat],0)

    def test_saved_projection_is_reversible_and_does_not_accumulate(self):
        for template,resource,slot in ((256,1,4),(262,6,1),(264,2,4)):
            raw,inv=self.setup_gear(template,resource,slot)
            with closing(sqlite3.connect(self.path)) as db,db:
                db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account=?',(raw,inv,'alice'))
            reads=[self.pets.list('alice')[0][1] for _ in range(3)]
            self.assertEqual(reads[0],reads[1]);self.assertEqual(reads[1],reads[2])
            f=decode_pet_info(reads[0],human_equipment=True).fields
            before=decode_pet_info(raw,human_equipment=True).fields
            if template==262:self.assertEqual(f['0x8c4a1b'],9)
            if template==256:
                self.assertEqual(number(f[SAVED[0]]),number(before[SAVED[0]])+25)
                self.assertEqual(f[BASE[0]],before[BASE[0]])
            with closing(sqlite3.connect(self.path)) as db:
                stored=decode_pet_info(db.execute('SELECT pet_packet FROM owned_pets WHERE account=?',('alice',)).fetchone()[0],human_equipment=True).fields
                for key in (SAVED[0],BASE[0],'0x8c4a1b','0x8c4b57'):self.assertEqual(stored[key],before[key])

    def test_helmet_changes_real_visibility_and_removal_reverts_it(self):
        from tio.visibility import visible_actors
        raw,inv=self.setup_gear(262,6,1)
        pet=project(raw,True,inv)
        f=BattleField(14,3,[BattleActor(1,10,1,1,20,100,100,sight_radius=9),BattleActor(2,20,10,1,20,100,100)],step_cost=1)
        c=Combat(f,WeaponCatalog());f.combat=c
        c.register(1,inv,human=True,pet_packet=pet)
        self.assertIn(2,visible_actors(f,10))
        c.equip(10,ItemAction(1,1001,255))
        self.assertEqual(f.actor(1).sight_radius,8)
        self.assertNotIn(2,visible_actors(f,10))
        c.equip(10,ItemAction(1,1001,0))
        self.assertEqual(f.actor(1).sight_radius,9)

    def test_exo_capacity_updates_in_battle_and_tank_not_saved_as_training(self):
        for template,resource in ((263,2),(264,2),(254,1),(256,2)):
            raw,inv=self.setup_gear(template,resource,4)
            f=BattleField(3,3,[BattleActor(1,10,1,1,20,100,100)],step_cost=1)
            c=Combat(f,WeaponCatalog());c.register(1,inv,human=True,pet_packet=project(raw,True,inv))
            self.assertEqual(c.proficiency_rules.value(c.proficiencies[1],True,'Melee'),35)
            if template in (263,264):
                self.assertEqual(c.weight_capacity(1),1200)
                c.equip(10,ItemAction(1,1001,255))
                self.assertEqual(c.weight_capacity(1),1000)
                c.equip(10,ItemAction(1,1001,2))
                self.assertEqual(c.weight_capacity(1),1200)

    def test_shield_only_active_hand_adds_defense(self):
        raw,inv=self.setup_gear(341,6,16)
        self.assertEqual(ArmorCatalog().defense(inv,human=True),85)
        item=decode_item_list(inv)[1][0]
        self.assertEqual(ArmorCatalog().defense(encode_item_list(1,(replace(item,location_raw=128),)),human=True),0)
        f=BattleField(3,3,[BattleActor(1,10,1,1,20,100,100)],step_cost=1)
        c=Combat(f,WeaponCatalog());c.register(1,inv,human=True,pet_packet=raw)
        self.assertEqual(c.defense(1),85)
        c.swap_weapons(10,1)
        self.assertEqual(c.defense(1),0)
        c.swap_weapons(10,1)
        self.assertEqual(c.defense(1),85)

    def test_tank_increases_actual_melee_damage_without_training_the_bonus(self):
        from test_weapon_proficiency import setup,profile
        from test_combat import item
        from tio.protocol.battle_attack import AttackRequest
        raw=profile(5)
        for worn,expected in ((True,21),(False,17)):
            f,c=setup(326,packet=raw)
            inv=encode_item_list(1,(item(1,326,1,True),replace(item(2,256),unknown_u8_01=int(worn),location_raw=4 if worn else 0)))
            c.register(1,inv,human=True,pet_packet=project(raw,True,inv))
            f._actors[2]=replace(f.actor(2),x=2)
            c.attack(7,AttackRequest(1,2,1))
            self.assertEqual(1000-f.actor(2).health,expected)
            skill=c.proficiency_rules.value(c.proficiencies[1],True,'Melee')
            self.assertGreater(skill,35)
            self.assertLess(skill,36)
