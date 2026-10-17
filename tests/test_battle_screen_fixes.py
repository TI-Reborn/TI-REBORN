"""Screenshot regressions: native-safe bot owners, initial doors, late EndTurn."""
from dataclasses import replace
import unittest
from unittest.mock import patch
from tio.protocol.battle_turn import encode_end_turn
from tio.visibility import VisibilityView,visible_actors
from tio.protocol.battle_door import DoorRequest,encode_door_state
import test_shared_survival_groups as survival
import test_battle_doors as doors

class ScreenshotTests(unittest.TestCase):
    def solo(self):
        c=survival.SharedSurvivalGroupsTests();c.setUp();self.addCleanup(c.doCleanups)
        owners=c.join(1);c.now=60;c.hub.tick()
        b=c.hub.battles[owners[0]]
        c.send(0,b'\x36');c.hub.tick()
        return c,owners[0],b

    def test_survival_bot_owner_is_native_signed_safe_and_unique(self):
        c,owner,b=self.solo()
        bot=next(iter(b['bots']))
        self.assertTrue(0<bot<0x80000000)
        self.assertNotEqual(bot,owner)
        self.assertTrue(all(b['views'][owner].templates[i].owner_id==bot for i in b['field'].actor_ids(bot)))

    def finish_cycle(self,c,owner,b):
        # A fast bot (as in the reported replay); authoritative turn setup and
        # finish still run. Isolate tactic/random map costs from turn timing.
        def fast(arena,room,bot):
            arena.begin_turn_packets(bot,b['field'].living_actor_ids(bot),40)
            arena.end_turn(bot,encode_end_turn())
        with patch('tio.training_bot.play_turn',side_effect=fast):
            c.hub.tick();c.hub.tick()
        self.assertEqual(b['arena']._turns[b['room'].room_id][0],owner)

    def test_delayed_duplicate_cannot_finish_next_turn_or_reset_deadline(self):
        c,owner,b=self.solo();c.send(0,encode_end_turn())
        c.now+=.1;self.finish_cycle(c,owner,b)
        turn=b['arena']._turns[b['room'].room_id];actors=dict(b['field']._actors)
        c.now+=.16
        replies=c.send(0,encode_end_turn())
        self.assertNotIn(b'\x39',replies)
        self.assertEqual(b['arena']._turns[b['room'].room_id],turn)
        self.assertEqual(b['field']._actors,actors)
        c.now=61.01;c.send(0,encode_end_turn())
        self.assertNotIn(b['room'].room_id,b['arena']._turns)

    def test_zero_ap_late_end_turn_does_not_skip_fresh_turn(self):
        c,owner,b=self.solo();f=b['field']
        for i in f.actor_ids(owner):f._actors[i]=replace(f.actor(i),action_points=0)
        c.hub.finish_exhausted_turn(b)
        c.now+=.1;self.finish_cycle(c,owner,b)
        turn=b['arena']._turns[b['room'].room_id]
        c.now+=.1;c.send(0,encode_end_turn())
        self.assertEqual(b['arena']._turns[b['room'].room_id],turn)
        self.assertTrue(all(f.actor(i).action_points>0 for i in f.living_actor_ids(owner)))

    def test_expired_turn_late_end_turn_does_not_skip_fresh_turn(self):
        c,owner,b=self.solo()
        c.now=101;self.finish_cycle(c,owner,b)
        turn=b['arena']._turns[b['room'].room_id]
        c.now+=.1;c.send(0,encode_end_turn())
        self.assertEqual(b['arena']._turns[b['room'].room_id],turn)

    def test_initial_closed_door_state_sent_without_revealing_enemy(self):
        c=doors.DoorTests();c.setUp();f=c.field
        view=VisibilityView(f,7,{})
        view.visible=visible_actors(f,7) # no soldier templates needed for this update
        expected=encode_door_state(DoorRequest(0,False,3,3))
        self.assertNotIn(2,view.visible)
        self.assertIn(expected,view.refresh())
        self.assertNotIn(expected,view.refresh())
        self.assertEqual(f.actor(1).action_points,10)

    def test_initial_unseen_door_waits_until_surface_in_sight(self):
        c=doors.DoorTests();c.setUp();f=c.field
        f._actors[1]=replace(f.actor(1),sight_radius=0)
        view=VisibilityView(f,7,{});view.visible=visible_actors(f,7)
        self.assertFalse(any(p[0]==0x3f for p in view.refresh()))
        f._actors[1]=replace(f.actor(1),sight_radius=9)
        self.assertIn(encode_door_state(DoorRequest(0,False,3,3)),view.refresh())
        self.assertNotIn(2,visible_actors(f,7))
