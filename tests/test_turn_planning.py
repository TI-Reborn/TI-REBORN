from dataclasses import replace
import unittest

import test_tactical_bot as fixture
from tio.control_points import ControlPoints
from tio.protocol.item_list import encode_item_list
from tio.tactical_bot import play_actor
from tio.training_bot import bot_known
from tio.turn_planning import TurnObjective, choose_plan, expected_reply
from tio.visibility import visible_actors


class TurnPlanningTests(unittest.TestCase):
    def scene(self, *, bot=(3, 3), enemy=(12, 3), blocked=(), ap=15, flag=(10, 8)):
        case = fixture.TacticalBotTests()
        field, arena, _ = case.scene(bot=bot, enemy=enemy, blocked=blocked, ap=ap,
                                      sight=15, bag=case.gun())
        field.teams = {7: 0, 8: 1}
        field.combat.inventories[2] = encode_item_list(2, (fixture.item(20, 303, equipped=True, slot=16),
                                                          fixture.item(21, 3, 40)))
        field._actors[2] = replace(field.actor(2), health=100, max_health=100,
                                   weapons=(field.combat.catalog.weapons[303],))
        return field, arena, TurnObjective(ControlPoints((flag,), [None], [0, 20]), 60)

    def test_late_trailing_bot_ends_within_reach_of_the_flag(self):
        field, _, objective = self.scene(enemy=(23, 15), flag=(8, 3))
        plan = choose_plan(field, 1, bot_known(field, 7, 1), objective)
        end = (plan.after or plan.before)[-1]
        self.assertLessEqual(abs(end[0]-8)+abs(end[1]-3), 2)
        self.assertIsNone(plan.target)

    def test_response_considers_a_move_then_fire_using_observed_weapon(self):
        field, _, _ = self.scene(enemy=(11, 3))
        visible = bot_known(field, 7, 1)
        reply = expected_reply(field, 1, visible)
        self.assertGreater(reply((3, 3))[2], 0)
        self.assertGreater(reply((3, 3))[2], reply((0, 15))[2])
        field.combat.inventories[2] = encode_item_list(2, ())
        self.assertEqual(expected_reply(field, 1, visible)((3, 3)), reply((3, 3)))

    def test_hidden_enemy_and_rng_do_not_change_a_plan(self):
        field, _, objective = self.scene()
        known = bot_known(field, 7, 1)
        state = field.combat.rng.getstate()
        before = choose_plan(field, 1, known, objective)
        hidden = replace(field.actor(2), actor_id=3, owner_id=9, x=23, y=15)
        field._actors[3] = hidden
        self.assertEqual(bot_known(field, 7, 1), known)
        self.assertEqual(choose_plan(field, 1, known, objective), before)
        self.assertEqual(field.combat.rng.getstate(), state)

    def test_reply_uses_a_frozen_sighting_after_enemy_leaves_fog(self):
        from server.battle_events import remember_tournament_sight
        from tio.battle_snapshot import dumps, loads
        field, _, _ = self.scene(enemy=(6, 3))
        battle = {'field': field, 'bots': {7}}
        remember_tournament_sight(battle, 8)
        seen = battle['bot_sightings'][7][2]
        field._actors[2] = replace(field.actor(2), x=23, y=15)
        remember_tournament_sight(battle, 8)
        observed = battle['bot_sightings'][7]
        self.assertEqual(observed[2], seen)
        restored, _ = loads(dumps(observed))
        self.assertEqual(restored, observed)
        known = bot_known(field, 7, 1)
        self.assertNotIn(2, expected_reply(field, 1, known)((3, 3)))
        self.assertGreater(expected_reply(field, 1, known, tuple(restored.values()))((3, 3))[2], 0)

    def test_plan_accounts_for_ammo_and_uses_server_action_points(self):
        field, _, objective = self.scene(enemy=(5, 3), flag=(3, 5), ap=7)
        field._actors[2] = replace(field.actor(2), health=5)
        field.combat.inventories[1] = encode_item_list(1, (fixture.item(10, 301, equipped=True, slot=16),
                                                          fixture.item(11, 3, 1)))
        plan = choose_plan(field, 1, bot_known(field, 7, 1), objective)
        self.assertEqual((plan.target, plan.shots), (2, 1))
        self.assertLessEqual(len(plan.before)+3+len(plan.after), 7)

    def test_fires_and_breaks_enemy_sight_instead_of_spending_all_ap_on_shots(self):
        field, arena, objective = self.scene(bot=(3, 3), enemy=(7, 3), ap=11, flag=(3, 3))
        objective.points.owners[0] = 0
        objective.points.scores[:] = [15, 0]
        self.assertIn(1, visible_actors(field, 8))

        packets = play_actor(arena, 1, 7, 1, objective=replace(objective, seconds_left=480))

        self.assertTrue(any(packet[0] == 0x4b for packet in packets))
        self.assertNotIn(1, visible_actors(field, 8))
        self.assertEqual(objective.points.owners, [0])

    def test_leaves_open_captured_flag_for_a_nearby_guard_position(self):
        flag = (10, 8)
        wall = tuple((8, y) for y in range(8, 14))
        field, _, objective = self.scene(bot=flag, enemy=(23, 15), flag=flag, blocked=wall)
        field._actors[1] = replace(field.actor(1), sight_radius=8)
        objective.points.owners[0] = 0
        known = bot_known(field, 7, 1)
        self.assertNotIn(2, known)

        plan = choose_plan(field, 1, known, replace(objective, seconds_left=480))

        self.assertGreater(len(plan.before), 0)
        self.assertLessEqual(len(plan.before), 6)
        self.assertIsNone(plan.target)

    def test_does_not_abandon_reachable_flag_when_losing_late(self):
        field, _, objective = self.scene(bot=(3, 3), enemy=(23, 15), flag=(8, 3))
        objective.points.owners[0] = 1
        plan = choose_plan(field, 1, bot_known(field, 7, 1), objective)
        x, y = plan.before[-1]
        self.assertLessEqual(abs(x-8)+abs(y-3), objective.points.radius)
