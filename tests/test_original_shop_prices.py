import json
import sqlite3
import struct
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from tests import test_shop as shop_tests
ROOT=shop_tests.ROOT
from tio.protocol.item_list import decode_item_list
from tio.protocol.shop_purchase import ShopPurchase
from tio.protocol.premium_shop import decode_premium_purchase
from tio.protocol.city_services import city_service_reply
from tio.wallets import WalletStore


def gold_request(item, quantity=1, owner=1, revision=20261008):
    return struct.pack('<BIIIIIQI',0x78,1,1000+item,quantity,owner,0,revision,0)


class OriginalPricesTests(unittest.TestCase):
    setUp=shop_tests.ShopTests.setUp
    def test_price_coverage_and_currency_exclusivity(self):
        rows=json.loads((ROOT/'config/original_shop_prices.json').read_text())['items']
        self.assertEqual(len(rows),92)
        credits={o.item_id:o for o in self.store.catalogs.items[0]}
        gold={o.item_id:o for o in self.store.catalogs.premium_items}
        for r in rows:
            self.assertEqual(r['item_id'] in credits,r['credits'] is not None)
            self.assertEqual(r['item_id'] in gold,r['gold'] is not None)
        self.assertEqual(credits[304].unknown_u32_03,900)
        self.assertEqual(gold[304].gold,6)
        self.assertEqual(gold[252].gold,126)
        self.assertEqual(credits[261].unknown_u32_03,2200)
        self.assertEqual(credits[9].unknown_u32_02,1)
        self.assertEqual(gold[9].pack_count,3)
        self.assertEqual(city_service_reply(b'\x76'+bytes(4),self.store.catalogs)[0],0x77)

    def test_gold_pack_and_reconnect(self):
        result=self.store.purchase_premium('alice',gold_request(9,2))
        self.assertEqual((result.assets.credits,result.assets.gold),(10000,9998))
        bandages=[i for i in decode_item_list(result.inventory)[1] if i.template_id==9]
        self.assertEqual(sum(i.count for i in bandages),6)
        self.assertEqual((result.charged_credits,result.charged_gold),(0,2))
        self.assertEqual(WalletStore(self.path).ensure('alice').gold,9998)

    def test_gold_validation_and_atomic_failure(self):
        for packet in [gold_request(32),gold_request(326,0),gold_request(326,owner=77),
                       gold_request(326,revision=1),gold_request(252,1000),gold_request(326)+b'\0']:
            with self.assertRaises(ValueError): self.store.purchase_premium('alice',packet)
        with self.assertRaises(ValueError): self.store.purchase_premium('bob',gold_request(326))
        # Neither the old fixture ID nor a premium ID can buy Gold goods with credits.
        for offer in (2,1326):
            with self.assertRaises(ValueError): self.store.purchase('alice',ShopPurchase(1,0,offer,1))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER reject_gold BEFORE UPDATE ON owned_pets BEGIN SELECT RAISE(ABORT,'test rollback'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.store.purchase_premium('alice',gold_request(326))
        wallet=WalletStore(self.path).ensure('alice')
        self.assertEqual((wallet.credits,wallet.gold),(10000,10000))

    def test_gold_concurrency_cannot_overspend(self):
        with closing(sqlite3.connect(self.path)) as db, db: db.execute("UPDATE wallets SET gold=6 WHERE account='alice'")
        def buy(_):
            try: return self.store.purchase_premium('alice',gold_request(326))
            except ValueError: return None
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(buy,range(2)))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(WalletStore(self.path).ensure('alice').gold,2)
