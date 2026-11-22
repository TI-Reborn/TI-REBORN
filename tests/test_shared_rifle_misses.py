"""Accepted misses advance RNG through the shared hub and durable checkpoint."""
from contextlib import closing
from dataclasses import replace
import random
import sqlite3
import unittest

import test_shared_mine_arena as fixtures
from test_combat import item
from tio.combat_rolls import burst
from tio.protocol.battle_attack import (
    AttackRequest, RESULT_MISS, decode_attack_result, encode_attack_request,
)
from tio.protocol.item_list import encode_item_list
from tio.weapon_proficiency import damage_endpoint
from tio.weapons import WeaponCatalog


class SharedRifleMissTests(unittest.TestCase):
    def test_full_miss_then_hit_are_committed_without_repeating_random_state(self):
        for weapon_id in (330, 311):
            with self.subTest(weapon=weapon_id):
                f = fixtures.SharedMineArenaTests()
                f.setUp()
                try:
                    session = f.case.sessions[0]
                    with closing(sqlite3.connect(f.path)) as db, db:
                        pet_id, = db.execute('SELECT pet_id FROM owned_pets WHERE account=?',
                                             (session.account,)).fetchone()
                        inventory = encode_item_list(pet_id, (
                            item(1001, weapon_id, equipped=True), item(1002, 5, 100)))
                        db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                                   (inventory, session.account, pet_id))
                    catalog = WeaponCatalog()
                    rounds = catalog.weapons[weapon_id].bullets_count
                    distance = 9
                    accuracy = catalog.accuracy(weapon_id, distance)
                    low, high = (damage_endpoint(n, 35)
                                 for n in catalog.distance_damage(weapon_id, distance))
                    critical = int(catalog.sources[weapon_id]['critical'])
                    for seed in range(10000):
                        probe = random.Random(seed)
                        if [burst(probe, low, high, accuracy, rounds, critical)[1]
                                for _ in range(2)] == [False, True]:
                            break
                    else:
                        self.fail('No deterministic miss/hit fixture found')
                    battle = f.enter((0, 1))
                    field, owner = battle['field'], f.owners[0]
                    actor, = field.actor_ids(owner)
                    target = field.actor_ids(next(iter(battle['bots'])))[0]
                    with f.hub.journal.unit(battle):
                        f.park_mutants(battle)
                        field._actors[actor] = replace(field.actor(actor), x=10, y=10,
                                                       action_points=100, sight_radius=30)
                        field._actors[target] = replace(field.actor(target), x=10 + distance, y=10)
                        field.combat.rng = random.Random(seed)
                        battle['views'][owner].refresh()
                    oracle = random.Random(seed)
                    for expected_hit in (False, True):
                        before = field.combat.rng.getstate()
                        replies = f.send(0, encode_attack_request(AttackRequest(actor, 10 + distance, 10)))
                        packet, = (p for p in replies if p[0] == 0x4b)
                        result = decode_attack_result(packet)
                        self.assertEqual(result.flags == RESULT_MISS, not expected_hit)
                        self.assertNotEqual(field.combat.rng.getstate(), before)
                        burst(oracle, low, high, accuracy, rounds, critical)
                        self.assertEqual(field.combat.rng.getstate(), oracle.getstate())
                        recovered = f.restore().battles[owner]['field'].combat.rng
                        self.assertEqual(recovered.getstate(), oracle.getstate())
                finally:
                    f.doCleanups()


if __name__ == '__main__':
    unittest.main()
