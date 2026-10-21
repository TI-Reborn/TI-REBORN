"""Heavy ground fire: shared damage, fog privacy and atomic ammunition costs."""
import random
import sqlite3
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import test_weapon_effects as fixtures
from tio.protocol.battle_attack import AttackRequest, decode_attack_result
from tio.protocol.item_list import decode_item_list
from tio.visibility import visible_actors


class AreaFireTests(unittest.TestCase):
    def prepare(self, weapon=314, count=100):
        field, combat = fixtures.WeaponEffectsTests().setup_effect(weapon, 14, count)
        field._actors[1] = replace(field.actor(1), x=2, y=4)
        field._actors[2] = replace(field.actor(2), x=7, y=3)
        field._actors[3] = replace(field.actor(3), x=7, y=5)
        return field, combat

    def test_empty_aim_between_two_actors_hits_enemy_and_ally_for_one_burst(self):
        for weapon, count, ap in ((314, 20, 9), (315, 30, 10)):
            with self.subTest(weapon=weapon):
                f, c = self.prepare(weapon, count)
                result = decode_attack_result(c.attack(7, AttackRequest(1, 7, 4))[0])
                self.assertEqual((result.weapon_id, result.target), (weapon, (7, 4)))
                self.assertEqual({h.actor_id for h in result.hits}, {2, 3})
                self.assertTrue(all(h.damage > 0 for h in result.hits))
                self.assertEqual(f.actor(1).action_points, 40-ap)
                self.assertEqual([i.template_id for i in decode_item_list(c.inventories[1])[1]], [weapon])
                self.assertEqual(c.statistics[7]['damage_dealt'], result.hits[0].damage)

    def test_empty_sector_still_animates_consumes_and_wears_once(self):
        for weapon, ap, ammo in ((314, 9, 20), (315, 10, 30)):
            f, c = self.prepare(weapon)
            result = decode_attack_result(c.attack(7, AttackRequest(1, 2, 1))[0])
            self.assertEqual(result.hits, ())
            self.assertEqual(f.actor(1).action_points, 40-ap)
            items = decode_item_list(c.inventories[1])[1]
            self.assertEqual((items[0].unknown_words[0], items[1].count), (300-ap, 100-ammo))

    def test_sector_excludes_behind_outside_and_dead_actors(self):
        for position, hp in (((1, 4), 500), ((7, 6), 500), ((15, 4), 500), ((7, 4), 0)):
            f, c = self.prepare()
            f._actors[2] = replace(f.actor(2), x=position[0], y=position[1], health=hp)
            result = decode_attack_result(c.attack(7, AttackRequest(1, 7, 4))[0])
            self.assertNotIn(2, [h.actor_id for h in result.hits])
            self.assertEqual(f.actor(1).health, 100)

    def test_piercing_continues_past_aim_cell_but_respects_each_weapon_range(self):
        for weapon, maximum in ((314, 12), (315, 8)):
            for distance, hit in ((maximum, True), (maximum+1, False)):
                f, c = self.prepare(weapon)
                f._actors[2] = replace(f.actor(2), x=2+distance, y=4)
                result = decode_attack_result(c.attack(7, AttackRequest(1, 5, 4))[0])
                self.assertEqual(2 in [h.actor_id for h in result.hits], hit)

    def test_m60_aim_at_twelve_and_thirteen_cell_boundary(self):
        f,c=self.prepare(314,40)
        f._actors[2]=replace(f.actor(2),x=14,y=4)
        result=decode_attack_result(c.attack(7,AttackRequest(1,14,4))[0])
        self.assertIn(2,[h.actor_id for h in result.hits])
        self.assertEqual(f.actor(1).action_points,31)
        self.assertEqual(next(i.count for i in decode_item_list(c.inventories[1])[1] if i.template_id==14),20)
        before=dict(f._actors),dict(c.inventories)
        with self.assertRaisesRegex(ValueError,'range'):c.attack(7,AttackRequest(1,15,4))
        self.assertEqual((f._actors,c.inventories),before)

    def test_walls_block_individual_rays_not_the_whole_sector(self):
        f, c = self.prepare()
        f.blocked = frozenset(((7, 3),))
        result = decode_attack_result(c.attack(7, AttackRequest(1, 7, 4))[0])
        self.assertEqual([h.actor_id for h in result.hits], [3])
        self.assertEqual(f.actor(2).health, 500)

    def test_aim_can_point_toward_wall_without_shooting_through_it(self):
        f, c = self.prepare()
        f._actors[2] = replace(f.actor(2), x=5, y=4)
        f._actors[3] = replace(f.actor(3), x=9, y=4)
        f.blocked = frozenset(((7, 3), (7, 4), (7, 5)))
        result = decode_attack_result(c.attack(7, AttackRequest(1, 7, 4))[0])
        self.assertEqual([h.actor_id for h in result.hits], [2])
        self.assertEqual(f.actor(3).health, 500)

    def test_fences_follow_existing_transparent_shot_geometry(self):
        f, c = self.prepare()
        f._actors[2] = replace(f.actor(2), x=7, y=4)
        f.blocked = frozenset(((5, 3), (5, 4), (5, 5)))
        f.transparent_obstacles = f.blocked
        result = decode_attack_result(c.attack(7, AttackRequest(1, 7, 4))[0])
        self.assertIn(2, [h.actor_id for h in result.hits])

    def test_smoke_keeps_existing_bullet_obstruction_rule(self):
        from tio.battle_item_effects import initialize
        f, c = self.prepare()
        initialize(c)['areas'][1] = dict(kind='smoke', center=(5, 4), radius=2)
        result = decode_attack_result(c.attack(7, AttackRequest(1, 7, 4))[0])
        self.assertEqual(result.hits, ())
        self.assertEqual(f.actor(2).health, 500)

    def test_blind_fire_damage_does_not_disclose_hidden_target(self):
        f, c = self.prepare()
        f._actors[1] = replace(f.actor(1), sight_radius=1)
        f._actors[3] = replace(f.actor(3), x=1, y=1, sight_radius=1)
        known = visible_actors(f, 7)
        self.assertNotIn(2, known)
        from tio.visibility import VisibilityView
        view = VisibilityView(f, 7, {})
        view.visible = known
        # No template refresh is needed when proficiency/equipment is unchanged.
        result = decode_attack_result(c.attack(7, AttackRequest(1, 7, 4), view=view)[0])
        self.assertLess(f.actor(2).health, 500)
        self.assertEqual(result.hits, ())

    def test_invalid_requests_and_insufficient_resources_are_atomic(self):
        for owner, x, y, count, ap in ((8,7,4,100,40), (7,2,4,100,40), (7,23,4,100,40),
                                       (7,24,4,100,40), (7,7,4,19,40), (7,7,4,100,8)):
            f, c = self.prepare(count=count)
            f._actors[1] = replace(f.actor(1), action_points=ap)
            before = dict(f._actors), dict(c.inventories)
            with self.assertRaises(ValueError): c.attack(owner, AttackRequest(1,x,y))
            self.assertEqual((f._actors, c.inventories), before)

    def test_other_weapons_still_require_visible_enemy(self):
        f, c = self.prepare(301)
        before = dict(f._actors), dict(c.inventories)
        with self.assertRaisesRegex(ValueError, 'Visible enemy'): c.attack(7, AttackRequest(1,7,4))
        self.assertEqual((f._actors, c.inventories), before)

    def test_storage_failure_restores_hp_ammo_ap_statistics_and_random_state(self):
        f, c = self.prepare()
        c.rng = random.Random(1349)
        before = dict(f._actors), dict(c.inventories), dict(c.statistics), c.rng.getstate()
        with patch.object(c, '_persist_batch', side_effect=sqlite3.OperationalError('injected')):
            with self.assertRaises(sqlite3.OperationalError): c.attack(7, AttackRequest(1,7,4))
        self.assertEqual((f._actors, c.inventories, c.statistics, c.rng.getstate()), before)
