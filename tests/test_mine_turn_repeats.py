"""Repeat EndTurn must not consume a new shared mine turn."""
import unittest
from unittest.mock import patch

import test_shared_mine_arena as fixtures
from tio.protocol.battle_turn import encode_end_turn


class MineTurnRepeatTests(unittest.TestCase):
    def setUp(self):
        self.mine = fixtures.SharedMineArenaTests()
        self.mine.setUp()
        self.addCleanup(self.mine.doCleanups)

    def next_turn(self, battle, owner):
        room = battle['room'].room_id
        for _ in range(8):
            turn = battle['arena']._turns.get(room)
            if turn and turn[0] == owner:
                return turn
            if turn:
                self.mine.case.now += 1.01
                self.mine.send(self.mine.owners.index(turn[0]), encode_end_turn())
            self.mine.hub.tick()
        self.fail('Human turn did not start')

    def assert_repeat_preserves_turn(self, battle, owner):
        room = battle['room'].room_id
        turn = self.next_turn(battle, owner)
        actors = tuple(battle['field'].actor(i) for i in battle['field'].actor_ids(owner))
        round_number = battle['field'].mining.round
        # The timeout/exhaustion tick already queued the old turn's finish.
        self.mine.hub.queues[owner].clear()
        replies = self.mine.send(self.mine.owners.index(owner), encode_end_turn())
        self.assertEqual(battle['arena']._turns.get(room), turn)
        self.assertEqual(tuple(battle['field'].actor(a.actor_id) for a in actors), actors)
        self.assertEqual(battle['field'].mining.round, round_number)
        self.assertNotIn(b'\x39', replies)
        # A deliberate subsequent skip remains possible after the short fence.
        self.mine.case.now += 1.01
        self.mine.send(self.mine.owners.index(owner), encode_end_turn())
        self.assertNotIn(room, battle['arena']._turns)

    def test_repeat_after_slow_mutants_preserves_next_turn(self):
        battle = self.mine.enter((0,))
        self.mine.park_mutants(battle)
        owner = self.mine.owners[0]
        self.mine.send(0, encode_end_turn())
        # The synchronous AI can take longer than the original one-second
        # fence while the legacy client's repeated packet waits in the socket.
        from tio.training_bot import play_turn
        def slow_turn(*args, **kwargs):
            result = play_turn(*args, **kwargs)
            self.mine.case.now += 3
            return result
        with patch('tio.training_bot.play_turn', side_effect=slow_turn):
            self.assert_repeat_preserves_turn(battle, owner)

    def test_timeout_then_late_client_end_turn_preserves_next_turn(self):
        battle = self.mine.enter((0,))
        self.mine.park_mutants(battle)
        room = battle['room'].room_id
        self.mine.case.now = battle['arena']._turns[room][2] + .01
        self.mine.hub.tick()
        self.assert_repeat_preserves_turn(battle, self.mine.owners[0])

    def test_exhaustion_then_late_client_end_turn_preserves_next_turn(self):
        battle = self.mine.enter((0,))
        self.mine.park_mutants(battle)
        owner = self.mine.owners[0]
        field = battle['field']
        from dataclasses import replace
        for identity in field.actor_ids(owner):
            field._actors[identity] = replace(field.actor(identity), action_points=0)
        self.mine.hub.tick()
        self.mine.case.now += 3
        self.assert_repeat_preserves_turn(battle, owner)

    def test_repeat_after_other_players_preserves_next_turn(self):
        battle = self.mine.enter()
        self.mine.park_mutants(battle)
        owner = self.mine.owners[0]
        self.mine.send(0, encode_end_turn())
        self.mine.case.now += 3
        self.assert_repeat_preserves_turn(battle, owner)


if __name__ == '__main__':
    unittest.main()
