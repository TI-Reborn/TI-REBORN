"""Human/dog visibility under bot actions; eliminated accounts spectate."""
import unittest
import json
from pathlib import Path
from dataclasses import replace
import test_shared_team_arena as fixture
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
from tio.owned_pets import OwnedPetStore


class TurnRegressionTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.SharedTeamTests();self.case.setUp();self.addCleanup(self.case.doCleanups)

    def open(self):
        return self.case.open_battle()

    def dog_battle(self):
        from tio.hiring import HireStore
        from tio.city_catalogs import CityCatalogs
        from tio.squad import SquadStore
        from tio.protocol.arena import ArenaCreateRequest,encode_create_request
        c=self.case;root=Path(__file__).resolve().parents[1]
        template=bytes.fromhex(json.loads((root/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        store=HireStore(c.path,CityCatalogs(root/'config/city_catalogs.json'),template)
        for session in c.sessions[:2]:
            pet,_,_=store.hire(session.account,3)
            dog=decode_pet_info(pet,human_equipment=False).fields['0x8c43eb']
            SquadStore(c.path).assign(session.account,dog,2)
        for i in (0,1):
            c.send(i,encode_create_request(ArenaCreateRequest(1,0,4,2,60,2,2,0,0)));c.send(i,b'\x2e')
        owners=[c.hub.identities[s] for s in c.sessions[:2]]
        b=c.hub.battles[owners[0]];f=b['field'];f.blocked=frozenset();f.doors.states={}
        c.send(0,b'\x36');c.send(1,b'\x36')
        return owners,b

    def test_bot_fog_does_not_hide_other_clients_own_soldiers(self):
        owners,b=self.open();f=b['field'];hub=self.case.hub
        hostile=next(o for o in b['bots'] if not f.allied(o,owners[0]))
        friendly=next(o for o in b['bots'] if f.allied(o,owners[0]))
        shooter=f.actor_ids(hostile)[0];victim=f.actor_ids(friendly)[0]
        for j,(identity,a) in enumerate(f._actors.items()):
            f._actors[identity]=replace(a,x=20+j*2,y=20,sight_radius=2)
        f._actors[shooter]=replace(f.actor(shooter),x=6,y=5)
        f._actors[victim]=replace(f.actor(victim),x=5,y=5)
        for v in b['views'].values():v.refresh()
        for q in hub.queues.values():q.clear()
        b['arena']._turns.clear();b['arena'].begin_turn(hostile,(shooter,),40)
        hub.perform_action(b,hostile,encode_attack_request(AttackRequest(shooter,5,5)))
        self.assert_displayed_models(b,owners)

    def test_human_and_dog_survive_both_bot_turns_without_hidden_hp_one(self):
        owners,b=self.dog_battle();f=b['field'];hub=self.case.hub
        for j,(identity,a) in enumerate(f._actors.items()):
            f._actors[identity]=replace(a,x=20+j,y=20,sight_radius=2)
        bots=tuple(b['bots']);shooters=[f.actor_ids(o)[0] for o in bots]
        for i,(owner,identity) in enumerate(zip(bots,shooters)):
            f._actors[identity]=replace(f.actor(identity),x=5+i,y=5)
        for v in b['views'].values():v.refresh()
        for q in hub.queues.values():q.clear()
        for owner,shooter,victim in zip(bots,shooters,reversed(shooters)):
            for q in hub.queues.values():q.clear()
            b['arena']._turns.clear();b['arena'].begin_turn(owner,(shooter,),40)
            target=f.actor(victim)
            hub.perform_action(b,owner,encode_attack_request(AttackRequest(shooter,target.x,target.y)))
            self.assert_displayed_models(b,owners)
        for owner in owners:
            dog=next(i for i in f.actor_ids(owner) if not f.combat.human[i])
            self.assertIn(dog,b['views'][owner].visible)

    def test_dead_primary_with_live_selected_recruit_still_has_valid_turn(self):
        owners,b=self.dog_battle();f=b['field'];arena=b['arena']
        primary=f.actor_ids(owners[0])[0]
        f._actors[primary]=replace(f.actor(primary),health=0,action_points=0)
        arena._turns.clear();arena._last_turn[b['room'].room_id]=b['room'].members[-1]
        self.assertEqual(arena.next_turn_owner(b['room'].room_id),owners[0])
        alive=f.living_actor_ids(owners[0]);self.assertEqual(len(alive),1)
        arena.begin_turn(owners[0],alive,40)
        self.assertNotIn(primary,arena._turns[b['room'].room_id][1])

    def assert_displayed_models(self,b,owners):
        f=b['field']
        for owner in owners:
            for packet in self.case.hub.queues[owner]:
                identity=int.from_bytes(packet[1:5],'little')
                if identity not in f._actors or not f.allied(f.actor(identity).owner_id,owner):continue
                self.assertNotEqual(packet[0],0x43,'Own/allied soldier removed by another viewer\'s fog')
                if packet[0]!=0x3b:continue
                a=decode_battle_soldier(packet,human_equipment=int.from_bytes(packet[9:13],'little') in (1,2,6))
                self.assertEqual(a.position,(f.actor(identity).x,f.actor(identity).y))
                self.assertEqual(a.fields['0x8c57bb'],f.actor(identity).health)

    def test_dead_single_fighter_account_gets_no_turn_and_can_exit(self):
        owners,b=self.open();f=b['field'];hub=self.case.hub;arena=b['arena']
        dead=owners[1];identity=f.actor_ids(dead)[0]
        f._actors[identity]=replace(f.actor(identity),health=0,action_points=0)
        for q in hub.queues.values():q.clear()
        self.case.send(0,encode_end_turn());hub.tick()
        for _ in range(4):
            turn=arena._turns.get(b['room'].room_id)
            if turn and turn[0] in owners:
                self.assertNotEqual(turn[0],dead)
                self.case.send(owners.index(turn[0]),encode_end_turn())
            hub.tick()
        self.assertIn(dead,hub.battles,'Eliminated account should retain its spectator connection')
        self.assertFalse(any(p[0]==0x38 for p in hub.queues[dead]))
        replies=self.case.send(1,encode_end_turn())
        self.assertTrue(any(p[0]==0xf0 for p in replies),'Spectator turn action must be rejected')
        replies=self.case.send(1,b'\x2a\x01')
        self.assertNotIn(dead,hub.battles)
        self.assertIn(owners[0],hub.battles,'Spectator departure must not end the surviving team\'s battle')

    def test_dead_actor_cannot_be_included_in_turn_budget(self):
        owners,b=self.open();f=b['field'];identity=f.actor_ids(owners[0])[0]
        f._actors[identity]=replace(f.actor(identity),health=0,action_points=0)
        with self.assertRaisesRegex(ValueError,'Dead actor'):f.prepare_turn(owners[0],(identity,))
        self.assertEqual(f.actor(identity).action_points,0)
