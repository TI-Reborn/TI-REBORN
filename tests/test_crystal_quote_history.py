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

    def test_sale_and_ten_minute_rise_survive_restart_with_exact_fixed_point_prices(self):
        rate,history=self.market.quote_history()
        self.market.sell('seller',1000)
        after=self.market.quote_history()
        self.assertEqual(after[0],(POLICY['market_initial_rate_units']-1000)/SCALE)
        self.assertEqual(len(after[1]),2)
        self.now+=600
        restored=CrystalMarket(self.path,clock=lambda:self.now)
        current,values=restored.quote_history()
        self.assertEqual(current,(POLICY['market_initial_rate_units']-1000+POLICY['market_rise_units'])/SCALE)
        self.assertEqual(values[:2],after[1]);self.assertEqual(values[-1],(current,)*4)

    def test_rejected_sale_cannot_write_a_price_or_history_sample(self):
        before=self.market.quote_history()
        with self.assertRaises(ValueError):self.market.sell('seller',11000)
        self.assertEqual(self.market.quote_history(),before)

    def test_bounded_history_and_native_quote_are_based_on_same_transaction(self):
        with patch.dict(POLICY,market_history_points=3):
            for _ in range(5):
                self.market.quote_history();self.now+=600
            rate,values=self.market.quote_history()
        self.assertEqual(len(values),3)
        service=object.__new__(MiningService);service.market=self.market
        packets=service.quote()
        # Original client reverses wire candles before drawing the graph.
        self.assertEqual(packets[1],price_history(tuple(reversed(values))))
        self.assertEqual(len(packets[1]),4+16*3)
        self.assertEqual(values[-1],(rate,)*4)


if __name__=='__main__':unittest.main()
