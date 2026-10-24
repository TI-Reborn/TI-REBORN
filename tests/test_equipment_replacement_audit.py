"""Battle replacement must only remove gear whose occupied body slots overlap."""
import unittest,sqlite3
from contextlib import closing
from dataclasses import replace
import test_equipment_batch as fixture
from test_equipment_batch import gear
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.pet_info import decode_pet_info,encode_pet_info

class EquipmentReplacementAuditTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.EquipmentBatchTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        c=self.case
        pet=decode_pet_info(c.combat.proficiencies[1],human_equipment=True)
        profile=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':20}))
        profile=c.combat.proficiency_rules.normalize(profile,True)
        items=(gear(101,301,16),gear(102,317,128),gear(103,208,1),gear(104,210,4),gear(105,212,8),
               gear(110,301),gear(111,208),gear(112,210),gear(113,212),gear(114,254))
        inventory=encode_item_list(1,items)
        c.combat.inventories[1]=inventory;c.combat.proficiencies[1]=profile
        with closing(sqlite3.connect(c.path)) as db,db:
            db.execute("UPDATE owned_pets SET inventory_packet=?,pet_packet=? WHERE account='alice' AND pet_id=1",(inventory,profile))
        self.initial=items

    def equipped(self):
        return {i.instance_id:i.client_slot for i in decode_item_list(self.case.combat.inventories[1])[1] if i.equipped}

    def test_weapon_helmet_chest_legs_replacements_preserve_all_other_gear_and_metadata(self):
        for new,old,slot,option in ((110,101,16,4),(111,103,1,0),(112,104,4,2),(113,105,8,3)):
            with self.subTest(item=new):
                c=self.case;before=self.equipped();c.stage(1,new,option);c.commit()
                expected={**before,new:slot};expected.pop(old)
                self.assertEqual(self.equipped(),expected)
                self.assertEqual(c.stored(),c.combat.inventories[1])
                for item in decode_item_list(c.combat.inventories[1])[1]:
                    original=next(i for i in self.initial if i.instance_id==item.instance_id)
                    self.assertEqual(replace(item,unknown_u8_01=original.equipped,location_raw=original.location_raw),original)
                c.field._actors[1]=replace(c.field.actor(1),action_points=15)
                c.combat.equipment_batch_receipts.clear()

    def test_explicit_rewear_does_not_toggle_equipped_weapon_or_armor_off(self):
        c=self.case;before=self.equipped()
        for item,option in ((101,4),(102,7),(103,0),(104,2),(105,3)):
            c.stage(1,item,option)
        c.commit();self.assertEqual(self.equipped(),before)

    def test_tank_covers_only_head_chest_legs_and_preserves_both_weapons(self):
        c=self.case;c.stage(1,114,2);c.commit()
        self.assertEqual(self.equipped(),{101:16,102:128,114:4})
        c.combat.equipment_batch_receipts.clear();c.field._actors[1]=replace(c.field.actor(1),action_points=15)
        c.stage(1,103,0);c.commit()
        self.assertEqual(self.equipped(),{101:16,102:128,103:1})

    def test_invalid_placement_restores_entire_outfit_without_applying_preview(self):
        from tio.equipment_batch import EquipmentBatchRejected
        c=self.case;before=self.equipped();points=c.field.actor(1).action_points
        c.stage(1,111,0)
        with self.assertRaises(EquipmentBatchRejected):c.stage(1,112,3)
        self.assertEqual(self.equipped(),before);self.assertEqual(c.field.actor(1).action_points,points)
        self.assertEqual(c.stored(),c.combat.inventories[1])
