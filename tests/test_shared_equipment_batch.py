from contextlib import closing
from dataclasses import replace
import sqlite3
import unittest
from unittest.mock import patch

import test_shared_team_arena as fixture
from test_equipment_batch import gear
from server.battle_journal import BattleJournal
from server.team_arena import TeamArena
from tio import battle_checkpoints
from tio.owned_pets import OwnedPetStore
from tio.protocol.equipment_batch import EquipmentBatchRequest, encode_equipment_batch, STAGE, COMMIT, CANCEL
from tio.protocol.item_action import ItemAction, encode_item_action
from tio.protocol.item_list import encode_item_list, decode_item_list
from tio.protocol.battle_turn import encode_end_turn


class SharedEquipmentBatchTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.SharedTeamTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.hub=self.case.hub;self.path=self.case.path
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',
                       (encode_item_list(1,(gear(101,301,16),gear(102,317),gear(103,208),gear(104,9,count=2))),'alice'))
        self.wall=1000.;self.hub.journal=BattleJournal(self.hub,self.path,wall=lambda:self.wall)
        for index in (0,1):self.case.send(index,b'\xba\3\0\1')
        for index in (0,1):self.case.send(index,b'\x36')
        self.hub.tick()
        self.owners=tuple(self.hub.identities[s] for s in self.case.sessions[:2])
        self.battle=self.hub.battles[self.owners[0]];self.field=self.battle['field']
        self.actor=self.field.actor_ids(self.owners[0])[0]
        self.other=self.field.actor_ids(self.owners[1])[0]
        if self.battle['arena']._turns[self.battle['room'].room_id][0]!=self.owners[0]:
            self.case.send(1,encode_end_turn());self.hub.tick()
        self.inventory=self.field.combat.inventories[self.actor]
        self.points=self.field.actor(self.actor).action_points
        for queue in self.hub.queues.values():queue.clear()

    def send(self,operation,*,actor=None,item=102,batch=1,index=0):
        request=EquipmentBatchRequest(operation,batch,ItemAction(self.actor if actor is None else actor,item,4) if operation==STAGE else None)
        return self.case.send(index,encode_equipment_batch(request))

    def restore(self):
        hub=TeamArena(clock=lambda:self.case.now);hub.journal=BattleJournal(hub,self.path,wall=lambda:self.wall)
        hub.journal.recover();return hub

    def test_preview_is_private_commit_and_retry_charge_two_once(self):
        packets=self.send(STAGE)
        self.assertEqual([p[0] for p in packets],[0x30])
        self.assertFalse(self.hub.queues[self.owners[1]])
        self.assertEqual(self.field.combat.inventories[self.actor],self.inventory)
        self.assertEqual(self.field.actor(self.actor).action_points,self.points)
        self.send(COMMIT)
        self.assertEqual(self.field.actor(self.actor).action_points,self.points-2)
        stored=OwnedPetStore(self.path).inventory('alice',1)
        self.assertEqual(next(i.template_id for i in decode_item_list(stored)[1] if i.client_slot==16),317)
        after=stored;self.send(COMMIT)
        self.assertEqual(self.field.actor(self.actor).action_points,self.points-2)
        self.assertEqual(OwnedPetStore(self.path).inventory('alice',1),after)
        restored=self.restore();field=restored.battles[self.owners[0]]['field']
        self.assertEqual(field.actor(self.actor).action_points,self.points-2)
        self.assertEqual(field.combat.inventories[self.actor],self.field.combat.inventories[self.actor])

    def test_invalid_second_selection_cancels_and_checkpoint_does_not_resurrect_it(self):
        self.send(STAGE)
        packets=self.send(STAGE,item=999)
        self.assertEqual(packets[0],self.field.combat.inventory_packet(self.actor))
        self.assertNotIn(self.owners[0],self.field.combat.equipment_batches)
        self.assertNotIn(self.owners[0],self.restore().battles[self.owners[0]]['field'].combat.equipment_batches)
        self.send(COMMIT)
        self.assertEqual(self.field.actor(self.actor).action_points,self.points)

    def test_foreign_actor_and_foreign_turn_do_not_touch_either_account(self):
        self.send(STAGE,actor=self.other)
        self.send(STAGE,index=1)
        self.assertEqual(self.field.actor(self.actor).action_points,self.points)
        self.assertEqual(self.field.combat.inventories[self.actor],self.inventory)
        self.assertFalse(self.field.combat.equipment_batches)

    def test_cancel_turn_end_timeout_and_reconnect_discard_preview(self):
        self.send(STAGE);self.send(CANCEL)
        self.assertFalse(self.field.combat.equipment_batches)
        self.send(STAGE,batch=2);self.case.send(0,encode_end_turn())
        self.assertFalse(self.field.combat.equipment_batches)
        self.hub.tick();self.case.send(1,encode_end_turn());self.hub.tick()
        self.send(STAGE,batch=3);self.hub.send_scene(self.owners[0],reconnect=True)
        self.assertFalse(self.field.combat.equipment_batches)
        self.send(STAGE,batch=4);self.case.now=100;self.hub.tick()
        self.assertFalse(self.field.combat.equipment_batches)
        self.assertEqual(OwnedPetStore(self.path).inventory('alice',1),encode_item_list(1,decode_item_list(self.inventory)[1]))

    def use_medkit(self):
        return self.case.send(0,encode_item_action(ItemAction(self.actor,104,255)))

    def test_item_use_keeps_preview_shown_and_confirmable(self):
        actor=self.field.actor(self.actor)
        self.field._actors[self.actor]=replace(actor,health=actor.max_health-5)
        self.send(STAGE)
        packets=self.use_medkit()
        self.assertIn(self.owners[0],self.field.combat.equipment_batches)
        shown={i.instance_id:i for i in decode_item_list([p for p in packets if p[0]==0x30][-1])[1]}
        self.assertEqual((shown[102].client_slot,shown[104].count),(16,1))
        self.assertEqual(self.field.actor(self.actor).action_points,self.points-1)
        self.send(COMMIT)
        self.assertEqual(self.field.actor(self.actor).action_points,self.points-3)
        stored=decode_item_list(OwnedPetStore(self.path).inventory('alice',1))[1]
        self.assertEqual(next(i.template_id for i in stored if i.client_slot==16),317)

    def test_rejected_item_use_keeps_preview(self):
        self.send(STAGE)
        self.use_medkit()  # full health: the server refuses and changes nothing
        field=self.battle['field']  # a refused action restores the journal copy
        self.assertIn(self.owners[0],field.combat.equipment_batches)
        self.assertEqual(field.actor(self.actor).action_points,self.points)
        self.send(COMMIT)
        self.assertEqual(self.battle['field'].actor(self.actor).action_points,self.points-2)

    def test_checkpoint_failure_rolls_back_db_ap_and_all_replies(self):
        self.send(STAGE)
        before=OwnedPetStore(self.path).inventory('alice',1)
        queues={o:tuple(q) for o,q in self.hub.queues.items()}
        with patch('server.battle_journal.store.save',side_effect=RuntimeError('injected checkpoint failure')):
            with self.assertRaises(RuntimeError):
                self.hub.battle_action(self.owners[0],encode_equipment_batch(EquipmentBatchRequest(COMMIT,1)))
        field=self.battle['field']
        self.assertEqual(field.actor(self.actor).action_points,self.points)
        self.assertEqual(OwnedPetStore(self.path).inventory('alice',1),before)
        self.assertEqual({o:tuple(q) for o,q in self.hub.queues.items()},queues)
        self.assertIn(self.owners[0],field.combat.equipment_batches)


if __name__=='__main__':unittest.main()
