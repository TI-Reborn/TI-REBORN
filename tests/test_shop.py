from wallet_fixture import fund_wallet
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from tio.shop import ShopStore, PurchaseRejected
from tio.city_catalogs import CityCatalogs
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.item_list import decode_item_list
from tio.protocol.shop_purchase import ShopPurchase
from tio.protocol.shop_sale import ShopSale, encode_sale_request, decode_sale_request

ROOT = Path(__file__).resolve().parents[1]


class ShopTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'shop.sqlite3'
        trial = json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        self.pet = bytes.fromhex(trial['packet_hex'])
        self.inventory = bytes.fromhex(trial['inventory_packet_hex'])
        OwnedPetStore(self.path).ensure('alice', self.pet, self.inventory, human=True)
        fund_wallet(self.path, 'alice', credits=10_000, gold=10_000)
        self.store = ShopStore(self.path, CityCatalogs(ROOT/'config/city_catalogs.json'))

    def test_buy_and_reopen(self):
        result = self.store.purchase('alice', ShopPurchase(1, 0, 81, 2))
        self.assertEqual((result.assets.credits, result.assets.gold), (9700, 10000))
        _, items, _ = decode_item_list(result.inventory)
        self.assertEqual([(i.instance_id, i.template_id) for i in items], [(1001, 301), (1002, 327), (1003, 327)])
        self.assertEqual(OwnedPetStore(self.path).ensure('alice', self.pet, self.inventory, human=True)[1], result.inventory)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits, 9700)

    def test_expanded_catalog_purchases_and_resale(self):
        for template in (3,9,210,211,212,304):
            offer=next(o for o in self.store.catalogs.items[0] if o.item_id==template)
            result=self.store.purchase('alice',ShopPurchase(1,0,offer.unknown_u32_01,1))
            # A firearm now arrives with its ammunition pack; check the weapon itself.
            item=next(i for i in reversed(decode_item_list(result.inventory)[1]) if i.template_id==template)
            if template==3:
                self.assertEqual(item.count,50)  # Original 9mm packamount.
            self.assertEqual((item.template_id,item.count,item.unknown_words),(template,offer.unknown_u32_02,(offer.durability,)*3))
            if item.count==1:
                self.assertEqual(self.store.sell('alice',ShopSale(1,item.instance_id,1),quote=True),offer.unknown_u32_03*65//100)

    def test_quote_and_sale(self):
        request = ShopSale(1, 1001, 1)
        for quote in (False, True):
            packet = encode_sale_request(request, quote=quote)
            self.assertEqual(decode_sale_request(packet, quote=quote), request)
            with self.assertRaises(ValueError):
                decode_sale_request(packet[:-1], quote=quote)
        self.assertEqual(self.store.sell('alice', request, quote=True), 97)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits, 10000)
        result = self.store.sell('alice', request)
        self.assertEqual(result.assets.credits, 10097)
        self.assertEqual(decode_item_list(result.inventory)[1], ())
        with self.assertRaises(PurchaseRejected):
            self.store.sell('alice', request)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits, 10097)

    def test_sale_rejections_and_rollback(self):
        for account, request in [('bob', ShopSale(1, 1001, 1)), ('alice', ShopSale(2, 1001, 1)),
                                 ('alice', ShopSale(1, 1001, 2)), ('alice', ShopSale(1, 9999, 1))]:
            with self.assertRaises(PurchaseRejected):
                self.store.sell(account, request)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER reject_sale BEFORE UPDATE ON owned_pets BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.sell('alice', ShopSale(1, 1001, 1))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits, 10000)

    def test_sold_ids_are_never_reused(self):
        self.store.purchase('alice', ShopPurchase(1, 0, 81, 1))
        self.store.sell('alice', ShopSale(1, 1002, 1))
        result = self.store.purchase('alice', ShopPurchase(1, 0, 81, 1))
        self.assertEqual(decode_item_list(result.inventory)[1][-1].instance_id, 1003)
        with self.assertRaises(PurchaseRejected):
            self.store.sell('alice', ShopSale(1, 1002, 1))

    def test_rejections_leave_state_unchanged(self):
        for account, request in [('bob', ShopPurchase(1, 0, 1, 1)), ('alice', ShopPurchase(2, 0, 1, 1)),
                ('alice', ShopPurchase(1, 9, 1, 1)), ('alice', ShopPurchase(1, 0, 99, 1)),
                ('alice', ShopPurchase(1, 0, 1, 0)), ('alice', ShopPurchase(1, 0, 1, 101))]:
            with self.assertRaises(PurchaseRejected):
                self.store.purchase(account, request)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits, 10000)
        self.assertEqual(OwnedPetStore(self.path).ensure('alice', self.pet, self.inventory, human=True)[1], self.inventory)

    def test_inventory_write_failure_rolls_back_charge(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER reject_inventory BEFORE UPDATE ON owned_pets BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.purchase('alice', ShopPurchase(1, 0, 1, 1))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits, 10000)

    def test_concurrent_purchases_cannot_overspend(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=1200 WHERE account='alice'")
        def buy(_):
            try:
                return self.store.purchase('alice', ShopPurchase(1, 0, 1, 8))
            except PurchaseRejected:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(buy, range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits, 0)
        snapshot = OwnedPetStore(self.path).ensure('alice', self.pet, self.inventory, human=True)[1]
        # Original item + 8 weapons + one merged stack of their ammunition packs.
        self.assertEqual(len(decode_item_list(snapshot)[1]), 10)
