"""Approved mine armor reaches shared state, client packets and actual damage."""
from dataclasses import replace
import unittest

import test_mine_automatic_damage as shooting
from tio.protocol.battle_attack import AttackRequest, decode_attack_result
from tio.protocol.item_list import decode_item_list


class MineArmorBalanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = shooting.MineAutomaticDamageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_all_mine_bands_publish_the_approved_armor_and_keep_health(self):
        for levels, armor, hp in (((4, 6), 128, 150), ((7, 10), 180, 249),
                                  ((11, 15), 200, 249), ((16, 20), 240, 300)):
            for level in levels:
                with self.subTest(level=level):
                    scene = self.fixture.prepare(level=level)
                    field = scene.field
                    self.assertTrue(field.actor_ids(42))
                    self.assertTrue(field.actor_ids(43))
                    mobs = field.actor_ids(scene.bot_owner)
                    self.assertEqual(len(mobs), 10)
                    for identity in mobs:
                        self.assertEqual(field.combat.defense(identity), armor)
                        self.assertEqual(field.actor(identity).max_health, hp)
                        self.assertEqual(
                            scene.visibility.templates[identity].fields['0x8c5731'], armor)

    def test_aug_damage_for_two_owners_with_original_ap_and_ammunition_cost(self):
        for owner in (42, 43):
            for upgrade, skill, high, expected in (
                    (0, 140, False, 25), (0, 140, True, 37),
                    (20, 140, False, 47), (20, 140, True, 59),
                    (20, 35, False, 23), (20, 35, True, 29)):
                with self.subTest(owner=owner, upgrade=upgrade, skill=skill, high=high):
                    scene = self.fixture.prepare(level=14, upgrade=upgrade,
                                                 skill=skill, weapon_id=311)
                    field, combat = scene.field, scene.field.combat
                    actor, = field.actor_ids(owner)
                    target = field.actor_ids(scene.bot_owner)[0]
                    field.blocked = field.transparent_obstacles = frozenset()
                    field._actors[actor] = replace(field.actor(actor), x=10, y=10,
                                                   sight_radius=20, action_points=100)
                    field._actors[target] = replace(field.actor(target), x=14, y=10)
                    combat.rng = shooting.AttackRandom(high=high)
                    before = field.actor(target).health
                    result = decode_attack_result(combat.attack(
                        owner, AttackRequest(actor, 14, 10))[0])
                    hit, = result.hits
                    self.assertEqual(hit.damage, expected)
                    self.assertEqual(before - field.actor(target).health, expected)
                    self.assertEqual(hit.left_hp, field.actor(target).health)
                    self.assertEqual(field.actor(actor).action_points, 94)
                    self.assertEqual(sum(item.count for item in decode_item_list(
                        combat.inventories[actor])[1] if item.template_id == 5), 95)
                    self.assertEqual(tuple(combat.rng.rolls), ())


if __name__ == '__main__':
    unittest.main()
