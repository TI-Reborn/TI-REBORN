"""Exhaust the per-projectile accuracy threshold through attacks and packets."""
from dataclasses import replace
import unittest

from test_combat import item
from test_weapon_proficiency import change, profile
from tio.battle_state import BattleActor, BattleField
from tio.combat import Combat
from tio.protocol.battle_attack import AttackRequest, RESULT_MISS, decode_attack_result
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.weapon_proficiency import BASE, NAMES, SAVED, bits
from tio.weapons import WeaponCatalog


class HitRoll:
    def __init__(self, roll):
        self.roll, self.calls = roll, 0
        self.critical = False

    def randrange(self, stop):
        self.calls += 1
        roll = stop - 1 if self.critical else self.roll
        self.critical = False
        return roll

    def randint(self, low, high):
        self.critical = True
        return low


class RifleAccuracyTests(unittest.TestCase):
    def test_all_rolls_distances_upgrades_and_skills_match_hp_and_packet(self):
        catalog = WeaponCatalog()
        base = profile(14)
        for weapon_id, chances in ((330, (95, 95, 95, 94, 92, 90, 88, 87, 85)),
                                   (311, (80,) * 14)):
            weapon = catalog.weapons[weapon_id]
            skill_index = NAMES.index(weapon.weapon_type)
            for skill in (35, 140):
                pet = change(base, {SAVED[skill_index]: bits(skill),
                                    BASE[skill_index]: bits(skill)})
                for upgrade in (0, 20):
                    equipped = replace(item(1, weapon_id, equipped=True),
                                       unknown_bytes_03=bytes((upgrade, 0, 0)))
                    inventory = encode_item_list(1, (equipped, item(2, 5, 100)))
                    for distance, chance in enumerate(chances, 1):
                        hits = 0
                        for roll in range(100):
                            with self.subTest(weapon=weapon_id, skill=skill,
                                              upgrade=upgrade, distance=distance, roll=roll):
                                field = BattleField(32, 32, (
                                    BattleActor(1, 7, 1, 1, 100, 1000, 1000, sight_radius=30),
                                    BattleActor(2, 8, 1 + distance, 1, 100, 1000, 1000),
                                ), step_cost=1)
                                rng = HitRoll(roll)
                                combat = Combat(field, catalog, rng=rng)
                                combat.register(1, inventory, human=True, pet_packet=pet)
                                combat.npc_defense = {2: 200}
                                result = decode_attack_result(combat.attack(
                                    7, AttackRequest(1, 1 + distance, 1))[0])
                                target, = result.hits
                                landed = roll < chance
                                self.assertEqual(field.actor(2).health < 1000, landed)
                                self.assertEqual(result.flags == RESULT_MISS, not landed)
                                self.assertEqual(target.flags == RESULT_MISS, not landed)
                                self.assertEqual(target.damage, 1000 - field.actor(2).health)
                                self.assertEqual(target.left_hp, field.actor(2).health)
                                self.assertEqual(rng.calls, weapon.bullets_count * (2 if landed else 1))
                                self.assertEqual(field.actor(1).action_points,
                                                 100 - weapon.attack_ap)
                                self.assertEqual(decode_item_list(
                                    combat.inventories[1])[1][1].count,
                                    100 - weapon.bullets_count)
                                hits += landed
                        self.assertEqual(hits, chance)


if __name__ == '__main__':
    unittest.main()
