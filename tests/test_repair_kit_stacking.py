"""Repair Kits 17/18/19 stack when identical; partial use splits one kit off."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from test_durability import gear, request
import test_warehouse_resources as fixture
from test_warehouse_resources import ROOT, item
from tio.db_transaction import transaction
from tio.durability import KITS
from tio.item_stacking import STACKABLE, compact_saved_items, merge_stacks
from tio.inventory_capacity import INVENTORY_SLOTS
from tio.protocol.item_action import ItemAction, encode_item_action
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.repair import repair, select_kit
from tio.warehouse_resources import counts


def kit(identity, template=17, count=1, resource=None):
    full = KITS[template]
    return item(identity, template, quantity=count, resource=full if resource is None else resource, capacity=full)


def cells(items):
    return [(i.instance_id, i.template_id, i.count, i.unknown_words[0]) for i in items]


class RepairKitStackingTests(unittest.TestCase):
    setUp = fixture.WarehouseResourcesTests.setUp
    stash = fixture.WarehouseResourcesTests.stash
    assets = fixture.WarehouseResourcesTests.assets

    def bag(self, *extra, owner='alice'):
        damaged = replace(item(9001, 301, resource=50, capacity=350), unknown_u8_01=1, location_raw=16)
        with transaction(self.path) as db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',
                       (encode_item_list(1, (damaged, *extra)), owner))

    def backpack(self, owner='alice'):
        with closing(sqlite3.connect(self.path)) as db:
            return decode_item_list(db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',
                                               (owner,)).fetchone()[0])[1]

    def quick_repair(self, owner='alice'):
        return repair(self.path, owner, b'\xc2\x03' + struct.pack('<II', 1, 9001))

    def test_policy_and_client_catalog_mark_all_three_kits_stackable(self):
        nodes = {n.get('id'): n for n in ET.parse(ROOT / 'evidence/items_diagnostic.xml').getroot()}
        for template in (17, 18, 19):
            self.assertIn(template, STACKABLE)
            values = {v.get('key'): v.get('val') for v in nodes[str(template)].findall('value')}
            self.assertEqual(values.get('stackable'), '1')

    def test_only_kits_with_equal_remaining_resource_and_template_merge(self):
        self.assertEqual(cells(merge_stacks((kit(1), kit(2), kit(3)))), [(1, 17, 3, 600)])
        mixed = (kit(1), kit(2, resource=309), kit(3, 18), kit(4, 19))
        self.assertEqual(merge_stacks(mixed), mixed)

    def test_login_compaction_puts_full_kits_in_one_cell_and_keeps_points(self):
        self.stash([kit(1), kit(2), kit(3), kit(4, resource=37), kit(5, 19), kit(6, 19)], town=3)
        self.stash([kit(1), kit(2)], 'bob', town=3)
        before = self.assets().repair_points
        self.assertEqual(compact_saved_items(self.path, 'alice')['warehouse'], True)
        self.assertEqual(cells(self.store.items('alice')), [(1, 17, 3, 600), (4, 17, 1, 37), (5, 19, 2, 3600)])
        self.assertEqual(self.assets().repair_points, before)
        self.assertEqual(cells(self.store.items('bob')), [(1, 17, 1, 600), (2, 17, 1, 600)])

    def test_warehouse_repair_spends_partial_kit_first_and_keeps_at_most_one_remainder(self):
        self.bag()
        self.stash([kit(1, count=3), kit(5, resource=100)], town=3)
        self.quick_repair()  # 291 points: the 100-point kit, then 191 split off the stack.
        stock = self.store.items('alice')
        self.assertEqual([(i.count, i.unknown_words[0]) for i in stock], [(2, 600), (1, 409)])
        self.assertEqual(self.assets().repair_points, 1900 - 291)
        self.bag()
        self.quick_repair()  # The remainder is spent before the stack is touched again.
        self.assertEqual([(i.instance_id, i.count, i.unknown_words[0]) for i in self.store.items('alice')],
                         [(1, 2, 600), (stock[1].instance_id, 1, 118)])

    def test_backpack_repair_splits_one_kit_off_a_stack_with_a_fresh_reserved_id(self):
        self.bag(kit(5, count=3))
        self.stash([item(9500, 301)], town=3)  # Highest existing ID lives on the warehouse.
        with transaction(self.path) as db:
            db.execute('DELETE FROM warehouse_items WHERE account=?', ('alice',))
            db.execute('CREATE TABLE IF NOT EXISTS item_sequences (account TEXT PRIMARY KEY,next_id INTEGER NOT NULL)')
            db.execute('INSERT INTO item_sequences VALUES (?,?)', ('alice', 9600))
        self.quick_repair()
        kits = [i for i in self.backpack() if i.template_id == 17]
        self.assertEqual(cells(kits), [(5, 17, 2, 600), (9600, 17, 1, 309)])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT next_id FROM item_sequences WHERE account=?', ('alice',)).fetchone()[0], 9601)
            self.assertEqual(db.execute('SELECT kit_id,spent FROM item_repairs').fetchall(), [(5, 291)])
        self.bag(*kits)
        self.quick_repair()  # The split remainder is spent first.
        self.assertEqual(cells(i for i in self.backpack() if i.template_id == 17), [(5, 17, 2, 600), (9600, 17, 1, 18)])

    def test_selected_stacked_kit_repairs_and_other_account_is_untouched(self):
        self.bag(kit(5, count=2))
        self.bag(kit(5, count=2), owner='bob')
        bob = self.backpack('bob')
        selection = select_kit(self.path, 'alice', encode_item_action(ItemAction(1, 5, 255)))
        self.assertEqual(selection, (1, 5))
        repair(self.path, 'alice', b'\x7e' + struct.pack('<II', 1, 9001), selection)
        self.assertEqual([(i.count, i.unknown_words[0]) for i in self.backpack() if i.template_id == 17], [(1, 600), (1, 309)])
        self.assertEqual(self.backpack('bob'), bob)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(counts(db, 'alice')[0], 0)

    def test_battle_repair_splits_stack_using_the_match_id_allocator(self):
        from test_durability import DurabilityTests
        field, combat = DurabilityTests().scene()
        field.loot = SimpleNamespace(next_id=0x60000005)
        stacked = replace(kit(101, count=2), unknown_words=(600, 600, 600))
        combat.inventories[1] = encode_item_list(1, (gear(), stacked))
        combat.repair_selections[7] = (1, 101)
        combat.repair(7, request(selected=True))
        kits = [i for i in decode_item_list(combat.inventories[1])[1] if i.template_id == 17]
        self.assertEqual(cells(kits), [(101, 17, 1, 600), (0x60000005, 17, 1, 309)])
        self.assertEqual(field.loot.next_id, 0x60000006)

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as db:
            return tuple(db.iterdump())

    def test_full_city_bag_rejects_split_without_changing_either_account(self):
        fillers = tuple(item(100 + i, 317) for i in range(INVENTORY_SLOTS - 2))
        self.bag(kit(5, count=2), *fillers)
        self.bag(kit(5, count=2), owner='bob')
        with transaction(self.path) as db:
            db.execute('INSERT INTO item_sequences VALUES (?,?)', ('alice', 9600))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Inventory is full'):
            self.quick_repair()
        self.assertEqual(self.snapshot(), before)

    def test_one_free_city_slot_accepts_split(self):
        fillers = tuple(item(100 + i, 317) for i in range(INVENTORY_SLOTS - 3))
        self.bag(kit(5, count=2), *fillers)
        self.quick_repair()
        self.assertEqual(len(self.backpack()), INVENTORY_SLOTS)

    def test_full_city_bag_accepts_fully_spent_unit_without_split(self):
        fillers = tuple(item(100 + i, 317) for i in range(INVENTORY_SLOTS - 2))
        self.bag(kit(5, count=2, resource=291), *fillers)
        self.quick_repair()
        after = self.backpack()
        self.assertEqual(len(after), INVENTORY_SLOTS)
        self.assertEqual(next(i.count for i in after if i.instance_id == 5), 1)

    def test_legacy_oversized_city_bag_cannot_grow(self):
        fillers = tuple(item(100 + i, 317) for i in range(INVENTORY_SLOTS - 1))
        self.bag(kit(5, count=2), *fillers)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Inventory is full'):
            self.quick_repair()
        self.assertEqual(self.snapshot(), before)
        self.bag(kit(5, count=2, resource=291), *fillers)
        self.quick_repair()
        self.assertEqual(len(self.backpack()), INVENTORY_SLOTS + 1)

    def persisted_battle(self, occupied=INVENTORY_SLOTS):
        from test_durability import DurabilityTests
        field, combat = DurabilityTests().scene()
        field.loot = SimpleNamespace(next_id=0x60000005)
        fillers = tuple(item(1000 + i, 317) for i in range(occupied - 2))
        inventory = encode_item_list(1, (gear(), kit(101, count=2), *fillers))
        combat.inventories[1] = inventory
        combat.persistence[1] = (self.path, 'alice')
        combat.repair_selections[7] = (1, 101)
        with transaction(self.path) as db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',
                       (inventory, 'alice'))
            db.execute('INSERT INTO item_sequences VALUES (?,?)', ('alice', field.loot.next_id))
        return field, combat

    def test_full_battle_bag_rejects_split_without_spending_or_allocating(self):
        field, combat = self.persisted_battle()
        before = self.snapshot()
        inventory = combat.inventories[1]
        actor = field.actor(1)
        with self.assertRaisesRegex(ValueError, 'Inventory is full'):
            combat.repair(7, request(selected=True))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(combat.inventories[1], inventory)
        self.assertEqual(field.actor(1), actor)
        self.assertEqual(field.loot.next_id, 0x60000005)
        self.assertEqual(combat.repair_selections[7], (1, 101))

    def test_battle_split_persists_and_reserves_the_new_id(self):
        field, combat = self.persisted_battle(INVENTORY_SLOTS - 1)
        combat.repair(7, request(selected=True))
        self.assertEqual(len(self.backpack()), INVENTORY_SLOTS)
        self.assertEqual(encode_item_list(1, self.backpack()), combat.inventories[1])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT next_id FROM item_sequences WHERE account=?',
                                        ('alice',)).fetchone()[0], 0x60000006)
        self.assertEqual(field.loot.next_id, 0x60000006)

    def test_battle_split_database_failure_preserves_inventory_ap_and_ids(self):
        field, combat = self.persisted_battle(INVENTORY_SLOTS - 1)
        before = self.snapshot()
        inventory = combat.inventories[1]
        actor = field.actor(1)
        with patch('tio.repair.record', side_effect=sqlite3.OperationalError('write failed')):
            with self.assertRaises(sqlite3.OperationalError):
                combat.repair(7, request(selected=True))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(combat.inventories[1], inventory)
        self.assertEqual(field.actor(1), actor)
        self.assertEqual(field.loot.next_id, 0x60000005)


if __name__ == '__main__':
    unittest.main()
