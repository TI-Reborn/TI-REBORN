import test_equipment
from dataclasses import replace
from contextlib import closing
import sqlite3,unittest
from tio.equipment import equip_primary_weapon,EquipmentRejected,armor_rules
from tio.protocol.pet_info import PetInfo,SCHEMAS,decode_pet_info,encode_pet_info
from tio.protocol.item_list import decode_item_list,encode_item_list
from tio.protocol.item_action import ItemAction,encode_item_action
from tools.battle_actor_fixture import actor_packet
from tio.protocol.battle_soldier import decode_battle_soldier


class ArmorTests(unittest.TestCase):
    setUp=test_equipment.EquipmentTests.setUp

    def seed(self,templates,*,human=True,level=1,female=False):
        fields={**decode_pet_info(self.pet,human_equipment=True).fields,'0x8c4aef':level}
        if female:fields['0x8c446f']=2
        if not human:
            fields['0x8c446f']=3
            fields={k:fields.get(k,0) for k,_,_ in SCHEMAS[(False,bool(fields['0x6d0203']),bool(fields['0x8c4565']))]}
        pet=encode_pet_info(PetInfo(human,fields))
        item=decode_item_list(self.inventory)[1][0]
        bag=encode_item_list(1,tuple(replace(item,instance_id=1001+n,template_id=t) for n,t in enumerate(templates)))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET human=?,pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=1',(int(human),pet,bag,'alice'))
        return pet,bag

    def wear(self,instance=1001,option=255):
        return equip_primary_weapon(self.path,'alice',encode_item_action(ItemAction(1,instance,option)))

    def test_heavy_complete_set_persists_and_enters_battle(self):
        pet,_=self.seed((242,243,244,252))
        for i,opt in ((1001,0),(1002,2),(1003,3)):bag=self.wear(i,opt)
        actor=decode_battle_soldier(actor_packet(pet,7,bag),human_equipment=True)
        self.assertEqual({m:actor.equipment_templates[m] for m in (1,4,8)},{1:242,4:243,8:244})
        bag=self.wear(1004)
        items=decode_item_list(bag)[1]
        self.assertEqual([i.equipped for i in items],[1,0,1,1])
        self.assertEqual(self.pets.inventory('alice',1),bag)
        bag=self.wear(1004)
        self.assertEqual(decode_item_list(bag)[1][3].equipped,0)
        actor=decode_battle_soldier(actor_packet(pet,7,bag),human_equipment=True)
        self.assertEqual(actor.equipment_templates[4],0)

    def test_dog_armor_variants_and_battle_model(self):
        for template,level in ((255,2),(265,5),(266,5)):
            pet,_=self.seed((template,),human=False,level=level)
            bag=self.wear(option=2)
            actor=decode_battle_soldier(actor_packet(pet,7,bag,human=False),human_equipment=False)
            self.assertEqual(actor.fields['0x8c546e'],template)
            self.assertEqual(decode_item_list(self.wear())[1][0].equipped,0)

    def test_species_level_wrong_slot_and_internal_mesh_rejected(self):
        for template,human,level,opt in ((266,True,5,2),(243,False,5,2),(266,False,1,2),(255,False,1,2),(243,True,1,3),(65501,True,5,2),(258,True,5,2),(301,False,5,4)):
            _,before=self.seed((template,),human=human,level=level)
            with self.subTest(template=template,human=human,level=level,opt=opt):
                with self.assertRaises(EquipmentRejected):self.wear(option=opt)
                self.assertEqual(self.pets.inventory('alice',1),before)

    def test_armor_catalog_covers_requested_items(self):
        rules=armor_rules()
        self.assertEqual(rules[243],{'slot':4,'dog':False,'level':0})
        self.assertEqual(rules[266],{'slot':4,'dog':True,'level':5})

    def test_screenshot_helmet_option_zero_and_battle_head_slot(self):
        pet,_=self.seed((251,))
        bag=self.wear(option=0)
        self.assertEqual(decode_item_list(bag)[1][0].client_slot,1)
        actor=decode_battle_soldier(actor_packet(pet,7,bag),human_equipment=True)
        self.assertEqual(actor.equipment_templates[1],251)
        self.assertEqual(actor.equipment_templates[2],0)

    def test_female_exo_equips_replaces_and_enters_battle(self):
        from tio.armor import ArmorCatalog
        for template in (263,264):
            pet,_=self.seed((242,243,244,template,301),female=True)
            for instance,option in ((1001,0),(1002,2),(1003,3),(1005,4)):
                self.wear(instance,option)
            bag=self.wear(1004,2)  # Exact screenshot option: chest.
            self.assertEqual([i.equipped for i in decode_item_list(bag)[1]],[1,0,0,1,1])
            self.assertEqual(self.pets.inventory('alice',1),bag)
            actor=decode_battle_soldier(actor_packet(pet,7,bag),human_equipment=True)
            self.assertEqual(actor.equipment_templates[4],template)
            self.assertEqual(actor.equipment_templates[8],0)
            self.assertEqual(ArmorCatalog().defense(encode_item_list(1,(decode_item_list(bag)[1][3],)),human=True),208)
            # Ordinary trousers replace the full suit, preserving helmet/weapon.
            bag=self.wear(1003,3)
            self.assertEqual([i.equipped for i in decode_item_list(bag)[1]],[1,0,1,0,1])
            self.wear(1004)
            bag=self.wear(1004)
            self.assertEqual(decode_item_list(bag)[1][3].equipped,0)

    def test_female_exo_rejects_men_dogs_and_wrong_slot_atomically(self):
        for template in (263,264):
            for human,female,option in ((True,False,2),(False,False,2),(True,True,3)):
                _,before=self.seed((template,),human=human,female=female)
                with self.assertRaises(EquipmentRejected):self.wear(option=option)
                self.assertEqual(self.pets.inventory('alice',1),before)

    def test_tank_suits_level_five_persist_replace_and_enter_battle(self):
        from tio.armor import ArmorCatalog
        for template in (254,256):
            for female in (False,True):
                with self.subTest(template=template,female=female):
                    pet,_=self.seed((242,243,244,template,301),level=5,female=female)
                    for instance,option in ((1001,0),(1002,2),(1003,3),(1005,4)):
                        self.wear(instance,option)
                    bag=self.wear(1004,2)
                    items=decode_item_list(bag)[1]
                    self.assertEqual([i.equipped for i in items],[0,0,0,1,1])
                    self.assertEqual(self.pets.inventory('alice',1),bag)
                    actor=decode_battle_soldier(actor_packet(pet,7,bag),human_equipment=True)
                    self.assertEqual(actor.equipment_templates[4],template)
                    self.assertEqual(actor.equipment_templates[1],0)
                    self.assertEqual(actor.equipment_templates[8],0)
                    self.assertEqual(ArmorCatalog().defense(bag,human=True),220)
                    for replacement,option in ((1001,0),(1002,2),(1003,3)):
                        bag=self.wear(replacement,option)
                        self.assertEqual(decode_item_list(bag)[1][3].equipped,0)
                        bag=self.wear(1004)
                        self.assertEqual([i.equipped for i in decode_item_list(bag)[1]],[0,0,0,1,1])
                    bag=self.wear(1004)
                    self.assertEqual(decode_item_list(bag)[1][3].equipped,0)

    def test_tank_suits_reject_low_level_dogs_and_wrong_slots_atomically(self):
        for template in (254,256):
            for human,level,option in ((True,4,2),(False,5,2),(True,5,0),(True,5,3)):
                with self.subTest(template=template,human=human,level=level,option=option):
                    _,before=self.seed((template,),human=human,level=level)
                    with self.assertRaises(EquipmentRejected):self.wear(option=option)
                    self.assertEqual(self.pets.inventory('alice',1),before)
