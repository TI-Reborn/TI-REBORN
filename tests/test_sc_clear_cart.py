import sqlite3,unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from tests import test_credits_only as fixtures
from tio.shop_completion import CompletedSCShopStore
from tio.protocol.sc_shop import encode_sc_basket,decode_sc_request

sc=fixtures.sc

class SCClearCartTests(unittest.TestCase):
    setUp=fixtures.CreditsOnlyTests.setUp
    wallet=fixtures.CreditsOnlyTests.wallet
    inventory=fixtures.CreditsOnlyTests.inventory
    def offer(self,item,level=0):return next(o for o in self.sc.offers.values() if o.item_id==item and o.enhancement==level)
    def fill(self,account='alice'):
        self.sc.handle(account,sc(9,self.offer(248,10).lot_id))
        self.sc.handle(account,sc(9,self.offer(248,10).lot_id))
        self.sc.handle(account,sc(9,self.offer(14).lot_id))
    def cart(self,account):
        with closing(sqlite3.connect(self.path)) as db:
            return tuple(db.execute('SELECT lot_id,quantity FROM sc_cart WHERE account=? ORDER BY lot_id',(account,)))
    def test_native_clear_packet_and_account_isolation(self):
        self.assertEqual(decode_sc_request(bytes.fromhex('b40a00000000')),(10,(0,)))
        self.fill();self.fill('bob');other=self.cart('bob');wallet=self.wallet();inventory=self.inventory()
        self.assertEqual(self.sc.handle('alice',sc(10,0),identity='clear-cart'),(encode_sc_basket(()),))
        self.assertEqual(self.cart('alice'),());self.assertEqual(self.cart('bob'),other)
        self.assertEqual(self.wallet(),wallet);self.assertEqual(self.inventory(),inventory)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertFalse(db.execute("SELECT 1 FROM sc_cart_terms WHERE account='alice'").fetchone())
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sc_cart_terms WHERE account='bob'").fetchone()[0],2)
            self.assertFalse(db.execute('SELECT 1 FROM sc_sold').fetchone())
    def test_empty_and_repeated_clear_and_reconnect_are_safe(self):
        self.assertEqual(self.sc.handle('alice',sc(10,0)),(encode_sc_basket(()),))
        self.fill();self.sc.handle('alice',sc(10,0),identity='clear-repeat')
        self.sc.handle('alice',sc(10,0),identity='clear-repeat')
        self.assertEqual(CompletedSCShopStore(self.path).handle('alice',sc(7)),(encode_sc_basket(()),))
        self.assertEqual(self.wallet(),(100000,0))
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM sc_receipts WHERE identity='clear-repeat'").fetchone()[0],1)
    def test_invalid_old_quotes_can_be_cleared_without_decoding_them(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT INTO sc_cart VALUES (?,123,5)',('alice',))
            db.execute('INSERT INTO sc_cart_terms VALUES (?,123,?,1)',('alice','obsolete-non-json-quote'))
        with self.assertRaises(ValueError):self.sc.handle('alice',sc(7))
        self.assertEqual(self.sc.handle('alice',sc(10,0)),(encode_sc_basket(()),))
    def test_clear_in_battle_and_malformed_packets_do_not_mutate(self):
        self.fill();before=self.cart('alice')
        with self.assertRaises(ValueError):self.sc.handle('alice',sc(10,0),allow_mutation=False)
        for packet in (bytes.fromhex('b40a000000'),bytes.fromhex('b40a0000000000')):
            with self.assertRaises(ValueError):self.sc.handle('alice',packet)
        self.assertEqual(self.cart('alice'),before)
    def test_remove_one_still_only_decrements_the_selected_lot(self):
        self.fill();self.sc.handle('alice',sc(10,self.offer(248,10).lot_id))
        self.assertEqual(dict(self.cart('alice')),{self.offer(248,10).lot_id:1,self.offer(14).lot_id:1})
    def test_failure_to_serialize_rolls_back_all_cart_deletions(self):
        from unittest.mock import patch
        self.fill();before=self.cart('alice')
        with patch('tio.shop_completion.encode_sc_basket',side_effect=ValueError('serialization failed')):
            with self.assertRaises(ValueError):self.sc.handle('alice',sc(10,0),identity='clear-error')
        self.assertEqual(self.cart('alice'),before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sc_cart_terms WHERE account='alice'").fetchone()[0],2)
            self.assertFalse(db.execute("SELECT 1 FROM sc_receipts WHERE identity='clear-error'").fetchone())
    def test_concurrent_clear_and_checkout_never_double_charge_or_leave_partial_cart(self):
        lot=self.offer(248).lot_id;self.sc.handle('alice',sc(9,lot))
        def action(packet):
            try:self.sc.handle('alice',packet);return True
            except ValueError:return False
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(action,(sc(10,0),sc(11,1,1))))
        self.assertTrue(results[0]);self.assertEqual(self.cart('alice'),())
        if results[1]:self.assertEqual(self.wallet(),(94000,0));self.assertEqual(len(fixtures.decode_item_list(self.inventory())[1]),1)
        else:self.assertEqual(self.wallet(),(100000,0));self.assertEqual(len(fixtures.decode_item_list(self.inventory())[1]),0)
