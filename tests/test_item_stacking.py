from wallet_fixture import fund_wallet
from contextlib import closing
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tio.item_stacking import STACKABLE, MAX_STACK, merge_stacks, compact_saved_items
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore, WarehouseRejected
from tio.warehouse_service import transfer_private_items
from tio.protocol.warehouse_transfer import WarehouseTransfer, encode_warehouse_transfer
from tio.protocol.warehouse import decode_warehouse_list
from tio.protocol.item_list import ItemRecord, encode_item_list, decode_item_list
from tio.protocol.shop_purchase import ShopPurchase
from tio.shop import ShopStore
from tio.sc_shop import SCShopStore
from tio.city_catalogs import CityCatalogs

ROOT = Path(__file__).resolve().parents[1]


def item(identity, template=5, count=40, **fields):
    return replace(ItemRecord(identity, template, bytes(2), count, 0, 0,
                              (1, 1, 1), bytes(4), None, bytes(3)), **fields)


class StackTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'stacks.db'
        trial = json.loads((ROOT / 'evidence/owned_pet_trial.json').read_text())
        self.pet = bytes.fromhex(trial['packet_hex'])
        self.pets = OwnedPetStore(self.path)
        self.pets.ensure('alice', self.pet, encode_item_list(1, ()), human=True)
        fund_wallet(self.path, 'alice', credits=10_000, gold=10_000)
        self.warehouse = WarehouseStore(self.path, capacity=1)
        self.shop = ShopStore(self.path, CityCatalogs(ROOT / 'config/city_catalogs.json'))

    def seed(self, inventory=(), warehouse=(), account='alice'):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',
                       (encode_item_list(1, inventory), account))
            db.executemany('INSERT INTO warehouse_items VALUES (?,?,?)',
                           ((account, i.instance_id, encode_item_list(0, (i,))) for i in warehouse))

    def buy(self, template, packs):
        offer = next(o for o in self.shop.catalogs.items[0] if o.item_id == template)
        return self.shop.purchase('alice', ShopPurchase(1, 0, offer.unknown_u32_01, packs))

    def test_all_allowed_templates_and_exclusions(self):
        for template in (*sorted(STACKABLE), 8, 10, 11, 20, 32, 33, 35, 30, 317, 318, 319, 320, 321, 340, 301):
            original = (item(1, template, 1), item(2, template, 1))
            merged = merge_stacks(original)
            self.assertEqual(merged, (item(1, template, 2),) if template in STACKABLE else original)

    def test_state_flags_durability_and_equipment_are_not_lost(self):
        variants = [dict(unknown_words=(1, 2, 3)), dict(unknown_bytes_01=b'\x01\0'),
                    dict(unknown_bytes_02=b'\0\0\x01\0'), dict(optional_u32=123),
                    dict(unknown_bytes_03=b'\x01\0\0'), dict(unknown_u8_01=1, location_raw=16)]
        for fields in variants:
            original = (item(1), item(2, **fields))
            self.assertEqual(merge_stacks(original), original)
        for fields in (variants[2], variants[3], variants[5]):
            original = (item(1, **fields), item(2, **fields))
            self.assertEqual(merge_stacks(original), original)

    def test_quantity_overflow_keeps_remainder_without_wrapping(self):
        merged = merge_stacks((item(1, count=MAX_STACK-2), item(2, count=10)))
        self.assertEqual(merged, (item(1, count=MAX_STACK), item(2, count=8)))
        self.assertEqual(merge_stacks(merged), merged)
        with self.assertRaises(ValueError): merge_stacks((item(1), item(1)))

    def test_purchase_counts_rounds_not_packs_and_keeps_existing_id(self):
        self.seed((item(70, count=32),))
        result = self.buy(5, 3)
        self.assertEqual(decode_item_list(result.inventory)[1], (item(70, count=152),))
        self.assertEqual((result.charged_credits, result.assets.credits), (120, 9880))
        result = self.buy(5, 1)
        self.assertEqual(decode_item_list(result.inventory)[1], (item(70, count=192),))
        result = self.buy(9, 3)
        self.assertEqual([(i.template_id, i.count) for i in decode_item_list(result.inventory)[1]], [(5, 192), (9, 3)])
        result = self.buy(10, 2)
        self.assertEqual([i.count for i in decode_item_list(result.inventory)[1] if i.template_id == 10], [1, 1])

    def test_gold_purchase_stacks_candies_but_not_rockets(self):
        store = SCShopStore(self.path)
        for template in (34, 8):
            lot = next(o.lot_id for o in store.offers.values() if o.item_id == template)
            for _ in range(2):
                result = store.handle('alice', b'\xb4\x06' + struct.pack('<III', lot, 1, 2))
            goods = [i for i in decode_item_list(result[0])[1] if i.template_id == template]
            self.assertEqual([i.count for i in goods], [2 * store.packs[lot]] if template == 34 else [1, 1])

    def test_wire_partial_transfer_merges_in_both_directions_even_when_full(self):
        self.seed((item(10, count=32),), (item(20, count=40),))
        def transfer(deposits=(), withdrawals=()):
            return transfer_private_items(self.path, 'alice',
                encode_warehouse_transfer(WarehouseTransfer(0, 1, deposits, withdrawals)), capacity=1)
        replies = transfer(((10, 12),))
        self.assertEqual(decode_item_list(replies[0])[1], (item(10, count=20),))
        self.assertEqual([(i.instance_id, i.count) for i in decode_warehouse_list(replies[1])[3]], [(20, 52)])
        replies = transfer(withdrawals=((20, 30),))
        self.assertEqual(decode_item_list(replies[0])[1], (item(10, count=50),))
        self.assertEqual([(i.instance_id, i.count) for i in decode_warehouse_list(replies[1])[3]], [(20, 22)])
        replies = transfer(((10, 50),))
        self.assertEqual(decode_item_list(replies[0])[1], ())
        self.assertEqual(self.warehouse.items('alice'), (item(20, count=72),))
        with self.assertRaises(WarehouseRejected): transfer(((10, 1),))
        replies = transfer(withdrawals=((20, 72),))
        self.assertEqual(decode_item_list(replies[0])[1], (item(20, count=72),))
        self.assertEqual(self.warehouse.items('alice'), ())

    def test_exchange_rollback_preserves_counts_and_sequence(self):
        self.seed((item(10), item(11, template=8, count=1)), (item(20),))
        before = self.pets.inventory('alice', 1), self.warehouse.items('alice')
        with self.assertRaises(WarehouseRejected):
            self.warehouse.exchange('alice', 1, deposits=((10, 40), (11, 1)))
        self.assertEqual((self.pets.inventory('alice', 1), self.warehouse.items('alice')), before)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER fail_stack BEFORE UPDATE ON warehouse_items BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.warehouse.exchange('alice', 1, deposits=((10, 20),))
        self.assertEqual((self.pets.inventory('alice', 1), self.warehouse.items('alice')), before)

    def test_login_compaction_is_local_idempotent_and_reserves_removed_ids(self):
        self.seed((item(10, 9, 1), item(999, 9, 1)), (item(20), item(21)))
        self.pets.ensure('bob', self.pet, encode_item_list(1, (item(10), item(999))), human=True)
        before_bob = self.pets.inventory('bob', 1)
        result = compact_saved_items(self.path, 'alice')
        self.assertEqual(result, {'inventories': 1, 'warehouse': True})
        self.assertEqual(decode_item_list(self.pets.inventory('alice', 1))[1], (item(10, 9, 2),))
        self.assertEqual(self.warehouse.items('alice'), (item(20, count=80),))
        self.assertEqual(self.pets.inventory('bob', 1), before_bob)
        self.assertEqual(compact_saved_items(self.path, 'alice'), {'inventories': 0, 'warehouse': False})
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM item_stack_backups').fetchone()[0], 3)
        purchased = self.buy(10, 1)
        self.assertEqual(decode_item_list(purchased.inventory)[1][-1].instance_id, 1000)
        with self.assertRaises(WarehouseRejected):
            self.warehouse.exchange('alice', 1, deposits=((999, 1),))

    def test_concurrent_purchases_do_not_lose_rounds(self):
        self.seed((item(10, count=1),))
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: self.buy(5, 2), range(2)))
        self.assertEqual(decode_item_list(self.pets.inventory('alice', 1))[1], (item(10, count=161),))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits, 9840)

    def test_stack_sale_consumes_selected_units_and_uses_pack_price(self):
        from tio.protocol.shop_sale import ShopSale
        self.seed((item(10, count=120),))
        self.assertEqual(self.shop.sell('alice', ShopSale(1, 10, 40), quote=True), 26)
        result = self.shop.sell('alice', ShopSale(1, 10, 40))
        self.assertEqual(result.assets.credits, 10026)
        self.assertEqual(decode_item_list(result.inventory)[1], (item(10, count=80),))
        before = result.inventory
        with self.assertRaises(ValueError): self.shop.sell('alice', ShopSale(1, 10, 81))
        self.assertEqual(self.pets.inventory('alice', 1), before)
        self.assertEqual(decode_item_list(self.shop.sell('alice', ShopSale(1, 10, 80)).inventory)[1], ())

    def test_migration_rolls_back_all_locations_on_write_failure(self):
        self.seed((item(10), item(11)), (item(20), item(21)))
        before = self.pets.inventory('alice', 1), self.warehouse.items('alice')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER fail_migration BEFORE DELETE ON warehouse_items BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError): compact_saved_items(self.path, 'alice')
        self.assertEqual((self.pets.inventory('alice', 1), self.warehouse.items('alice')), before)

    def test_native_catalog_agrees_with_requested_policy(self):
        for node in ET.parse(ROOT / 'evidence/items_diagnostic.xml').getroot():
            values = {v.get('key'): v.get('val') for v in node.findall('value')}
            if values.get('itype') in ('ammo', 'medkit'):
                self.assertEqual(values.get('stackable', '0') == '1', int(node.get('id')) in STACKABLE)
