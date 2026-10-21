from dataclasses import replace
import unittest

from server.battle_events import movement_packets,project_action
from tio.battle_state import BattleActor,BattleField
from tio.visibility import VisibilityView
from tio.protocol.battle_move import BattleMove,encode_battle_move,decode_battle_move
from tio.protocol.battle_attack import AttackResult,AttackHit,encode_attack_result,decode_attack_result


class MinimalView(VisibilityView):
    def snapshot(self,identity):
        # Snapshot position is checked without requiring a full equipment fixture.
        actor=self.field.actor(identity)
        return b'\x3b'+identity.to_bytes(4,'little')+bytes((actor.x,actor.y))


class BattleEventsTests(unittest.TestCase):
    def test_scope_use_animation_is_visible_but_cooldown_and_hidden_actor_are_private(self):
        from tio.protocol.ability_status import AbilityStatus,encode_ability_status,decode_ability_status
        field=BattleField(32,32,[BattleActor(1,10,5,5,20,100,100),BattleActor(2,20,6,5,20,100,100)],step_cost=1)
        view=MinimalView(field,10,{})
        view.refresh();before=dict(field._actors)
        used=AbilityStatus(9,1,0,0);cooldown=AbilityStatus(23,1,3,2)
        packet=encode_ability_status(2,(used,cooldown))
        result=project_action(view,20,before,frozenset((1,2)),(packet,))
        self.assertEqual([decode_ability_status(p) for p in result if p[:2]==b'\x7f\x01'],[(2,(used,))])
        result=project_action(view,20,before,frozenset((1,)),(packet,))
        self.assertFalse(any(p[:2]==b'\x7f\x01' for p in result))
        own=encode_ability_status(1,(used,cooldown))
        self.assertIn(own,project_action(view,10,before,frozenset((1,2)),(own,)))

    def test_movement_projection_preserves_corpse_without_resending_death(self):
        field=BattleField(32,32,[BattleActor(1,10,5,5,20,100,100,2),
                               BattleActor(2,20,20,20,20,100,100,2),
                               BattleActor(3,20,6,5,20,100,100,2)],step_cost=1)
        view=MinimalView(field,10,{})
        view.refresh()
        field._actors[3]=replace(field.actor(3),health=0)
        view.refresh()
        field._actors[1]=replace(field.actor(1),x=10,y=10)
        view.refresh()
        before=dict(field._actors)
        field._actors[2]=replace(field.actor(2),x=21)
        from unittest.mock import patch
        with patch('server.battle_events.VisibilityView',MinimalView):
            packets=movement_packets(view,before,encode_battle_move(BattleMove(2,((21,20),))))
        self.assertEqual(view.resident_corpses,{3})
        self.assertNotIn(3,view.visible)
        self.assertFalse(any(p[0] in (0x3b,0x43,0x4e) and int.from_bytes(p[1:5],'little')==3 for p in packets))
        field._actors[1]=replace(field.actor(1),x=5,y=5)
        packets=view.refresh()
        self.assertIn(3,view.visible)
        self.assertFalse(any(p[0] in (0x3b,0x43,0x4e) and int.from_bytes(p[1:5],'little')==3 for p in packets))

    def test_path_entering_and_leaving_sight_never_leaks_hidden_coordinates(self):
        # Enemy traverses the observer's radius: hidden -> visible -> hidden.
        field=BattleField(16,16,[BattleActor(1,10,5,5,20,100,100,2),
                               BattleActor(2,20,1,6,20,100,100,2)],step_cost=1)
        view=MinimalView(field,10,{})
        view.refresh();before=dict(field._actors)
        path=tuple((x,6) for x in range(2,10))
        field._actors[2]=replace(field.actor(2),x=9)
        # Use minimal snapshots in the replay too.
        from unittest.mock import patch
        with patch('server.battle_events.VisibilityView',MinimalView):
            packets=movement_packets(view,before,encode_battle_move(BattleMove(2,path)))
        steps=tuple(c for p in packets if p[0]==0x3d for c in decode_battle_move(p).path)
        self.assertEqual(steps,((5,6),(6,6)))
        self.assertIn(b'\x3b'+(2).to_bytes(4,'little')+bytes((4,6)),packets)
        self.assertNotIn(2,view.visible)
        self.assertEqual(field.actor(2).x,9)

    def test_attack_filters_unseen_hits_and_hidden_shooter(self):
        field=BattleField(16,16,[BattleActor(i,i,2*i,5,20,100,100) for i in (1,2,3)],step_cost=1)
        view=MinimalView(field,1,{})
        view.visible=frozenset((1,2));before=dict(field._actors)
        attack=AttackResult(2,(4,5),(2,5),333,(AttackHit(1,10,90),AttackHit(3,20,80)))
        packet=encode_attack_result(attack)
        result=project_action(view,2,before,frozenset((1,2)),(packet,))
        shown=decode_attack_result(next(p for p in result if p[0]==0x4b))
        self.assertEqual([h.actor_id for h in shown.hits],[1])
        field._actors[1]=replace(field.actor(1),health=90)
        result=project_action(view,2,before,frozenset((1,)),(packet,))
        self.assertFalse(any(p[0]==0x4b for p in result))
        self.assertTrue(any(p[0]==0x4e for p in result))
