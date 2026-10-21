"""Two SQLite accounts, native shared actions and durable hazard recovery.

Synthetic clear corridor isolates movement/fog mechanics; this is server QA,
not a claim that the unmodified Windows client has been exercised.
"""
from contextlib import closing
from dataclasses import replace
import random
import sqlite3
import unittest
from unittest.mock import patch

import test_shared_team_arena as fixture
from test_combat import item
from server.team_arena import TeamArena
from server.battle_journal import BattleJournal
from tio import battle_checkpoints as checkpoints
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.battle_mines import MineDeploy,encode_mine_deploy,decode_mine_deployed
from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.known_mines import decode_known_mines


class SharedSpecialItemsTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.SharedTeamTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.wall=1000

    def prepare(self,weapon=321):
        c=self.case
        with closing(sqlite3.connect(c.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',
                (encode_item_list(1,(item(100,weapon,equipped=weapon not in (321,325)),)),'alice'))
        c.hub.journal=BattleJournal(c.hub,c.path,wall=lambda:self.wall)
        for index in (0,1):c.send(index,b'\xba\3\0\1');c.send(index,b'\x2e')
        self.owners=tuple(c.hub.identities[s] for s in c.sessions[:2])
        self.battle=c.hub.battles[self.owners[0]];field=self.battle['field']
        self.assertIs(self.battle,c.hub.battles[self.owners[1]])
        self.assertFalse(self.battle['bots']);self.assertEqual(len(field._actors),2)
        self.ids=tuple(field.actor_ids(o)[0] for o in self.owners)
        self.assertEqual(set(field.combat.storage_ids.values()),{1})
        with c.hub.journal.unit(self.battle):
            field.blocked=frozenset();field.doors.states={};field.combat.rng=random.Random(31)
            for identity,x in zip(self.ids,(5,8)):
                field._actors[identity]=replace(field.actor(identity),x=x,y=5,sight_radius=30,health=200,max_health=200)
            for view in self.battle['views'].values():view.refresh()
        for index in (0,1):c.send(index,b'\x36')
        c.hub.tick()
        if self.battle['arena']._turns[1][0]!=self.owners[0]:
            c.send(1,encode_end_turn());c.hub.tick()
        self.assertEqual(self.battle['arena']._turns[1][0],self.owners[0]);self.clear()

    def clear(self):
        for q in self.case.hub.queues.values():q.clear()

    def plant(self):
        return self.case.send(0,encode_mine_deploy(MineDeploy(self.ids[0],100,6,5)))

    def restore(self):
        c=self.case;hub=TeamArena(clock=lambda:c.now)
        hub.journal=BattleJournal(hub,c.path,wall=lambda:self.wall);hub.journal.recover()
        for s in c.sessions[:2]:self.assertTrue(hub.resume(s))
        c.hub=hub;self.battle=hub.battles[self.owners[0]]
        self.assertIs(self.battle,hub.battles[self.owners[1]])
        return hub

    def test_native_deploy_hidden_marker_and_reconnect_preserve_supplies(self):
        self.prepare();packets=self.plant()
        ack=decode_mine_deployed(next(p for p in packets if p[:2]==b'\xc8\x3f'))
        self.assertEqual((ack.actor_id,ack.x,ack.y,ack.template_id,ack.state),(*self.ids[:1],6,5,321,1))
        self.assertEqual(len(decode_known_mines(next(p for p in packets if p[:2]==b'\xc8\x3e'))),1)
        other=tuple(self.case.hub.queues[self.owners[1]])
        self.assertFalse(any(p[:2]==b'\xc8\x3f' or p[0]==0x30 for p in other))
        self.assertEqual(decode_known_mines(next(p for p in other if p[:2]==b'\xc8\x3e')),())
        self.assertFalse(decode_item_list(OwnedPetStore(self.case.path).inventory('alice',1))[1])
        self.assertFalse(decode_item_list(OwnedPetStore(self.case.path).inventory('bob',1))[1])
        ap=self.battle['field'].actor(self.ids[0]).action_points
        self.restore()
        for index,count in ((0,1),(1,0)):
            packets=self.case.send(index,b'\x36')
            self.assertEqual(len(decode_known_mines(next(p for p in packets if p[:2]==b'\xc8\x3e'))),count)
        self.assertEqual(self.battle['field'].actor(self.ids[0]).action_points,ap)
        self.assertEqual(len(self.battle['field'].combat.mines),1)

    def test_movement_projects_explosion_to_both_and_credits_real_source_once(self):
        self.prepare();self.plant();self.case.send(0,encode_end_turn());self.case.hub.tick();self.clear()
        packets=self.case.send(1,encode_move_request(BattleMove(self.ids[1],((7,5),(6,5),(6,6)))))
        other=tuple(self.case.hub.queues[self.owners[0]])
        self.assertEqual(decode_battle_move(next(p for p in packets if p[0]==0x3d)).path,((7,5),(6,5)))
        for replies in (packets,other):
            explosion=decode_attack_result(next(p for p in replies if p[0]==0x4b))
            self.assertEqual((explosion.actor_id,explosion.weapon_id,explosion.mine_state),(self.ids[0],321,1))
            self.assertEqual({h.actor_id for h in explosion.hits},set(self.ids))
            self.assertTrue(all(h.damage>0 for h in explosion.hits))
            self.assertEqual(decode_known_mines(next(p for p in replies if p[:2]==b'\xc8\x3e')),())
        self.assertEqual(self.battle['reward_damage'],{self.owners[0]})
        state=self.battle['field'].actor(self.ids[1]);self.assertEqual((state.x,state.y),(6,5))
        self.assertFalse(self.battle['field'].combat.mines)
        hp=tuple(self.battle['field'].actor(i).health for i in self.ids)
        self.restore()
        for index in (0,1):self.case.send(index,b'\x36')
        self.assertEqual(tuple(self.battle['field'].actor(i).health for i in self.ids),hp)
        self.assertEqual(self.battle['field'].combat.after_move(self.ids[1]),())

    def test_burn_turn_is_broadcast_and_reconnect_does_not_repeat_damage(self):
        self.prepare(324)
        packets=self.case.send(0,encode_attack_request(AttackRequest(self.ids[0],8,5)))
        attack=decode_attack_result(next(p for p in packets if p[0]==0x4b))
        self.assertGreater(attack.hits[0].damage,0)
        combat=self.battle['field'].combat;self.assertIn(self.ids[1],combat.burns)
        self.assertEqual(decode_item_list(OwnedPetStore(self.case.path).inventory('alice',1))[1][0].unknown_words[0],291)
        hp=self.battle['field'].actor(self.ids[1]).health
        self.case.send(0,encode_end_turn());self.clear();self.case.hub.tick()
        self.assertEqual(self.battle['field'].actor(self.ids[1]).health,hp-10)
        for owner in self.owners:
            from tio.protocol.health import encode_health
            replies=tuple(self.case.hub.queues[owner])
            self.assertEqual(replies.count(encode_health(self.ids[1],hp-10)),1)
            self.assertFalse(any(p[0]==0x4b for p in replies))
        self.assertEqual(combat.burns[self.ids[1]].remaining,1)
        self.restore()
        for index in (0,1):self.case.send(index,b'\x36')
        self.assertEqual(self.battle['field'].actor(self.ids[1]).health,hp-10)
        self.assertEqual(self.battle['field'].combat.burns[self.ids[1]].remaining,1)

    def test_snapshot_failure_rolls_back_deployment_inventory_ap_and_queues(self):
        self.prepare();before=self.rows();queues={o:tuple(q) for o,q in self.case.hub.queues.items()}
        ap=self.battle['field'].actor(self.ids[0]).action_points;real=checkpoints.save
        def fail(*args,**kwargs):real(*args,**kwargs);raise RuntimeError('Injected after checkpoint')
        with patch('server.battle_journal.store.save',side_effect=fail),self.assertRaises(RuntimeError):
            self.case.hub.battle_action(self.owners[0],encode_mine_deploy(MineDeploy(self.ids[0],100,6,5)))
        self.assertEqual(self.rows(),before)
        battle=self.case.hub.battles[self.owners[0]]
        self.assertEqual(battle['field'].actor(self.ids[0]).action_points,ap)
        self.assertFalse(battle['field'].combat.mines)
        self.assertEqual({o:tuple(q) for o,q in self.case.hub.queues.items()},queues)

    def test_rejected_deployment_returns_native_failure_and_keeps_account_assets(self):
        self.prepare();before=self.rows();ap=self.battle['field'].actor(self.ids[0]).action_points
        packets=self.case.send(0,encode_mine_deploy(MineDeploy(self.ids[0],100,20,20)))
        ack=decode_mine_deployed(next(p for p in packets if p[:2]==b'\xc8\x3f'))
        self.assertEqual((ack.template_id,ack.state),(321,4))
        self.assertFalse(self.battle['field'].combat.mines)
        self.assertEqual(self.battle['field'].actor(self.ids[0]).action_points,ap)
        # The request journal may advance its checkpoint revision on rejection;
        # the invariant here is that durable account assets do not change.
        after=self.rows()
        self.assertEqual({k:v for k,v in after.items() if k!='battle_checkpoints'},
                         {k:v for k,v in before.items() if k!='battle_checkpoints'})

    def test_mine_armor_break_refreshes_equipment_for_both_with_private_bag(self):
        from test_durability import gear
        from tio.durability import refresh_template
        from tio.protocol.battle_soldier import decode_battle_soldier
        self.prepare();field=self.battle['field'];combat=field.combat
        armor=gear(200,210,(1,300,300),4);identity=self.ids[1]
        with self.case.hub.journal.unit(self.battle):
            combat._persist_batch({identity:encode_item_list(identity,(armor,))})
            combat.inventories[identity]=encode_item_list(identity,(armor,))
            for view in self.battle['views'].values():refresh_template(combat,view,identity)
        self.plant();self.case.send(0,encode_end_turn());self.case.hub.tick();self.clear()
        packets=self.case.send(1,encode_move_request(BattleMove(identity,((7,5),(6,5)))))
        other=tuple(self.case.hub.queues[self.owners[0]])
        for replies in (packets,other):
            soldier=next(p for p in replies if p[0]==0x3b and int.from_bytes(p[1:5],'little')==identity)
            self.assertEqual(decode_battle_soldier(soldier,human_equipment=True).fields['0x8c531b'],0)
        self.assertTrue(any(p[0]==0x30 and decode_item_list(p)[0]==identity for p in packets))
        self.assertFalse(any(p[0]==0x30 and decode_item_list(p)[0]==identity for p in other))
        self.assertFalse(decode_item_list(OwnedPetStore(self.case.path).inventory('bob',1))[1])

    def rows(self):
        with closing(sqlite3.connect(self.case.path)) as db:
            tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {t:tuple(db.execute('SELECT * FROM "'+t+'"').fetchall()) for t in tables}


if __name__=='__main__':unittest.main()
