"""Four-account authoritative actions, TTL, private recon and rollback."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import unittest
from unittest.mock import patch

import test_shared_survival_groups as fixture
from test_equipment_batch import gear
from server.battle_journal import BattleJournal
from tio import battle_item_effects as effects
from tio.owned_pets import OwnedPetStore
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.protocol.battle_item_visuals import decode_item_visuals
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.item_action import ItemAction,encode_item_action
from tio.protocol.item_list import encode_item_list,decode_item_list

class SharedBattleItemTests(unittest.TestCase):
    def prepare(self,template=318):
        self.case=fixture.SharedSurvivalGroupsTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.hub,self.path=self.case.hub,self.case.path
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',
                (encode_item_list(1,(gear(101,template,16 if template in (318,320,5001) else 0),)),'alice'))
        self.wall=1000.;self.hub.journal=BattleJournal(self.hub,self.path,wall=lambda:self.wall)
        self.owners=self.case.join(4)
        for index in range(4):self.case.send(index,b'\x36')
        self.hub.tick();self.battle=self.hub.battles[self.owners[0]]
        self.field=self.battle['field'];self.actor=self.field.actor_ids(self.owners[0])[0]
        # Controlled isolated geometry; production maps remain authoritative.
        self.field.blocked=set();self.field.transparent_obstacles=set()
        for index,owner in enumerate(self.owners):
            identity=self.field.actor_ids(owner)[0]
            self.field._actors[identity]=replace(self.field.actor(identity),x=2+index*6+(10 if index==3 else 0),y=3,sight_radius=9)
        effects.initialize(self.field.combat)
        for index in range(4):
            if self.turn()==self.owners[0]:break
            self.case.send(self.owners.index(self.turn()),encode_end_turn());self.hub.tick()
        for queue in self.hub.queues.values():queue.clear()

    def turn(self):return self.battle['arena']._turns[self.battle['room'].room_id][0]

    def test_smoke_consumption_and_owner_turn_ttl_are_shared(self):
        self.prepare();combat=self.field.combat;before=self.field.actor(self.actor).action_points
        with patch.object(effects,'_scatter',return_value=(8,3)):
            packets=self.case.send(0,encode_attack_request(AttackRequest(self.actor,8,3)))
        self.assertTrue(combat.item_effects['areas'])
        self.assertFalse(decode_item_list(OwnedPetStore(self.path).inventory('alice',1))[1])
        self.assertEqual(self.field.actor(self.actor).action_points,before-7)
        own=next(p for p in packets if p[0]==0xf7);self.assertTrue(decode_item_visuals(own))
        far=self.owners[3]
        far_packets=tuple(self.hub.queues[far]);self.assertEqual(decode_item_visuals(next(p for p in far_packets if p[0]==0xf7)),())
        self.assertNotIn(self.field.actor_ids(self.owners[1])[0],self.battle['views'][self.owners[0]].visible)
        # Four completed opponent turns never decrement this owner's area twice.
        for _ in range(12):self.case.send(self.owners.index(self.turn()),encode_end_turn());self.hub.tick()
        self.assertFalse(combat.item_effects['areas'])
        self.hub.send_scene(self.owners[0],reconnect=True)
        self.assertEqual(decode_item_visuals([p for p in self.hub.queues[self.owners[0]] if p[0]==0xf7][-1]),())

    def test_binocular_native33_then49_private_recon_and_expiry(self):
        self.prepare(24);combat=self.field.combat;before=self.field.actor(self.actor).action_points
        self.case.send(0,encode_item_action(ItemAction(self.actor,101,255)))
        self.assertEqual(self.field.actor(self.actor).action_points,before)
        self.case.send(0,encode_attack_request(AttackRequest(self.actor,14,3)))
        self.assertEqual(self.field.actor(self.actor).action_points,before-5)
        self.assertTrue(combat.item_effects['recon'])
        self.assertIn(self.field.actor_ids(self.owners[2])[0],self.battle['views'][self.owners[0]].visible)
        self.assertFalse(any(kind==3 for packet in self.hub.queues[self.owners[1]] if packet[0]==0xf7
            for _,_,kind in decode_item_visuals(packet)))
        self.case.send(0,encode_end_turn());self.hub.tick()
        self.assertFalse(combat.item_effects['recon'])

    def test_checkpoint_failure_reverts_effect_inventory_ap_rng_and_recipient_queues(self):
        self.prepare(320);combat=self.field.combat
        before=(dict(self.field._actors),dict(combat.inventories),combat.rng.getstate(),
            OwnedPetStore(self.path).inventory('alice',1),{o:tuple(q) for o,q in self.hub.queues.items()})
        with patch('server.battle_journal.store.save',side_effect=RuntimeError('checkpoint fault')):
            with self.assertRaises(RuntimeError):self.hub.battle_action(self.owners[0],encode_attack_request(AttackRequest(self.actor,8,3)))
        self.field=self.battle['field'];combat=self.field.combat
        self.assertEqual((self.field._actors,combat.inventories,combat.rng.getstate(),
            OwnedPetStore(self.path).inventory('alice',1),{o:tuple(q) for o,q in self.hub.queues.items()}),before)
        self.assertFalse(combat.item_effects['flash'])

if __name__=='__main__':unittest.main()
