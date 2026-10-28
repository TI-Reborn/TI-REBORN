"""Shop purchases delivered straight to the personal warehouse (owner 0)."""
from wallet_fixture import fund_wallet
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tio.city_catalogs import CityCatalogs
from tio.owned_pets import OwnedPetStore
from tio.protocol.asset_count import encode_asset_count
from tio.protocol.item_list import decode_item_list
from tio.protocol.shop_purchase import ShopPurchase
from tio.protocol.warehouse import encode_private_warehouse_snapshot
from tio.shop import WAREHOUSE, PurchaseRejected, ShopStore, WarehousePurchaseResult
from tio.shop_errors import shop_error_reply
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore

ROOT = Path(__file__).resolve().parents[1]
SINGLE = 81  # Category 0 offer: one non-stacking item for 150 credits.


class WarehouseDeliveryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'shop.sqlite3'
        trial = json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        self.pet = bytes.fromhex(trial['packet_hex'])
        self.inventory = bytes.fromhex(trial['inventory_packet_hex'])
        for account in ('alice', 'bob'):
            OwnedPetStore(self.path).ensure(account, self.pet, self.inventory, human=True)
            fund_wallet(self.path, account, credits=10_000, gold=10_000)
        self.store = ShopStore(self.path, CityCatalogs(ROOT/'config/city_catalogs.json'))

    def warehouse(self, account='alice'):
        return WarehouseStore(self.path).items(account)

    def soldier(self, account='alice'):
        return OwnedPetStore(self.path).ensure(account, self.pet, self.inventory, human=True)[1]

    def credits(self, account='alice'):
        return WalletStore(self.path).ensure(account).credits

    def sql(self, statement, *args):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(statement, args)

    def test_purchase_lands_in_the_warehouse_not_the_soldier(self):
        result = self.store.purchase('alice', ShopPurchase(WAREHOUSE, 0, SINGLE, 2))
        self.assertIsInstance(result, WarehousePurchaseResult)
        self.assertEqual(self.credits(), 9700)
        self.assertEqual(result.charged_credits, 300)
        self.assertEqual([i.template_id for i in self.warehouse()], [327, 327])
        self.assertEqual(result.warehouse, self.warehouse())
        self.assertEqual(self.soldier(), self.inventory)

    def test_new_items_take_ordinary_slots_of_the_current_town(self):
        self.store.purchase('alice', ShopPurchase(WAREHOUSE, 0, SINGLE, 1))
        with closing(sqlite3.connect(self.path)) as db:
            places = db.execute('SELECT bucket,town,origin FROM warehouse_places WHERE account=?', ('alice',)).fetchall()
        self.assertEqual(places, [('city', 3, 'shop-purchase')])

    def test_item_ids_continue_the_account_sequence(self):
        soldier = self.store.purchase('alice', ShopPurchase(1, 0, SINGLE, 1))
        stored = self.store.purchase('alice', ShopPurchase(WAREHOUSE, 0, SINGLE, 1))
        last = decode_item_list(soldier.inventory)[1][-1].instance_id
        self.assertEqual([i.instance_id for i in stored.warehouse], [last+1])

    def test_replies_are_the_warehouse_snapshot_and_balance(self):
        result = self.store.purchase('alice', ShopPurchase(WAREHOUSE, 0, SINGLE, 1))
        expected = (*encode_private_warehouse_snapshot(result.warehouse), encode_asset_count(result.assets))
        self.assertEqual(result.packets(), expected)

    def test_soldier_purchase_replies_are_unchanged(self):
        result = self.store.purchase('alice', ShopPurchase(1, 0, SINGLE, 1))
        self.assertEqual(result.packets(), (result.inventory, encode_asset_count(result.assets)))

    def test_full_warehouse_rejects_the_whole_purchase(self):
        self.store.purchase('alice', ShopPurchase(WAREHOUSE, 0, SINGLE, 31))
        before = (self.credits(), self.warehouse())
        with self.assertRaisesRegex(PurchaseRejected, 'Недостаточно места на складе'):
            self.store.purchase('alice', ShopPurchase(WAREHOUSE, 0, SINGLE, 2))
        self.assertEqual((self.credits(), self.warehouse()), before)

    def test_location_without_a_warehouse_rejects_the_purchase(self):
        self.sql('CREATE TABLE character_locations (account TEXT PRIMARY KEY,town_id INTEGER NOT NULL)')
        self.sql("INSERT INTO character_locations VALUES ('alice',19)")  # Training base.
        with self.assertRaisesRegex(PurchaseRejected, 'Склад доступен'):
            self.store.purchase('alice', ShopPurchase(WAREHOUSE, 0, SINGLE, 1))
        self.assertEqual((self.credits(), self.warehouse()), (10_000, ()))

    def test_premium_goods_are_never_delivered_to_the_warehouse(self):
        with self.assertRaisesRegex(PurchaseRejected, 'Premium purchases require a mercenary'):
            self.store.purchase('alice', ShopPurchase(WAREHOUSE, 0, SINGLE, 1), _gold=True)
        self.assertEqual((self.credits(), self.warehouse()), (10_000, ()))

    def test_retry_with_the_same_identity_charges_once(self):
        request = ShopPurchase(WAREHOUSE, 0, SINGLE, 1)
        first = self.store.purchase('alice', request, identity='buy-1')
        again = self.store.purchase('alice', request, identity='buy-1')
        self.assertEqual(again, first)
        self.assertEqual(self.credits(), 9850)
        self.assertEqual(len(self.warehouse()), 1)

    def test_identity_cannot_be_reused_for_another_destination(self):
        self.store.purchase('alice', ShopPurchase(WAREHOUSE, 0, SINGLE, 1), identity='buy-1')
        with self.assertRaisesRegex(PurchaseRejected, 'Conflicting'):
            self.store.purchase('alice', ShopPurchase(1, 0, SINGLE, 1), identity='buy-1')

    def test_failed_warehouse_write_rolls_back_the_charge(self):
        self.sql("CREATE TRIGGER reject BEFORE INSERT ON warehouse_items BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.purchase('alice', ShopPurchase(WAREHOUSE, 0, SINGLE, 1))
        self.assertEqual(self.credits(), 10_000)

    def test_two_accounts_buy_into_separate_warehouses(self):
        def buy(account):
            return self.store.purchase(account, ShopPurchase(WAREHOUSE, 0, SINGLE, 3))
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(buy, ('alice', 'bob')))
        for account in ('alice', 'bob'):
            self.assertEqual(self.credits(account), 9550)
            self.assertEqual(len(self.warehouse(account)), 3)
            self.assertEqual(self.soldier(account), self.inventory)

    def test_concurrent_warehouse_purchases_cannot_overspend(self):
        self.sql("UPDATE wallets SET credits=300 WHERE account='alice'")
        def buy(_):
            try:
                return self.store.purchase('alice', ShopPurchase(WAREHOUSE, 0, SINGLE, 2))
            except PurchaseRejected:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(buy, range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual((self.credits(), len(self.warehouse())), (0, 2))


class WarehouseDeliveryErrorTests(unittest.TestCase):
    def test_warehouse_rejections_have_purchase_messages(self):
        for reason in ('Недостаточно места на складе', 'Склад доступен только в городе или у входа в шахту',
                       'Premium purchases require a mercenary'):
            with self.subTest(reason=reason):
                self.assertNotEqual(shop_error_reply(PurchaseRejected(reason)),
                                    shop_error_reply(PurchaseRejected('unmapped')))


if __name__ == '__main__':
    unittest.main()
