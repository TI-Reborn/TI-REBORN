"""Suicide Jacket excludes every hand weapon (manual p64), in every route."""
from contextlib import closing
import sqlite3
import unittest

from tio.equipment_batch import EquipmentBatchRejected
from tio.protocol.item_action import ItemAction
from tio.protocol.item_list import decode_item_list, encode_item_list

import test_equipment_batch as batch_tests

gear = batch_tests.gear

JACKET = 150


class SuicideJacketEquipmentTests(unittest.TestCase):
    setUp = batch_tests.EquipmentBatchTests.setUp
    stage = batch_tests.EquipmentBatchTests.stage
    commit = batch_tests.EquipmentBatchTests.commit

    def give(self, *records, drop=()):
        _, items, flag = decode_item_list(self.combat.inventories[1])
        items = tuple(i for i in items if i.instance_id not in drop) + records
        packet = encode_item_list(1, items, flag)
        self.combat.inventories[1] = packet
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='alice' AND pet_id=1", (packet,))

    def hands(self):
        return {i.client_slot: i.template_id for i in decode_item_list(self.combat.inventories[1])[1]
                if i.equipped and i.client_slot in (16, 128)}

    def test_jacket_rejected_while_weapon_only_in_secondary_hand(self):
        self.give(gear(JACKET, 334), gear(101, 301, 128), drop=(101,))
        with self.assertRaisesRegex(EquipmentBatchRejected, 'оружие'):
            self.stage(1, JACKET, 2)

    def test_secondary_weapon_rejected_while_jacket_worn(self):
        self.give(gear(JACKET, 334, 4), gear(101, 301), drop=(101,))
        with self.assertRaisesRegex(EquipmentBatchRejected, 'оружие'):
            self.stage(1, 101, 7)
        with self.assertRaisesRegex(ValueError, 'оружие'):
            self.combat.equip(10, ItemAction(1, 102, 7))
        self.assertEqual(self.hands(), {})

    def test_hand_swap_cannot_arm_a_jacket_wearer(self):
        # Saves made before this rule may still hold a secondary weapon.
        self.give(gear(JACKET, 334, 4), gear(101, 301, 128), drop=(101,))
        before = self.combat.inventories[1]
        with self.assertRaisesRegex(ValueError, 'оружие'):
            self.combat.swap_weapons(10, 1)
        self.assertEqual(self.combat.inventories[1], before)
        self.assertEqual(self.field.actor(1).action_points, 15)

    def test_removing_the_weapon_or_jacket_stays_allowed(self):
        self.give(gear(JACKET, 334, 4), gear(101, 301, 128), drop=(101,))
        self.stage(1, 101, 255)
        self.commit()
        self.assertEqual(self.hands(), {})

    def test_jacket_and_weapon_are_fine_without_each_other(self):
        self.give(gear(JACKET, 334))
        self.stage(1, 101, 255)
        self.stage(1, JACKET, 2)
        self.commit()
        equipped = {i.client_slot: i.template_id for i in decode_item_list(self.combat.inventories[1])[1] if i.equipped}
        self.assertEqual(equipped, {4: 334})


if __name__ == '__main__':
    unittest.main()
