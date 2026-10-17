import unittest
from dataclasses import replace
from tio.battle_state import BattleActor, BattleField
from tio.protocol.battle_move import BattleMove, decode_battle_move
from tio.visibility import visible_actors


class MovementContactTests(unittest.TestCase):
    def field(self, *, enemy=None, others=(), teams=None, blocked=(), step_cost=1):
        return BattleField(24, 12, [BattleActor(1, 10, 1, 1, 15, 100, 100, sight_radius=3),
            enemy or BattleActor(2, 20, 8, 3, 15, 100, 100), *others],
            blocked=blocked, teams=teams, step_cost=step_cost)

    def test_first_contact_truncates_wire_path_and_preserves_ap(self):
        field=self.field()
        path=tuple((x, 1) for x in range(2, 17))
        self.assertNotIn(2, visible_actors(field, 10))
        reply=decode_battle_move(field.move(10, BattleMove(1, path)))
        self.assertEqual(reply.path, path[:5])
        self.assertEqual((field.actor(1).x, field.actor(1).action_points), (6, 10))
        self.assertIn(2, visible_actors(field, 10))
        # A fresh order can spend the remaining budget, despite the known enemy.
        reply=decode_battle_move(field.move(10, BattleMove(1, path[5:])))
        self.assertEqual(reply.path, path[5:])
        self.assertEqual(field.actor(1).action_points, 0)

    def test_allies_corpses_and_shared_known_enemy_do_not_stop(self):
        for kwargs in (
            {'enemy': BattleActor(2, 10, 8, 3, 15, 100, 100)},
            {'enemy': BattleActor(2, 20, 8, 3, 15, 0, 100)},
            {'others': (BattleActor(3, 30, 8, 4, 15, 100, 100),),
             'teams': {10: 1, 30: 1, 20: 2}},
        ):
            with self.subTest(kwargs=kwargs):
                field=self.field(**kwargs)
                path=tuple((x, 1) for x in range(2, 17))
                self.assertEqual(decode_battle_move(field.move(10, BattleMove(1, path))).path, path)

    def test_wall_hides_enemy_until_line_of_sight_opens(self):
        field=self.field(enemy=BattleActor(2, 20, 5, 1, 15, 100, 100), blocked={(3, 1)})
        field._actors[1]=replace(field.actor(1), sight_radius=9)
        self.assertNotIn(2, visible_actors(field, 10))
        path=((1, 2), (1, 3), (2, 3), (3, 3), (4, 3))
        reply=decode_battle_move(field.move(10, BattleMove(1, path)))
        self.assertLess(len(reply.path), len(path))
        self.assertIn(2, visible_actors(field, 10))
        self.assertEqual(field.actor(1).action_points, 15-len(reply.path))

    def test_invalid_tail_does_not_commit_partial_movement(self):
        field=self.field(); before=dict(field._actors)
        for path in (tuple((x, 1) for x in range(2, 9))+((15, 1),),
                     tuple((x, 1) for x in range(2, 18))):
            with self.assertRaises(ValueError):field.move(10, BattleMove(1, path))
            self.assertEqual(field._actors, before)

    def test_origin_and_nonunit_cost(self):
        field=self.field(step_cost=2)
        path=tuple((x, 1) for x in range(1, 9))
        reply=decode_battle_move(field.move(10, BattleMove(1, path)))
        self.assertEqual(reply.path, path[1:6])
        self.assertEqual(field.actor(1).action_points, 5)
