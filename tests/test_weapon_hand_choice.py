"""An untargeted bag click on a weapon fills a free hand, primary first."""
from contextlib import closing
import sqlite3
import unittest

from tio.equipment import equip_primary_weapon
from tio.protocol.item_action import ItemAction, encode_item_action
from tio.protocol.item_list import decode_item_list, encode_item_list

import test_equipment_batch as batch_tests

gear = batch_tests.gear


def hands(packet):
    return {i.client_slot: i.template_id for i in decode_item_list(packet)[1]
            if i.equipped and i.client_slot in (16, 128)}


class WeaponHandChoiceTests(unittest.TestCase):
    # Actor 1 holds weapon 301 in the primary hand; grenade 317 (id 102) is in the bag.
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

    def test_battle_preview_fills_free_secondary_hand(self):
        replies = self.stage(1, 102, 255)
        self.assertEqual(hands(replies[0]), {16: 301, 128: 317})

    def test_battle_direct_equip_fills_free_secondary_hand(self):
        self.combat.equip(10, ItemAction(1, 102, 255))
        self.assertEqual(hands(self.combat.inventories[1]), {16: 301, 128: 317})

    def test_city_equip_fills_free_secondary_hand(self):
        inventory = equip_primary_weapon(self.path, 'alice', encode_item_action(ItemAction(1, 102, 255)))
        self.assertEqual(hands(inventory), {16: 301, 128: 317})

    def test_empty_hands_take_primary_first(self):
        self.give(gear(101, 301), drop=(101,))
        self.assertEqual(hands(self.stage(1, 102, 255)[0]), {16: 317})

    def test_both_hands_full_replace_primary(self):
        self.give(gear(107, 302, 128))
        self.assertEqual(hands(self.stage(1, 102, 255)[0]), {16: 317, 128: 302})

    def test_battle_preview_drag_between_full_hands_swaps(self):
        self.give(gear(107, 302, 128))
        self.assertEqual(hands(self.stage(1, 101, 7)[0]), {16: 302, 128: 301})
        self.assertEqual(hands(self.stage(1, 101, 4)[0]), {16: 301, 128: 302})

    def test_battle_direct_drag_between_full_hands_swaps(self):
        self.give(gear(107, 302, 128))
        self.combat.equip(10, ItemAction(1, 107, 4))
        self.assertEqual(hands(self.combat.inventories[1]), {16: 302, 128: 301})

    def test_city_drag_between_full_hands_swaps(self):
        self.give(gear(107, 302, 128))
        inventory = equip_primary_weapon(self.path, 'alice', encode_item_action(ItemAction(1, 101, 7)))
        self.assertEqual(hands(inventory), {16: 302, 128: 301})

    def test_freshly_staged_weapon_dragged_onto_other_hand_swaps(self):
        # Reported: AWP put from the bag into the primary hand in the same
        # window, then dragged onto Groza in the secondary hand.
        self.give(gear(107, 302, 128))
        self.stage(1, 102, 4)
        self.assertEqual(hands(self.stage(1, 102, 7)[0]), {16: 302, 128: 317})
        self.commit()
        self.assertEqual(hands(self.combat.inventories[1]), {16: 302, 128: 317})

    def test_bag_weapon_onto_full_hand_still_returns_old_one_to_bag(self):
        self.give(gear(107, 302, 128))
        self.assertEqual(hands(self.stage(1, 102, 7)[0]), {16: 301, 128: 317})

    def test_explicit_target_still_wins(self):
        self.assertEqual(hands(self.stage(1, 102, 4)[0]), {16: 317})


if __name__ == '__main__':
    unittest.main()
