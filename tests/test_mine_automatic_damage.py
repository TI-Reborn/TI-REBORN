"""AK-47 upgrades/proficiency through shared mine admission and actual attacks."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import unittest

from test_combat import item
import test_shared_mining_state as shared_fixture
from tio.matchmaking import SurvivalQueue
from tio.owned_pets import OwnedPetStore
from tio.protocol.battle_attack import AttackRequest, decode_attack_result
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.weapon_proficiency import BASE, NAMES, SAVED, bits
from tio.weapons import WeaponCatalog


class AttackRandom:
    def __init__(self, hits=(True,) * 5, high=False, critical=False):
        self.rolls = (roll for hit in hits
                      for roll in ((0, 0 if critical else 99) if hit else (99,)))
        self.high = high

    def randrange(self, stop):
        return next(self.rolls)

    def randint(self, low, high):
        return high if self.high else low


class MineAutomaticDamageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = shared_fixture.SharedMiningStateTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def prepare(self, *, skill=145, level=15, upgrade=20, weapon_id=304):
        fixture = self.fixture
        stats = WeaponCatalog().weapons[weapon_id]
        skill_index = NAMES.index(stats.weapon_type)
        with closing(sqlite3.connect(fixture.path)) as db, db:
            rows = db.execute('SELECT account,pet_id,pet_packet FROM owned_pets').fetchall()
            for account, identity, packet in rows:
                pet = decode_pet_info(packet, human_equipment=True)
                pet = replace(pet, fields={**pet.fields, '0x8c4aef': level,
                                           SAVED[skill_index]: bits(skill),
                                           BASE[skill_index]: bits(skill)})
                weapon = replace(item(1001, weapon_id, equipped=True),
                                 unknown_bytes_03=bytes((upgrade, 0, 0)))
                inventory = encode_item_list(identity, (weapon, item(1002, stats.ammo_id, 100)))
                db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? '
                           'WHERE account=? AND pet_id=?',
                           (encode_pet_info(pet), inventory, account, identity))
        store = OwnedPetStore(fixture.path)
        fixture.tickets = tuple(SurvivalQueue().join(owner, store.list(account))
                                for account, owner in zip(fixture.accounts, fixture.owners))
        return fixture.prepare((0, 1))

    def shoot(self, scene, *, owner=42, distance=1, hits=(True,) * 5,
              high=False, critical=False):
        field = scene.field
        combat = field.combat
        actor, = field.actor_ids(owner)
        target = field.actor_ids(scene.bot_owner)[0]
        field.blocked = frozenset()
        field.transparent_obstacles = frozenset()
        field._actors[actor] = replace(field.actor(actor), x=10, y=10,
                                       sight_radius=20, action_points=100)
        field._actors[target] = replace(field.actor(target), x=10 + distance, y=10)
        self.assertEqual(combat.defense(target), 200)
        self.assertEqual(combat.enhancement_caps[actor], 20)
        before = field.actor(target).health
        combat.rng = AttackRandom(hits, high, critical)
        result = decode_attack_result(combat.attack(owner, AttackRequest(actor, 10 + distance, 10))[0])
        hit, = result.hits
        self.assertEqual(hit.damage, before - field.actor(target).health)
        self.assertEqual(hit.left_hp, field.actor(target).health)
        self.assertEqual(field.actor(actor).action_points, 95)
        self.assertEqual(sum(i.count for i in decode_item_list(combat.inventories[actor])[1]
                             if i.template_id == 7), 95)
        self.assertEqual(tuple(combat.rng.rolls), ())
        return hit.damage

    def test_max_automatic_increases_damage_for_both_shared_mine_owners(self):
        for owner in (42, 43):
            for skill, high, expected in ((35, False, 24), (35, True, 32),
                                           (145, False, 51), (145, True, 66)):
                with self.subTest(owner=owner, skill=skill, high=high):
                    scene = self.prepare(skill=skill)
                    actor, = scene.field.actor_ids(owner)
                    combat = scene.field.combat
                    self.assertEqual(combat.proficiency_rules.value(
                        combat.proficiencies[actor], True, 'Automatic'), skill)
                    self.assertEqual(self.shoot(scene, owner=owner, high=high), expected)

    def test_burst_can_land_partially_after_the_first_projectile_misses(self):
        self.assertEqual(self.shoot(self.prepare()), 51)
        self.assertEqual(self.shoot(self.prepare(), hits=(False, True, False, False, False)), 10)
        self.assertEqual(self.shoot(self.prepare(), hits=(False,) * 5), 0)

    def test_all_critical_projectiles_double_damage_before_mob_armor(self):
        self.assertEqual(self.shoot(self.prepare(), critical=True), 103)

    def test_weapon_plus20_also_increases_damage_in_actual_mine(self):
        self.assertEqual(self.shoot(self.prepare(upgrade=0)), 29)
        self.assertEqual(self.shoot(self.prepare(upgrade=20)), 51)

    def test_max_skill_at_each_mine_level_and_distance_falloff(self):
        for level, skill, expected in ((11, 125, 46), (12, 130, 48),
                                       (13, 135, 49), (14, 140, 50), (15, 145, 51)):
            with self.subTest(level=level):
                self.assertEqual(self.shoot(self.prepare(level=level, skill=skill)), expected)
        for distance, high, expected in ((4, False, 46), (4, True, 60),
                                          (9, False, 38), (9, True, 49)):
            with self.subTest(distance=distance, high=high):
                self.assertEqual(self.shoot(self.prepare(), distance=distance, high=high), expected)

    def test_global_maximum_is_capped_by_mercenary_level(self):
        scene = self.prepare(skill=200)
        actor, = scene.field.actor_ids(42)
        combat = scene.field.combat
        self.assertEqual(combat.proficiency_rules.value(combat.proficiencies[actor], True, 'Automatic'), 145)
        self.assertEqual(self.shoot(scene), 51)


if __name__ == '__main__':
    unittest.main()
