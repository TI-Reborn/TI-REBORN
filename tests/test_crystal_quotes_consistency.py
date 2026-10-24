"""Native history orientation and the manual's shared fixed-point sale rules."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from types import SimpleNamespace

from wallet_fixture import fund_wallet
from tio.crystal_market import CrystalMarket, POLICY, SCALE
from tio.mining_service import MiningService


class CrystalQuotesTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'market.sqlite3'
        self.now = 1000
        self.market = CrystalMarket(self.path, clock=lambda: self.now)
        for account in ('alice', 'bob'):
            fund_wallet(self.path, account, credits=0, gold=0)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executemany('INSERT INTO crystal_wallets VALUES (?,?)',
                           (('alice', 1000000), ('bob', 1000000)))
            db.execute('UPDATE crystal_market SET rate=?', (426500000,))
        self.service = object.__new__(MiningService)
        self.service.path = self.path
        self.service.market = self.market
        self.service.arena = SimpleNamespace()

    def graph(self):
        price, history = self.service.quote()
        count = struct.unpack_from('<h', history, 2)[0]
        wire = [struct.unpack_from('<4f', history, 4 + 16*i) for i in range(count)]
        return struct.unpack_from('<f', price, 2)[0], tuple(reversed(wire))

    def test_oldest_left_latest_right_and_caption_same_float32(self):
        self.market.quote_history()
        self.now += 600
        self.market.quote_history()
        self.market.sell('alice', 50000)
        current, displayed = self.graph()
        self.assertEqual(displayed[-1], (current,)*4)
        self.assertAlmostEqual(displayed[0][0], 42.65, places=4)
        self.assertAlmostEqual(displayed[-2][0], 42.66, places=4)
        self.assertAlmostEqual(current, 42.655, places=4)

    def test_manual_thousand_and_maximum_sale_drop_after_payment(self):
        self.assertEqual((SCALE, POLICY['market_rise_interval'], POLICY['market_rise_units']),
                         (10000000, 600, 100000))
        self.assertEqual((POLICY['market_sale_min'], POLICY['market_sale_max']), (1000, 50000))
        for account, amount in (('alice', 1000), ('bob', 50000)):
            before = round(self.market.rate()*SCALE)
            self.assertEqual(self.market.sell(account, amount), amount*before//SCALE)
            after = round(self.market.rate()*SCALE)
            self.assertEqual(before-after, amount)
            current, graph = self.graph()
            self.assertEqual(graph[-1], (current,)*4)
        self.now += 599
        self.assertEqual(round(self.market.rate()*SCALE), after)
        self.now += 1
        self.assertEqual(round(self.market.rate()*SCALE), after+100000)

    def test_volume_sales_fall_globally_without_changing_other_inventory(self):
        before = round(self.market.rate()*SCALE)
        for _ in range(20):
            self.market.sell('alice', 50000)
        self.assertEqual(round(self.market.rate()*SCALE), before-1000000)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT amount FROM crystal_wallets WHERE account='bob'").fetchone(),
                             (1000000,))
            self.assertEqual(db.execute("SELECT credits FROM wallets WHERE account='bob'").fetchone(), (0,))
        shared = CrystalMarket(self.path, clock=lambda: self.now)
        self.assertEqual(shared.rate(), self.market.rate())

    def test_concurrent_accounts_conserve_both_sales_and_shared_rate(self):
        before = round(self.market.rate()*SCALE)
        with ThreadPoolExecutor(max_workers=2) as pool:
            amounts = list(pool.map(lambda account: self.market.sell(account, 50000), ('alice', 'bob')))
        self.assertEqual(round(self.market.rate()*SCALE), before-100000)
        self.assertEqual(sum(amounts), 50000*before//SCALE + 50000*(before-50000)//SCALE)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT sum(amount) FROM crystal_wallets').fetchone(), (1900000,))
            self.assertEqual(db.execute('SELECT count(*),sum(amount) FROM crystal_sales').fetchone(), (2,100000))

    def test_sale_reply_replaces_quote_and_graph_with_same_post_sale_price(self):
        self.market.quote_history()
        _, rows = self.service.handle('alice', 1, b'Alice', b'\xb0\x1d'+struct.pack('<i',50000))
        price = struct.unpack_from('<f', rows[1], 2)[0]
        newest = struct.unpack_from('<4f', rows[2], 4)
        self.assertEqual(newest, (price,)*4)
        self.assertEqual(rows[0][:2], b'\xc8\x39')
        self.assertEqual(rows[1][:2], b'\xb0\x20')
        self.assertEqual(rows[2][:2], b'\xb0\x1f')

    def test_rejected_sales_leave_price_history_wallets_and_ledger_unchanged(self):
        self.market.quote_history()
        def snapshot():
            with closing(sqlite3.connect(self.path)) as db:
                return {t:db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall()
                        for t in ('crystal_market','crystal_quote_history','crystal_wallets','wallets','crystal_sales')}
        before = snapshot()
        for amount in (0, 999, 50001, -1000):
            with self.assertRaises(ValueError):
                self.market.sell('alice', amount)
        with self.assertRaises(ValueError):
            self.market.sell('missing', 1000)
        self.assertEqual(snapshot(), before)

    def test_floor_and_restart_preserve_actual_price_at_graph_right_edge(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE crystal_market SET rate=?', (POLICY['market_min_rate_units']+1000,))
        self.market.sell('alice', 50000)
        self.assertEqual(round(self.market.rate()*SCALE), POLICY['market_min_rate_units'])
        self.service.market = CrystalMarket(self.path, clock=lambda:self.now)
        current, graph = self.graph()
        self.assertEqual(graph[-1], (current,)*4)


if __name__ == '__main__':
    unittest.main()
