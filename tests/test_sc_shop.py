from wallet_fixture import fund_wallet
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from tio.sc_shop import SCShopStore
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.item_list import decode_item_list, encode_item_list, ItemRecord
from tio.protocol.sc_shop import decode_sc_request

ROOT = Path(__file__).resolve().parents[1]


def request(action, *fields):
    return bytes((0xb4, action)) + b''.join(struct.pack('<I', x) for x in fields)


class SCShopTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'sc.sqlite3'
        trial = json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        self.pet = bytes.fromhex(trial['packet_hex'])
        self.inventory = bytes.fromhex(trial['inventory_packet_hex'])
        OwnedPetStore(self.path).ensure('alice', self.pet, self.inventory, human=True)
        fund_wallet(self.path, 'alice', credits=10_000, gold=10_000)
        self.store = SCShopStore(self.path)
        self.lot = 100314  # Original M60 template; local offer ID/price.

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as db:
            return tuple((t, db.execute('SELECT * FROM '+t+' ORDER BY 1,2').fetchall())
                         for t in ('wallets', 'owned_pets', 'sc_cart', 'sc_sold', 'item_sequences'))

    def test_catalog_chain_and_strict_requests(self):
        before = self.snapshot()
        catalog, = self.store.handle('alice', request(4))
        self.assertEqual(catalog[:2], b'\xb4\x05')
        self.assertEqual(struct.unpack_from('<I', catalog, 2)[0], 35)
        self.assertEqual(len(catalog), 6 + 35*30)
        self.assertEqual(self.store.handle('alice', request(7)), (b'\xb4\x08'+bytes(22),))
        self.assertEqual(self.store.handle('alice', request(12)), (b'\xb4\x0d\0\0',))
        self.assertEqual(self.snapshot(), before)
        for packet in (b'', b'\xb4', b'\xb4\xff', request(4)+b'\0', request(6, 1, 2), request(11, 1)):
            with self.subTest(packet=packet), self.assertRaises(ValueError):
                decode_sc_request(packet)

    def test_direct_buy_and_reopen(self):
        replies = self.store.handle('alice', request(6, self.lot, 1, 2))
        assets = decode_asset_count(replies[1])
        self.assertEqual((assets.credits, assets.gold), (10000, 9900))
        item = decode_item_list(replies[0])[1][-1]
        self.assertEqual((item.instance_id, item.template_id, item.count, item.unknown_words),
                         (1002, 314, 1, (300, 300, 300)))
        self.assertEqual(OwnedPetStore(self.path).inventory('alice', 1), replies[0])
        self.assertEqual(SCShopStore(self.path).handle('alice', request(4)), (replies[2],))

    def test_cart_add_remove_checkout_and_account_isolation(self):
        self.store.handle('alice', request(9, self.lot))
        self.store.handle('alice', request(9, self.lot))
        self.store.handle('alice', request(10, self.lot))
        self.store.handle('alice', request(9, 100014))
        self.assertEqual(self.store.handle('bob', request(7)), (b'\xb4\x08'+bytes(22),))
        replies = SCShopStore(self.path).handle('alice', request(11, 1, 2))
        self.assertEqual(decode_asset_count(replies[1]).gold, 9875)
        items = decode_item_list(replies[0])[1]
        self.assertEqual([(i.template_id, i.count) for i in items[1:]], [(14, 100), (314, 1)])
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.store.handle('alice', request(11, 1, 2))
        self.assertEqual(self.snapshot(), before)

    def test_rejections_are_atomic(self):
        self.store.handle('alice', request(9, self.lot))
        before = self.snapshot()
        for account, packet in (('bob', request(6, self.lot, 1, 2)), ('alice', request(6, self.lot, 999, 2)),
                                ('alice', request(6, self.lot, 1, 1)), ('alice', request(6, 42, 1, 2)),
                                ('alice', request(11, 1, 3))):
            with self.subTest(packet=packet), self.assertRaises(ValueError):
                self.store.handle(account, packet)
            self.assertEqual(self.snapshot(), before)
        with self.assertRaises(ValueError):
            self.store.handle('alice', request(6, self.lot, 1, 2), allow_mutation=False)
        self.assertEqual(self.snapshot(), before)

    def test_insufficient_gold_preserves_cart_and_items(self):
        self.store.handle('alice', request(9, self.lot))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE wallets SET gold=99 WHERE account='alice'")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Insufficient gold'):
            self.store.handle('alice', request(11, 1, 2))
        self.assertEqual(self.snapshot(), before)

    def test_database_failure_rolls_back_everything(self):
        self.store.handle('alice', request(9, self.lot))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER fail_stock BEFORE INSERT ON sc_sold BEGIN SELECT RAISE(ABORT,'test'); END")
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.handle('alice', request(11, 1, 2))
        self.assertEqual(self.snapshot(), before)

    def test_stock_is_enforced_and_direct_purchase_clamps_cart(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO sc_sold VALUES (?,?,?)', ('alice', self.lot, 999))
        self.store.handle('alice', request(9, self.lot))
        with self.assertRaises(ValueError):
            self.store.handle('alice', request(9, self.lot))
        self.store.handle('alice', request(6, self.lot, 1, 2))
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.store.handle('alice', request(6, self.lot, 1, 2))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.store.handle('alice', request(7)), (b'\xb4\x08'+bytes(22),))

    def test_warehouse_ids_are_not_reused(self):
        item = ItemRecord(5000, 314, bytes(2), 1, 0, 0, (300,)*3, bytes(4), None, bytes(3))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)', ('alice', 5000, encode_item_list(0, (item,))))
        replies = self.store.handle('alice', request(6, self.lot, 1, 2))
        self.assertEqual(decode_item_list(replies[0])[1][-1].instance_id, 5001)

    def test_parallel_checkout_only_commits_once(self):
        self.store.handle('alice', request(9, self.lot))
        def buy(_):
            try:
                self.store.handle('alice', request(11, 1, 2))
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(buy, range(2))), [False, True])
        self.assertEqual(WalletStore(self.path).ensure('alice').gold, 9900)

