"""Exercise every upgradeable weapon through authoritative combat and packets."""
import unittest
from dataclasses import replace

from tio.battle_state import BattleActor, BattleField
from tio.combat import Combat
from tio.enhancement import EnhancementRules
from tio.protocol.battle_attack import AttackRequest, decode_attack_result
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.weapons import WeaponCatalog
from test_combat import FixedRandom, item
from test_weapon_proficiency import change, profile


class HighDamageRandom(FixedRandom):
    def randint(self, low, high):
        return high


class CriticalRandom(FixedRandom):
    def randrange(self, stop):
        return 0


class WeaponEnhancementDamageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = WeaponCatalog()
        cls.rules = EnhancementRules()
        cls.weapons = tuple(sorted(
            identity for identity, rule in cls.rules.items.items()
            if rule['kind'] == 'weapon'
        ))
        # Perforator has no ammo rule; its separate test records that defect.
        cls.firing_weapons = tuple(i for i in cls.weapons if i != 322)
        cls.profiles = {level: profile(level) for level in (1, 4, 7, 11, 16)}

    def attack_damage(self, identity, enhancement, *, level=16, high=False,
                      distance=None, armored=False, displayed=0, critical=False):
        weapon = self.catalog.weapons[identity]
        distance = distance or max(1, weapon.min_range)
        equipped = replace(
            item(1, identity, equipped=True),
            unknown_bytes_03=bytes((enhancement, 0, 0)),
            unknown_bytes_02=bytes((displayed, 0, 0, 0)),
        )
        inventory = (equipped,)
        if weapon.ammo_id:
            inventory += (item(2, weapon.ammo_id, 100),)
        field = BattleField(32, 32, (
            BattleActor(1, 7, 1, 1, 100, 60000, 60000, sight_radius=30),
            BattleActor(2, 8, 1 + distance, 1, 100, 60000, 60000),
        ), step_cost=1)
        combat = Combat(field, self.catalog,
                        rng=CriticalRandom() if critical else
                        HighDamageRandom() if high else FixedRandom())
        packet = self.profiles[level]
        if identity in (335, 336, 341):
            packet = change(packet, {'0x8c446f': 6})
        combat.register(1, encode_item_list(1, inventory), human=True,
                        pet_packet=packet)
        if armored:
            armor = replace(item(3, 248, equipped=True), location_raw=4)
            combat.register(2, encode_item_list(2, (armor,)), human=True,
                            pet_packet=self.profiles[16])
        replies = combat.attack(7, AttackRequest(1, 1 + distance, 1))
        result = decode_attack_result(next(p for p in replies if p[0] == 0x4b))
        hit, = (hit for hit in result.hits if hit.actor_id == 2)
        actual = 60000 - field.actor(2).health
        self.assertEqual(hit.damage, actual)
        self.assertEqual(hit.left_hp, field.actor(2).health)
        return actual

    def expected_damage(self, identity, enhancement, *, high=False,
                        distance=None, armored=False):
        bonus = enhancement if enhancement <= 2 else 2 * enhancement - 2
        weapon = self.catalog.weapons[identity]
        distance = distance or max(1, weapon.min_range)
        low, upper = self.catalog.distance_damage(identity, distance, bonus)
        damage = int((upper if high else low) * 102 / 120)
        return max(1, damage * 100 // 180) if armored else damage

    def test_all_weapons_all_levels_both_damage_endpoints(self):
        self.assertEqual(len(self.weapons), 32)
        for identity in self.firing_weapons:
            for high in (False, True):
                for enhancement in range(26):
                    with self.subTest(weapon=identity, upgrade=enhancement, high=high):
                        self.assertEqual(
                            self.attack_damage(identity, enhancement, high=high),
                            self.expected_damage(identity, enhancement, high=high),
                        )

    def test_all_weapons_all_levels_respect_mercenary_caps(self):
        for identity in self.firing_weapons:
            for level, cap in ((1, 3), (4, 10), (7, 15), (11, 20)):
                for enhancement in range(26):
                    with self.subTest(weapon=identity, level=level, upgrade=enhancement):
                        self.assertEqual(
                            self.attack_damage(identity, enhancement, level=level),
                            self.expected_damage(identity, min(enhancement, cap)),
                        )

    def test_enhancement_precedes_distance_skill_and_armor(self):
        for identity in (304, 306, 312, 315, 326):
            distance = self.catalog.weapons[identity].max_range
            for enhancement in range(26):
                for high in (False, True):
                    with self.subTest(weapon=identity, upgrade=enhancement, high=high):
                        self.assertEqual(
                            self.attack_damage(identity, enhancement, distance=distance,
                                               armored=True, high=high),
                            self.expected_damage(identity, enhancement, distance=distance,
                                                 armored=True, high=high),
                        )

    def test_displayed_upgrade_cannot_increase_actual_damage(self):
        for identity in self.firing_weapons:
            with self.subTest(weapon=identity):
                self.assertEqual(self.attack_damage(identity, 0, displayed=25),
                                 self.expected_damage(identity, 0))

    def test_critical_hit_includes_enhancement(self):
        for enhancement in range(26):
            with self.subTest(upgrade=enhancement):
                self.assertEqual(self.attack_damage(306, enhancement, critical=True),
                                 2 * self.expected_damage(306, enhancement))

    def test_groza_upgrade_does_not_increase_underbarrel_grenade_damage(self):
        from test_weapon_effects import WeaponEffectsTests
        from tio.protocol.ability_cast import AbilityCast
        damages = []
        for enhancement in range(26):
            field, combat = WeaponEffectsTests().setup_effect(339, 340, 2)
            owner, items, unknown = decode_item_list(combat.inventories[1])
            items = (replace(items[0], unknown_bytes_03=bytes((enhancement, 0, 0))),
                     *items[1:])
            combat.register(1, encode_item_list(owner, items, unknown), human=True,
                            pet_packet=self.profiles[16])
            before = field.actor(2).health
            combat.cast_subgrenade(7, AbilityCast(27, 1, 0, 6, 1))
            damages.append(before - field.actor(2).health)
        self.assertGreater(damages[0], 0)
        self.assertEqual(damages, [damages[0]] * 26)

    @unittest.expectedFailure
    def test_perforator_enhancement_blocked_by_missing_ammunition_rule(self):
        self.assertEqual(self.attack_damage(322, 25),
                         self.expected_damage(322, 25))


if __name__ == '__main__':
    unittest.main()
