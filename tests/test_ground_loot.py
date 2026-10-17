"""Shared ground transfers, combat death and fog regression coverage."""
from test_battle_loot import BattleLootTests
from test_combat import item
from dataclasses import replace
import unittest
from unittest.mock import patch
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.battle_loot import LootTransfer
from tio.protocol.battle_position import BattlePositionRequest
from tio.protocol.battle_attack import AttackRequest


class GroundLootTests(unittest.TestCase):
    setUp=BattleLootTests.setUp
    saved=BattleLootTests.saved
    supply=BattleLootTests.supply
    take=BattleLootTests.take
    def drop(self,identity=101,count=4):
        return self.loot.transfer(7,LootTransfer(1,1,1,((identity,count),)),1)

    def test_ground_cross_owner_pickup_and_remove(self):
        bob=encode_item_list(1,(item(101,301),))
        self.pets.ensure('bob',self.pet,bob,human=True)
        self.combat.register(2,encode_item_list(2,decode_item_list(bob)[1]),human=True,path=self.path,account='bob')
        self.combat.storage_ids[2]=1
        self.drop()
        entry,=self.loot.boxes[1,1]
        self.assertNotEqual(entry.instance_id,101)
        self.assertEqual(self.field.actor(1).action_points,13)
        self.assertEqual(next(i.count for i in decode_item_list(self.saved())[1] if i.instance_id==101),6)
        with self.assertRaises(ValueError):self.loot.open(8,BattlePositionRequest(2,1,1),1)
        self.field._actors[2]=replace(self.field.actor(2),x=1,y=1)
        self.loot.open(8,BattlePositionRequest(2,1,1),1)
        self.loot.transfer(8,LootTransfer(2,1,1,(),((entry.instance_id,4),)),1)
        self.assertEqual(decode_item_list(self.combat.inventories[2])[1],(item(101,301),entry))
        self.assertEqual(decode_item_list(self.pets.inventory('bob',1))[1],(item(101,301),entry))
        self.assertEqual(self.loot.boxes[1,1],())
        with self.assertRaises(ValueError):self.loot.open(8,BattlePositionRequest(2,1,1),1)

    def test_ground_rejections_and_cancel_do_not_mutate(self):
        snapshot=(self.combat.inventories.copy(),self.loot.boxes.copy(),self.field.actor(1),self.loot.next_id)
        for request in (LootTransfer(1,1,2,((101,4),)),LootTransfer(1,1,1,((101,11),)),LootTransfer(1,1,1,(),((101,1),))):
            with self.assertRaises(ValueError):self.loot.transfer(7,request,1)
        with patch.object(self.combat,'_persist_inventory',side_effect=ValueError('CAS')):
            with self.assertRaises(ValueError):self.drop()
        self.loot.transfer(7,LootTransfer(1,1,1),1)
        self.assertEqual((self.combat.inventories,self.loot.boxes,self.field.actor(1),self.loot.next_id),snapshot)

    def test_ground_visibility_does_not_disclose_hidden_changes(self):
        self.field._actors[2]=replace(self.field.actor(2),x=7,y=7,sight_radius=1)
        self.drop();seen={};other={}
        self.assertEqual(self.loot.visible_updates(7,seen),(bytes((0x44,1,1,0,0)),))
        self.assertEqual(self.loot.visible_updates(8,other),())
        self.assertEqual(self.loot.visible_updates(7,seen),())
        self.field._actors[1]=replace(self.field.actor(1),x=7,y=7,sight_radius=1)
        self.loot.boxes[1,1]=()
        self.assertEqual(self.loot.visible_updates(7,seen),())
        self.field._actors[1]=replace(self.field.actor(1),x=1,y=1)
        self.assertEqual(self.loot.visible_updates(7,seen),(bytes((0x45,1,1)),))

    def death_setup(self,count=137):
        weapon,=self.supply((301,1))
        self.take((weapon,));self.combat.equip(7,__import__('tio.protocol.item_action',fromlist=['ItemAction']).ItemAction(1,weapon.instance_id,255))
        victim=encode_item_list(2,(item(222,3,5),item(0x60009000,52,count),item(0x60009001,301,equipped=True)))
        self.combat.register(2,victim,human=True)
        self.combat.temporary_items.update((0x60009000,0x60009001))
        self.field._actors[2]=replace(self.field.actor(2),health=1)
        return victim

    def test_death_drops_temporary_equipment_and_loaded_drill_once(self):
        self.death_setup()
        self.combat.attack(7,AttackRequest(1,3,1))
        self.assertEqual(self.field.actor(2).health,0)
        dropped=self.loot.boxes[3,1]
        self.assertEqual({i.template_id for i in dropped},{301,52})
        self.assertTrue(all(not i.equipped and not i.slot for i in dropped))
        self.assertEqual(next(i.count for i in dropped if i.template_id==52),137)
        self.assertEqual([i.instance_id for i in decode_item_list(self.combat.inventories[2])[1]],[222])
        self.assertEqual(self.loot.stage_deaths({2:self.field.actor(2)},{}),({},set()))
        self.field._actors[1]=replace(self.field.actor(1),x=3,y=1,action_points=15)
        self.loot.open(7,BattlePositionRequest(1,3,1),1)
        self.loot.transfer(7,LootTransfer(1,3,1,(),tuple((i.instance_id,i.count) for i in dropped)),1)
        self.assertEqual(next(i.count for i in decode_item_list(self.combat.inventories[1])[1] if i.template_id==52),137)
        self.assertFalse(any(i.template_id==52 for i in decode_item_list(self.saved())[1]))

    def test_failed_combat_commit_does_not_publish_death_bag(self):
        victim=self.death_setup();before=self.field._actors.copy()
        with patch.object(self.combat,'_persist_batch',side_effect=ValueError('CAS')):
            with self.assertRaises(ValueError):self.combat.attack(7,AttackRequest(1,3,1))
        self.assertEqual(self.field._actors,before)
        self.assertEqual(self.combat.inventories[2],victim)
        self.assertNotIn((3,1),self.loot.boxes)

    def test_loaded_and_empty_drills_move_whole_and_preserve_payload(self):
        for count in (0,137):
            self.combat.inventories[1]=encode_item_list(1,(*decode_item_list(self.combat.inventories[1])[1],item(0x60008000+count,52,count)))
            self.combat.temporary_items.add(0x60008000+count)
            if count:
                with self.assertRaises(ValueError):self.drop(0x60008000+count,count-1)
            self.drop(0x60008000+count,count)
        self.assertEqual(sorted(i.count for i in self.loot.boxes[1,1]),[0,137])
        self.assertEqual(self.saved(),self.initial)


del BattleLootTests
