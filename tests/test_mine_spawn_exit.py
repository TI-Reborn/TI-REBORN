"""Movement inside the mine admission area must not settle a defeat."""
from dataclasses import replace
import unittest

import test_shared_mine_arena as fixture
from tio.protocol.battle_move import BattleMove, encode_move_request
from tio.protocol.battle_turn import encode_end_turn


class MineSpawnExitTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.SharedMineArenaTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def move_inside(self, battle, index=0):
        field = battle['field']
        owner = self.case.owners[index]
        actor, = field.actor_ids(owner)
        current = field.actor(actor)
        exits = field.mining.layout.raider_exits if index == 1 else field.mining.layout.lift
        occupied = {(a.x, a.y) for a in field._actors.values() if a.health}
        destination = next((current.x + dx, current.y + dy)
                           for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                           if (current.x + dx, current.y + dy) in exits - occupied)
        self.case.hub.queues[owner].clear()
        replies = self.case.send(index, encode_move_request(BattleMove(actor, (destination,))))
        self.assertFalse(any(p[0] == 0xf0 for p in replies), replies)
        self.assertTrue(any(p[0] == 0x3d for p in replies), replies)
        self.assertFalse(any(p[0] == 0x4c for p in replies), 'First step settled a result')
        self.assertIs(self.case.hub.battles.get(owner), battle)
        self.assertNotIn(owner, battle['settled'])
        self.assertEqual((field.actor(actor).x, field.actor(actor).y), destination)

    def test_first_step_inside_miner_spawn_keeps_battle_active(self):
        self.move_inside(self.case.enter((0,)))

    def test_empty_drill_does_not_turn_first_step_into_defeat(self):
        battle = self.case.enter((0,))
        self.case.carry_at_exit(battle, 0, 0)
        self.move_inside(battle)

    def test_empty_drill_does_not_auto_exit_when_ending_turn(self):
        battle = self.case.enter((0,))
        self.case.carry_at_exit(battle, 0, 0)
        replies = self.case.send(0, encode_end_turn())
        self.assertFalse(any(p[0] == 0x4c for p in replies))
        self.assertIs(self.case.hub.battles.get(self.case.owners[0]), battle)

    def test_raider_step_inside_entry_after_lock_expires_keeps_battle(self):
        battle = self.case.enter((0, 1))
        self.case.advance_round(battle, 5)
        owner = self.case.owners[1]
        with self.case.hub.journal.unit(battle):
            field = battle['field']
            for actor in field.living_actor_ids(owner):
                field._actors[actor] = replace(field.actor(actor), action_points=20)
            battle['arena']._turns[battle['room'].room_id] = (
                owner, set(field.living_actor_ids(owner)), self.case.case.now + 60)
        self.move_inside(battle, 1)

    def test_returning_to_exit_without_menu_does_not_finish_battle(self):
        battle = self.case.enter((0,))
        field = battle['field']
        owner = self.case.owners[0]
        actor, = field.actor_ids(owner)
        exits = field.mining.layout.lift
        occupied = {(a.x, a.y) for a in field._actors.values() if a.actor_id != actor and a.health}
        inside, outside = next((p, (p[0] + dx, p[1] + dy)) for p in sorted(exits)
                               for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                               if p not in occupied and field.inside(p[0] + dx, p[1] + dy)
                               and (p[0] + dx, p[1] + dy) not in exits | field.blocked | occupied)
        with self.case.hub.journal.unit(battle):
            field._actors[actor] = replace(field.actor(actor), x=inside[0], y=inside[1])
        replies = self.case.send(0, encode_move_request(BattleMove(actor, (outside,))))
        self.assertFalse(any(p[0] == 0x4c for p in replies))
        self.assertIs(self.case.hub.battles.get(owner), battle)
        replies = self.case.send(0, encode_move_request(BattleMove(actor, (inside,))))
        self.assertFalse(any(p[0] == 0x4c for p in replies))
        self.assertIs(self.case.hub.battles.get(owner), battle)
        self.assertFalse(battle['finished'])

    def test_loaded_drill_at_exit_waits_for_explicit_menu_request(self):
        battle = self.case.enter((0,))
        self.case.carry_at_exit(battle, 0, 200)
        self.move_inside(battle)
        replies = self.case.send(0, encode_end_turn())
        self.assertFalse(any(p[0] == 0x4c for p in replies))
        self.assertIs(self.case.hub.battles.get(self.case.owners[0]), battle)
        replies = self.case.send(0, b'\x2a\x01')
        self.assertEqual(next(p for p in replies if p[0] == 0x4c)[3], 1)
        self.assertTrue(battle['finished'])


if __name__ == '__main__':
    unittest.main()
