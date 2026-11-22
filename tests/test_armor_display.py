from contextlib import closing
from dataclasses import replace
import sqlite3
import struct
import unittest

import test_armor_equipment
import test_miner_abilities
from test_combat import item
from tio.armor_display import city_armor, project_city_pet, encode_armor, total
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.protocol.abilities import AbilityEntry
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.battle_state import BattleActor, BattleField
from tio.combat import Combat
from tio.weapons import WeaponCatalog
from tio.visibility import VisibilityView
from tools.battle_actor_fixture import actor_packet


def battle(pet, bag, human=True):
    f=BattleField(10,10,(BattleActor(1,7,3,3,15,100,100),),step_cost=1)
    c=Combat(f,WeaponCatalog());f.combat=c
    c.register(1,bag,human=human,pet_packet=pet)
    template=decode_battle_soldier(actor_packet(pet,7,bag,human=human),human_equipment=human)
    view=VisibilityView(f,7,{1:template})
    return c,view


class ArmorDisplayTests(unittest.TestCase):
    setUp=test_armor_equipment.ArmorTests.setUp
    seed=test_armor_equipment.ArmorTests.seed
    wear=test_armor_equipment.ArmorTests.wear

    def test_city_and_battle_sum_worn_only_and_refresh_without_accumulation(self):
        pet,_=self.seed((251,252,253,242),level=4)
        base=decode_pet_info(pet,human_equipment=True).fields['0x8c4ac5']
        for i,opt in ((1001,0),(1002,2),(1003,3)):bag=self.wear(i,opt)
        expected=base+63+85+48
        self.assertEqual(city_armor(self.path,'alice',1),expected)
        original=pet
        for _ in range(3):
            pet=project_city_pet(self.path,'alice',pet)
            self.assertEqual(decode_pet_info(pet,human_equipment=True).fields['0x8c4ac5'],expected)
        c,view=battle(original,bag)
        self.assertEqual(decode_battle_soldier(view.snapshot(1),human_equipment=True).fields['0x8c5731'],expected)
        from tio.protocol.item_action import ItemAction
        c.equip(7,ItemAction(1,1002,255),view=view)
        self.assertEqual(c.displayed_armor(1),expected-85)
        self.assertEqual(decode_battle_soldier(view.snapshot(1),human_equipment=True).fields['0x8c5731'],expected-85)
        self.wear(1002)
        self.assertEqual(city_armor(self.path,'alice',1),expected-85)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT pet_packet FROM owned_pets').fetchone()[0],original)

    def test_rental_upgrade_is_scaled_once_and_backpack_ignored(self):
        gear=replace(item(1,252,equipped=True),location_raw=4,
                     unknown_bytes_02=bytes((20,0,0,0)),unknown_bytes_03=bytes((20,0,0)))
        bag=encode_item_list(1,(gear,replace(gear,instance_id=2,unknown_u8_01=0,location_raw=0)))
        # Original armor enchant table: +3 adds 3, +20 adds 100.
        self.assertEqual(total(15,bag,True,3),103)
        from tio.armor import ArmorCatalog
        self.assertEqual(total(15,bag,True,20),15+ArmorCatalog().defense(bag,human=True))
        self.assertEqual(struct.unpack('<BIIIIB',encode_armor(1,98)),(0x4e,1,1,9,98,0))

    def test_dog_equipment_sum_and_repeated_snapshot(self):
        pet,_=self.seed((266,),human=False,level=5)
        bag=self.wear(option=2)
        c,view=battle(pet,bag,False)
        expected=decode_pet_info(pet,human_equipment=False).fields['0x8c4ac5']+160
        self.assertEqual(city_armor(self.path,'alice',1),expected)
        for _ in range(3):
            self.assertEqual(decode_battle_soldier(view.snapshot(1),human_equipment=False).fields['0x8c5731'],expected)


class MinerArmorDisplayTests(unittest.TestCase):
    setUp=test_miner_abilities.MinerAbilityTests.setUp
    travel=test_miner_abilities.MinerAbilityTests.travel
    miner=test_miner_abilities.MinerAbilityTests.miner

    def test_naked_defense_returns_after_removing_armor(self):
        self.miner(5)
        learned=(AbilityEntry(24,2,0,0),)
        self.service.state.replace('alice',1,learned,expected_revision=0)
        self.assertEqual(city_armor(self.path,'alice',1),67)
        from tio.equipment import armor_rules
        from tio.armor import ArmorCatalog
        rules=armor_rules();identity=next(i for i,r in rules.items() if r.get('miner') and r['slot']==4)
        gear=replace(item(1,identity,equipped=True),location_raw=4)
        bag=encode_item_list(1,(gear,))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=?',(bag,))
        from tio.owned_pets import OwnedPetStore
        pet=OwnedPetStore(self.path).list('alice')[0][1]
        worn=ArmorCatalog().defense(bag,human=True)
        self.assertEqual(city_armor(self.path,'alice',1),worn)
        c,view=battle(pet,bag)
        c.configure_armor_display(1,learned,self.service.catalog)
        self.assertEqual(c.displayed_armor(1),worn)
        from tio.protocol.item_action import ItemAction
        c.equip(7,ItemAction(1,1,255),view=view)
        self.assertEqual(c.displayed_armor(1),67)
        c.equip(7,ItemAction(1,1,255),view=view)
        self.assertEqual(c.displayed_armor(1),worn)
