from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tio.battle_state import BattleActor,BattleField
from tio.combat import Combat
from tio.owned_pets import OwnedPetStore
from tio.weapons import WeaponCatalog
from tio.protocol.item_list import ItemRecord,encode_item_list,decode_item_list
from tio.protocol.item_action import ItemAction
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.equipment_batch import (EquipmentBatchRequest,encode_equipment_batch,
    decode_equipment_batch,STAGE,COMMIT,CANCEL)
from tio.equipment_batch import EquipmentBatchRejected,stage,commit,cancel,policy,rebase
from tools.battle_actor_fixture import actor_packet

ROOT=Path(__file__).resolve().parents[1]


def gear(identity,template,slot=0,count=1,wear=300):
    return ItemRecord(identity,template,b'\0'*2,count,int(bool(slot)),slot,
                      (wear,300,300),b'\0'*4,None,b'\0'*3)


class EquipmentBatchProtocolTests(unittest.TestCase):
    def test_explicit_extension_roundtrip_preserves_native_action(self):
        stage_request=EquipmentBatchRequest(STAGE,9,ItemAction(0x10000001,1001,255))
        packet=encode_equipment_batch(stage_request)
        self.assertEqual(packet,bytes.fromhex('f601000900000001000010e9030000ff'))
        self.assertEqual(decode_equipment_batch(packet),stage_request)
        for operation in (COMMIT,CANCEL):
            request=EquipmentBatchRequest(operation,9)
            self.assertEqual(decode_equipment_batch(encode_equipment_batch(request)),request)

    def test_bad_versions_lengths_and_targets_are_rejected(self):
        packet=encode_equipment_batch(EquipmentBatchRequest(STAGE,9,ItemAction(1,1001,255)))
        invalid=(packet[:2],packet+b'\0',packet[:-1],b'\x33'+packet[1:],
                 bytes((0xf6,2))+packet[2:],packet[:2]+b'\x03'+packet[3:],
                 packet[:3]+b'\0'*4+packet[7:],packet[:-1]+b'\xfe')
        for value in invalid:
            with self.subTest(packet=value.hex()),self.assertRaises(ValueError):decode_equipment_batch(value)
        with self.assertRaises(ValueError):encode_equipment_batch(EquipmentBatchRequest(COMMIT,1,ItemAction(1,1001,255)))


class EquipmentBatchTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'players.db';self.store=OwnedPetStore(self.path)
        trial=json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        prototype=decode_pet_info(bytes.fromhex(trial['packet_hex']),human_equipment=True)
        self.profiles={};self.inventories={};self.templates={}
        actors=[BattleActor(1,10,2,2,15,100,100),BattleActor(2,10,3,2,15,100,100),BattleActor(3,20,8,2,15,100,100)]
        self.field=BattleField(20,20,actors,step_cost=1)
        self.combat=Combat(self.field,WeaponCatalog());self.field.combat=self.combat
        for identity,account,saved in ((1,'alice',1),(2,'alice',2),(3,'bob',1)):
            profile=encode_pet_info(replace(prototype,fields={**prototype.fields,
                '0x8c43eb':saved,'0x8c4aef':1,'0x8c4ab1':100,'0x8c4a07':100}))
            records=(gear(identity*100+1,301,16),gear(identity*100+2,317),
                     gear(identity*100+3,208),gear(identity*100+4,210),gear(identity*100+5,212),
                     gear(identity*100+6,9,count=2))
            stored=encode_item_list(saved,records);inventory=encode_item_list(identity,records)
            self.store.ensure(account,profile,stored,human=True)
            self.combat.register(identity,inventory,human=True,pet_packet=profile)
            self.combat.persistence[identity]=(self.path,account);self.combat.storage_ids[identity]=saved
            self.inventories[identity]=inventory;self.profiles[identity]=profile
            self.templates[identity]=decode_battle_soldier(actor_packet(profile,10 if account=='alice' else 20,
                stored,human=True,actor_id=identity,x=identity+1,y=2),human_equipment=True)
        self.view=SimpleNamespace(templates=dict(self.templates));self.turn=('match-1',1,10)

    def stage(self,identity,item,option=255,*,owner=10,batch=1,turn=None):
        return self.combat.stage_equipment_batch(owner,EquipmentBatchRequest(STAGE,batch,ItemAction(identity,item,option)),
                                                 self.turn if turn is None else turn)

    def commit(self,*,owner=10,batch=1,turn=None):
        return self.combat.commit_equipment_batch(owner,EquipmentBatchRequest(COMMIT,batch),
                                                  self.turn if turn is None else turn,view=self.view)

    def stored(self,account='alice',identity=1):return self.store.inventory(account,identity)

    def state(self):
        return (dict(self.field._actors),dict(self.combat.inventories),dict(self.combat.proficiencies),
                dict(self.view.templates),dict(self.combat.rental_tax_units),dict(self.combat.skill_lists),
                tuple((a,i,p,n) for a in ('alice','bob') for i,p,n in self.store.list(a)))

    def test_weapon_and_all_armor_private_preview_then_exactly_two_ap_once(self):
        before=self.state()
        for item,option in ((102,4),(103,0),(104,2),(105,3)):
            replies=self.stage(1,item,option)
            self.assertEqual([p[0] for p in replies],[0x30]);self.assertEqual(self.state(),before)
        replies=self.commit()
        self.assertEqual([p[0] for p in replies],[0x30,0x4e])
        self.assertEqual(self.field.actor(1).action_points,13)
        final=decode_item_list(self.combat.inventories[1])[1]
        self.assertEqual({i.client_slot:i.template_id for i in final if i.equipped},{16:317,1:208,4:210,8:212})
        self.assertEqual(self.stored(),self.combat.inventories[1])
        self.assertEqual(self.view.templates[1].fields['0x8c52cf'],317)
        self.assertEqual(self.combat.proficiencies,before[2])
        after=self.state();self.commit();self.assertEqual(self.state(),after)

    def test_all_owned_fighters_commit_in_one_db_transaction(self):
        self.stage(1,102,4);self.stage(2,202,4)
        self.commit()
        self.assertEqual([self.field.actor(i).action_points for i in (1,2,3)],[13,13,15])
        self.assertEqual(self.stored(identity=2),self.combat.inventories[2])
        self.assertEqual(self.stored('bob',1),encode_item_list(1,decode_item_list(self.inventories[3])[1]))

    def test_rebase_carries_placement_over_item_use_but_not_over_regearing(self):
        self.field._actors[1]=replace(self.field.actor(1),health=50)
        self.stage(1,102,4)
        self.combat.use_medical(10,ItemAction(1,106,255))
        shown={i.instance_id:i for i in decode_item_list(rebase(self.combat,10)[0])[1]}
        self.assertEqual((shown[102].client_slot,shown[101].equipped,shown[106].count),(16,False,1))
        self.assertEqual(self.combat.equipment_batches[10]['actors'][1]['base'],self.combat.inventories[1])
        self.combat.equip(10,ItemAction(1,103,255))
        self.assertEqual(rebase(self.combat,10),(self.combat.inventory_packet(1),))
        self.assertNotIn(10,self.combat.equipment_batches)

    def test_other_real_account_cannot_stage_owner_equipment(self):
        self.stage(1,102,4);before=self.state()
        with self.assertRaises(EquipmentBatchRejected):self.stage(1,102,4,owner=20,batch=7)
        self.assertIn(10,self.combat.equipment_batches);self.assertEqual(self.state(),before)
        self.stage(3,302,4,owner=20,batch=7);self.commit(owner=20,batch=7)
        self.assertEqual(self.stored('bob',1),encode_item_list(1,decode_item_list(self.combat.inventories[3])[1]))
        self.assertEqual(self.field.actor(1).action_points,15)

    def test_invalid_middle_action_discards_every_preview_without_persistence(self):
        before=self.state();self.stage(1,102,4);self.stage(2,203,0)
        with self.assertRaises(EquipmentBatchRejected) as raised:self.stage(2,999,255)
        self.assertEqual({decode_item_list(p)[0] for p in raised.exception.restores},{1,2})
        self.assertNotIn(10,self.combat.equipment_batches);self.assertEqual(self.state(),before)
        with self.assertRaises(EquipmentBatchRejected):self.commit()

    def test_consumable_wrong_slots_broken_and_missing_profile_are_rejected(self):
        before=self.state()
        for item,option in ((106,255),(102,0),(103,4),(999,255)):
            with self.subTest(item=item),self.assertRaises(EquipmentBatchRejected):self.stage(1,item,option)
            self.assertEqual(self.state(),before)
        _,items,flag=decode_item_list(self.combat.inventories[1])
        self.combat.inventories[1]=encode_item_list(1,tuple(replace(i,unknown_words=(0,300,300)) if i.instance_id==102 else i for i in items),flag)
        with self.assertRaises(EquipmentBatchRejected):self.stage(1,102,4)
        self.combat.inventories[1]=self.inventories[1];self.combat.proficiencies.pop(1)
        with self.assertRaises(EquipmentBatchRejected):self.stage(1,102,4)

    def test_insufficient_ap_and_dead_fighter_invalidate_whole_batch(self):
        for change in ({'action_points':1},{'health':0}):
            with self.subTest(change=change):
                self.stage(1,102,4);self.stage(2,202,4)
                original=self.field.actor(2);self.field._actors[2]=replace(original,**change)
                before=self.state()
                with self.assertRaises(EquipmentBatchRejected):self.commit()
                self.assertEqual(self.state(),before);self.assertNotIn(10,self.combat.equipment_batches)
                self.field._actors[2]=original

    def test_db_failure_on_second_actor_rolls_back_both_accounts_and_all_memory(self):
        before=self.state();self.stage(1,102,4);self.stage(2,202,4)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER fail_second BEFORE UPDATE ON owned_pets WHEN NEW.account='alice' AND NEW.pet_id=2 BEGIN SELECT RAISE(ABORT,'injected equipment failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.commit()
        self.assertEqual(self.state(),before);self.assertNotIn(10,self.combat.equipment_batches)

    def test_external_inventory_change_rejects_cas_and_first_actor_update_rolls_back(self):
        self.stage(1,102,4);self.stage(2,202,4)
        _,items,flag=decode_item_list(self.stored(identity=2))
        outside=encode_item_list(2,tuple(replace(i,unknown_words=(299,300,300)) if i.instance_id==201 else i for i in items),flag)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='alice' AND pet_id=2",(outside,))
        before=(dict(self.field._actors),dict(self.combat.inventories),dict(self.view.templates),self.stored())
        with self.assertRaises(EquipmentBatchRejected):self.commit()
        self.assertEqual((dict(self.field._actors),dict(self.combat.inventories),dict(self.view.templates),self.stored()),before)
        self.assertEqual(self.stored(identity=2),outside)

    def test_restored_slots_still_validate_saved_inventory_before_charging_ap(self):
        self.stage(1,102,4);self.stage(1,101,4)
        _,items,flag=decode_item_list(self.stored())
        outside=encode_item_list(1,tuple(replace(i,unknown_words=(299,300,300)) if i.instance_id==101 else i for i in items),flag)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='alice' AND pet_id=1",(outside,))
        with self.assertRaises(EquipmentBatchRejected):self.commit()
        self.assertEqual(self.field.actor(1).action_points,15)
        self.assertEqual(self.combat.inventories[1],self.inventories[1])
        self.assertEqual(self.stored(),outside)

    def test_saved_profile_change_rolls_back_all_equipment_without_overwriting_skills(self):
        self.stage(1,102,4);self.stage(2,202,4)
        profile=next(p for i,p,_ in self.store.list('alice') if i==2)
        decoded=decode_pet_info(profile,human_equipment=True)
        outside=encode_pet_info(replace(decoded,fields={**decoded.fields,'0x8c4aef':2}))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=2",(outside,))
        before=(dict(self.field._actors),dict(self.combat.inventories),dict(self.combat.proficiencies),dict(self.view.templates),self.stored())
        with self.assertRaises(EquipmentBatchRejected):self.commit()
        self.assertEqual((dict(self.field._actors),dict(self.combat.inventories),dict(self.combat.proficiencies),dict(self.view.templates),self.stored()),before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=2").fetchone()[0],outside)

    def test_view_serialization_failure_precedes_database_and_ap_changes(self):
        self.stage(1,102,4);self.stage(2,202,4)
        self.view.templates[2]=replace(self.view.templates[2],fields={**self.view.templates[2].fields,'0x8c5116':object()})
        before=self.state()
        with self.assertRaises(Exception):self.commit()
        self.assertEqual(self.state(),before)

    def test_cancel_and_turn_or_batch_mismatch_return_authoritative_inventory(self):
        before=self.state();self.stage(1,102,4)
        self.assertEqual(cancel(self.combat,10,batch_id=7),())
        self.assertIn(10,self.combat.equipment_batches)
        replies=self.combat.cancel_equipment_batch(10,batch_id=1)
        self.assertEqual(replies,(self.combat.inventory_packet(1),));self.assertEqual(self.state(),before)
        for kwargs in ({'turn':('match-1',2,10)},{'batch':2}):
            self.stage(1,102,4)
            with self.assertRaises(EquipmentBatchRejected):self.commit(**kwargs)
            self.assertEqual(self.state(),before)

    def test_changed_then_restored_gear_still_costs_two_once_noop_costs_zero(self):
        self.stage(1,102,4);self.stage(1,101,4);self.commit()
        self.assertEqual(self.combat.inventories[1],self.inventories[1])
        self.assertEqual(self.field.actor(1).action_points,13)
        self.stage(1,101,4,batch=2);self.commit(batch=2)
        self.assertEqual(self.field.actor(1).action_points,13)

    def test_stage_and_receipts_checkpoint_safe_and_reconnect_cancel(self):
        from tio.battle_snapshot import dumps,loads
        self.stage(1,102,4)
        restored,_=loads(dumps(self.field,clock=lambda:10,wall=lambda:100),clock=lambda:20,wall=lambda:101)
        self.assertEqual(restored.combat.equipment_batches,self.combat.equipment_batches)
        restores=cancel(restored.combat,10,forget_receipts=True)
        self.assertEqual(decode_item_list(restores[0])[1],decode_item_list(self.inventories[1])[1])
        self.commit();restored,_=loads(dumps(self.field))
        self.assertEqual(restored.combat.equipment_batch_receipts,self.combat.equipment_batch_receipts)

    def test_explicit_resource_policy_bounds_staging(self):
        policy_value={**policy(),'maximum_staged_actions':1}
        with patch('tio.equipment_batch.policy',return_value=policy_value):
            self.stage(1,102,4)
            with self.assertRaises(EquipmentBatchRejected):self.stage(1,103,0)
        self.assertEqual(self.combat.inventories,self.inventories)


if __name__=='__main__':unittest.main()
