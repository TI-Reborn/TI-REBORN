from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tio.crystal_market import CrystalMarket,POLICY,SCALE
from tio.mining_service import MiningService
from tio.protocol.mining import price_history
from wallet_fixture import fund_wallet


class CrystalQuoteHistoryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'crystals.sqlite3';self.now=1000
        fund_wallet(self.path,'seller',credits=0,gold=0)
        self.market=CrystalMarket(self.path,clock=lambda:self.now)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT INTO crystal_wallets VALUES (?,?)',('seller',10000))

    def test_initial_history_is_empty_until_a_real_quote_is_observed(self):
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM crystal_quote_history').fetchone()[0],0)
        rate,history=self.market.quote_history()
        self.assertEqual(history,((rate,rate,rate,rate),))
        self.assertEqual(self.market.quote_history(),(rate,history))

    def test_first_sale_after_cutover_uses_fixed_price_and_retains_old_quote(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE crystal_market SET rate=?, updated=?', (82*SCALE, self.now))
            db.execute('INSERT INTO crystal_quote_history(observed,rate) VALUES (?,?)', (self.now,82*SCALE))
        self.assertEqual(self.market.sell('seller',1000),50_000)
        self.now+=30*86400
        restored=CrystalMarket(self.path,clock=lambda:self.now)
        self.assertEqual(restored.quote_history(),(50,((82,)*4,(50,)*4)))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT amount,credits,rate FROM crystal_sales').fetchall(),
                             [(1000,50_000,50*SCALE)])

    def test_rejected_sale_cannot_write_a_price_or_history_sample(self):
        before=self.market.quote_history()
        with self.assertRaises(ValueError):self.market.sell('seller',11000)
        self.assertEqual(self.market.quote_history(),before)

    def test_bounded_history_and_native_quote_are_based_on_same_transaction(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.executemany('INSERT INTO crystal_quote_history(observed,rate) VALUES (?,?)',
                           [(n,n*SCALE) for n in (80,81,82,83)])
        with patch.dict(POLICY,market_history_points=3):
            rate,values=self.market.quote_history()
        self.assertEqual(len(values),3)
        service=object.__new__(MiningService);service.market=self.market
        packets=service.quote()
        # Original client reverses wire candles before drawing the graph.
        self.assertEqual(packets[1],price_history(tuple(reversed(values))))
        self.assertEqual(len(packets[1]),4+16*3)
        self.assertEqual(values[-1],(rate,)*4)


if __name__=='__main__':unittest.main()
