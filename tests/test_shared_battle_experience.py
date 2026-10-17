"""Real shared PvP result IDs, earned XP and replay after a process crash."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import unittest
import random

import test_shared_team_arena as shared
from server.battle_journal import BattleJournal
from server.team_arena import TeamArena
from tio import level_progression as levels
from tio.owned_pets import OwnedPetStore
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.pet_info import decode_pet_info,encode_pet_info


class SharedBattleExperienceTests(unittest.TestCase):
    def setUp(self):
        self.case=shared.SharedTeamTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.path=self.case.path
        with closing(sqlite3.connect(self.path)) as db,db:
            for account,xp in (('alice',1399),('bob',21)):
                raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(account,)).fetchone()[0]
                pet=decode_pet_info(raw,human_equipment=True)
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',
                    (encode_pet_info(replace(pet,fields={**pet.fields,levels.XP:xp})),account))
        self.case.hub.journal=BattleJournal(self.case.hub,self.path,wall=lambda:1000.)
        for index in (0,1):self.case.send(index,b'\xba\x03\0\1')
        self.owners=tuple(self.case.hub.identities[s] for s in self.case.sessions[:2])
        self.battle=self.case.hub.battles[self.owners[0]]
        self.assertEqual(self.battle['humans'],set(self.owners))
        self.assertFalse(self.battle['bots'])
        field=self.battle['field'];combat=field.combat
        self.actors=tuple(field.actor_ids(owner)[0] for owner in self.owners)
        self.assertEqual(tuple(combat.storage_ids[i] for i in self.actors),(1,1))
        self.assertNotEqual(*self.actors)
        self.assertGreater(min(self.actors),0x40000000)
        with self.case.hub.journal.unit(self.battle):
            field.blocked=frozenset();field.doors.states={}
            for index,identity in enumerate(self.actors):
                field._actors[identity]=replace(field.actor(identity),x=10+index,y=10,
                    health=1 if index else field.actor(identity).health,sight_radius=30)
            for view in self.battle['views'].values():view.refresh()
            combat.rng=random.Random(1)
        for index in (0,1):self.case.send(index,b'\x36')
        self.case.hub.tick()
        if self.battle['arena']._turns[self.battle['room'].room_id][0]!=self.owners[0]:
            self.case.send(1,encode_end_turn(self.actors[1]));self.case.hub.tick()
        for queue in self.case.hub.queues.values():queue.clear()

    def finish_with_actual_attack(self):
        packets=self.case.send(0,encode_attack_request(AttackRequest(self.actors[0],11,10)))
        attack=decode_attack_result(next(p for p in packets if p[:1]==b'\x4b'))
        self.assertEqual(tuple((h.actor_id,h.damage,h.left_hp) for h in attack.hits),((self.actors[1],1,0),))
        self.case.hub.tick()
        self.assertTrue(self.battle['finished'])
        return self.battle['result_packets']

    def check_result(self,packets,identity,gain,xp,level):
        summary=packets[-1]
        self.assertEqual(summary[0],0x4c)
        self.assertEqual(summary[28],1,'Each result must have only its own fighter')
        self.assertEqual(int.from_bytes(summary[29:33],'little'),identity)
        self.assertEqual(int.from_bytes(summary[33:37],'little'),gain)
        updates=[p for p in packets if p[:1]==b'\x3b']
        self.assertEqual(len(updates),1)
        actor=decode_battle_soldier(updates[0],human_equipment=True)
        self.assertEqual((actor.soldier_id,actor.level,actor.fields['0x8c514b']),(identity,level,xp))
        xp_updates=[p for p in packets if p[:1]==b'\x4e']
        self.assertEqual(len(xp_updates),1)
        self.assertEqual(int.from_bytes(xp_updates[0][1:5],'little'),identity)
        self.assertEqual(int.from_bytes(xp_updates[0][9:13],'little'),2)
        self.assertEqual(int.from_bytes(xp_updates[0][13:17],'little'),xp)
        self.assertLess(packets.index(updates[0]),len(packets)-1)
        self.assertLess(packets.index(xp_updates[0]),len(packets)-1)

    def audit(self):
        with closing(sqlite3.connect(self.path)) as db:
            return tuple(db.execute('SELECT account,pet_id,gain,xp_after FROM experience_battle_audit ORDER BY account'))

    def test_actual_two_accounts_receive_their_own_global_actor_gain_and_promotion(self):
        results=self.finish_with_actual_attack()
        self.check_result(results[self.owners[0]],self.actors[0],4,1403,2)
        self.check_result(results[self.owners[1]],self.actors[1],2,23,1)
        self.assertEqual(self.audit(),(('alice',1,4,1403),('bob',1,2,23)))
        for account,xp in (('alice',1403),('bob',23)):
            stored=OwnedPetStore(self.path).list(account)[0][1]
            self.assertEqual(decode_pet_info(stored,human_equipment=True).fields[levels.XP],xp)
        cached={owner:tuple(packets) for owner,packets in results.items()}
        for owner in self.owners:self.case.hub.settle(self.battle,owner,int(owner==self.owners[0]))
        self.assertEqual(results,cached)
        self.assertEqual(self.audit(),(('alice',1,4,1403),('bob',1,2,23)))

    def test_crash_recovery_replays_same_result_once_without_awarding_experience_again(self):
        cached={owner:tuple(packets) for owner,packets in self.finish_with_actual_attack().items()}
        before=self.audit()
        hub=TeamArena(clock=lambda:self.case.now)
        hub.journal=BattleJournal(hub,self.path,wall=lambda:1001.)
        self.assertEqual(hub.journal.recover(),[self.battle['match_id']])
        self.assertEqual(set(hub.completed),set(self.owners))
        for index,session in enumerate(self.case.sessions[:2]):
            owner=self.owners[index]
            self.assertTrue(hub.resume(session));hub.queues[owner].clear()
            self.assertTrue(hub.handle(session,b'\x36'))
            self.assertEqual(tuple(hub.queues[owner]),cached[owner])
            hub.queues[owner].clear();hub.handle(session,b'\x36')
            self.assertFalse(hub.queues[owner])
        self.assertEqual(self.audit(),before)


if __name__=='__main__':unittest.main()
