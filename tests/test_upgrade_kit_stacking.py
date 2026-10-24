"""Upgrade Kits occupy one warehouse/backpack cell per location as one stack."""
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tio.db_transaction import transaction
from tio.enhancement import EnhancementStore
from tio.item_stacking import STACKABLE, compact_saved_items, merge_stacks
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from tio.protocol.shop_purchase import ShopPurchase
from tio.protocol.shop_sale import ShopSale
from tio.protocol.warehouse import decode_warehouse_list
from tio.protocol.warehouse_transfer import WarehouseTransfer, encode_warehouse_transfer
from tio.city_catalogs import CityCatalogs
from tio.shop import ShopStore
from tio.warehouse import WarehouseStore
from tio.warehouse_resources import counts
from tio.warehouse_service import transfer_private_items
from tio.warehouse_completion import schema
from wallet_fixture import fund_wallet

ROOT = Path(__file__).resolve().parents[1]
KIT = 30


def kit(identity, count=1, **fields):
    return replace(ItemRecord(identity, KIT, bytes(2), count, 0, 0, (1, 1, 1),
                              bytes(4), None, bytes(3)), **fields)


def weapon(identity, level=0):
    return ItemRecord(identity, 301, bytes(2), 1, 0, 0, (300+65*level,)*3,
                      bytes((level, 0, 0, 0)), None, bytes((level, 0, 0)))


class UpgradeKitStackingTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'kits.db'
        self.pet = bytes.fromhex(json.loads((ROOT / 'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        self.pets = OwnedPetStore(self.path)
        for account in ('alice', 'bob'):
            self.pets.ensure(account, self.pet, encode_item_list(1, ()), human=True)
            fund_wallet(self.path, account, credits=100_000, gold=0)
        self.warehouse = WarehouseStore(self.path)
        with transaction(self.path) as db:
            schema(db)
            db.execute('CREATE TABLE character_locations(account TEXT PRIMARY KEY,town_id INTEGER NOT NULL)')
            db.executemany('INSERT INTO character_locations VALUES (?,3)', (('alice',), ('bob',)))

    def seed(self, account='alice', inventory=(), warehouse=(), bucket='city'):
        """Hosted rows carry a city placement; bucket=None seeds an untagged legacy row."""
        with transaction(self.path) as db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',
                       (encode_item_list(1, inventory), account))
            for i in warehouse:
                db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',
                           (account, i.instance_id, encode_item_list(0, (i,))))
                if bucket is not None:
                    db.execute('INSERT INTO warehouse_places VALUES (?,?,?,?,?)',
                               (account, i.instance_id, bucket, 3, 'player-deposit'))

    def inventory(self, account='alice'):
        return decode_item_list(self.pets.inventory(account, 1))[1]

    def test_policy_and_client_catalog_mark_upgrade_kit_stackable(self):
        self.assertIn(KIT, STACKABLE)
        node = next(n for n in ET.parse(ROOT / 'evidence/items_diagnostic.xml').getroot() if n.get('id') == str(KIT))
        self.assertEqual({v.get('key'): v.get('val') for v in node.findall('value')}.get('stackable'), '1')

    def test_identical_kits_merge_but_repair_kits_and_marked_kits_stay_separate(self):
        self.assertEqual(merge_stacks((kit(1), kit(2), kit(3))), (kit(1, 3),))
        repair = tuple(replace(kit(i), template_id=17) for i in (4, 5))
        self.assertEqual(merge_stacks(repair), repair)
        marked = kit(6, unknown_bytes_02=b'\0\0\x01\0')
        self.assertEqual(merge_stacks((kit(1), marked)), (kit(1), marked))

    def test_login_compaction_turns_five_saved_kits_into_one_cell_per_account(self):
        # Screenshot case: five separate kits on the personal warehouse.
        self.seed(warehouse=[kit(i) for i in range(101, 106)])
        self.seed('bob', warehouse=[kit(201), kit(202)])
        self.assertEqual(counts(sqlite3.connect(self.path), 'alice')[1], 5)
        self.assertEqual(compact_saved_items(self.path, 'alice'), {'inventories': 0, 'warehouse': True})
        self.assertEqual(self.warehouse.items('alice'), (kit(101, 5),))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(counts(db, 'alice')[1], 5)
        self.assertEqual(self.warehouse.items('bob'), (kit(201), kit(202)))
        self.assertEqual(compact_saved_items(self.path, 'alice'), {'inventories': 0, 'warehouse': False})

    def test_untagged_legacy_rows_keep_their_existing_no_merge_policy(self):
        self.seed(warehouse=[kit(101), kit(102)], bucket=None)
        self.assertEqual(compact_saved_items(self.path, 'alice'), {'inventories': 0, 'warehouse': False})
        self.assertEqual(self.warehouse.items('alice'), (kit(101), kit(102)))

    def test_backpack_kits_merge_at_login(self):
        self.seed(inventory=(kit(11), weapon(12), kit(13)))
        self.assertEqual(compact_saved_items(self.path, 'alice'), {'inventories': 1, 'warehouse': False})
        self.assertEqual(self.inventory(), (kit(11, 2), weapon(12)))

    def test_partial_withdrawal_and_return_keep_one_cell_on_each_side(self):
        self.seed(warehouse=[kit(101, 5)])

        def transfer(deposits=(), withdrawals=()):
            return transfer_private_items(self.path, 'alice', encode_warehouse_transfer(
                WarehouseTransfer(0, 1, deposits, withdrawals)), capacity=1)
        replies = transfer(withdrawals=((101, 2),))
        self.assertEqual([(i.template_id, i.count) for i in decode_item_list(replies[0])[1]], [(KIT, 2)])
        self.assertEqual([(i.instance_id, i.count) for i in decode_warehouse_list(replies[1])[3]], [(101, 3)])
        withdrawn = decode_item_list(replies[0])[1][0].instance_id
        replies = transfer(((withdrawn, 2),))
        self.assertEqual(decode_item_list(replies[0])[1], ())
        self.assertEqual(self.warehouse.items('alice'), (kit(101, 5),))

    def test_shop_purchase_adds_to_existing_stack_and_sale_takes_single_units(self):
        shop = ShopStore(self.path, CityCatalogs(ROOT / 'config/city_catalogs.json'))
        category, offer = next((c, o) for c, group in shop.catalogs.items.items()
                               for o in group if o.item_id == KIT)
        self.seed(inventory=(kit(70, 2),))
        result = shop.purchase('alice', ShopPurchase(1, category, offer.unknown_u32_01, 3))
        goods = [i for i in decode_item_list(result.inventory)[1] if i.template_id == KIT]
        self.assertEqual([(i.instance_id, i.count) for i in goods], [(70, 5)])
        quote_one = shop.sell('alice', ShopSale(1, 70, 1), quote=True)
        self.assertGreater(quote_one, 0)
        # Proportional gross; the sales tax rounds the net of each request.
        self.assertLessEqual(abs(shop.sell('alice', ShopSale(1, 70, 2), quote=True) - 2*quote_one), 1)
        result = shop.sell('alice', ShopSale(1, 70, 1))
        self.assertEqual([(i.instance_id, i.count) for i in decode_item_list(result.inventory)[1]], [(70, 4)])

    def test_enhancement_consumes_one_kit_from_the_stack(self):
        self.seed(inventory=(weapon(1001), kit(1002, 3)))
        result = EnhancementStore(self.path, randbelow=lambda n: 0).handle(
            'alice', b'\xc8\x2a' + struct.pack('<IBI', 1001, 1, 1002))
        self.assertEqual(result.outcome, 'success')
        self.assertEqual([(i.instance_id, i.count) for i in self.inventory() if i.template_id == KIT], [(1002, 2)])
        self.assertEqual(self.inventory('bob'), ())


if __name__ == '__main__':
    unittest.main()
