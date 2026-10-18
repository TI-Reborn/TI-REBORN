"""Current credit policy, isolated wallets and native purchase ledger."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile,sqlite3,unittest
from tio import premium
from tio.wallets import WalletStore
from wallet_fixture import fund_wallet

class PremiumCreditsTests(unittest.TestCase):
 def setUp(self):
  folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.path=Path(folder.name)/'premium.sqlite3'
  for account in ('a','b'):fund_wallet(self.path,account,credits=100000,gold=0)
 def test_all_four_offers_use_credits_and_keep_accounts_isolated(self):
  self.assertEqual(premium.OFFERS,{1:(24,1500),2:(720,30000),3:(24,1500),4:(720,30000)})
  expiry=0
  for offer in (1,2,3,4):
   hours,cost=premium.OFFERS[offer];now=1000+offer*10;prior=WalletStore(self.path).ensure('a').credits
   assets=premium.purchase(self.path,'a',premium.encode_purchase(offer,cost),now=now)
   self.assertEqual((assets.credits,assets.gold),(prior-cost,0));expiry=max(expiry,now)+hours*3600
   self.assertEqual(premium.current(self.path,'a',now),(1 if offer<=2 else 3,expiry-now))
  self.assertEqual(WalletStore(self.path).ensure('b').credits,100000)
  with closing(sqlite3.connect(self.path)) as db:
   self.assertEqual(list(db.execute('SELECT offer,gold,credits FROM premium_purchases ORDER BY id')),[(1,0,1500),(2,0,30000),(3,0,1500),(4,0,30000)])
 def test_gold_balance_cannot_pay_and_stale_quote_is_rejected(self):
  with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE wallets SET credits=1499,gold=99999 WHERE account='a'")
  for quote in (10,1500):
   with self.assertRaises(ValueError):premium.purchase(self.path,'a',premium.encode_purchase(1,quote),now=1000)
  wallet=WalletStore(self.path).ensure('a');self.assertEqual((wallet.credits,wallet.gold),(1499,99999));self.assertEqual(premium.current(self.path,'a',1000),(0,0))
 def test_duplicate_concurrency_debits_once(self):
  with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:premium.purchase(self.path,'a',premium.encode_purchase(1,1500),now=1000),range(8)))
  self.assertEqual(WalletStore(self.path).ensure('a').credits,98500)
  with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT count(*) FROM premium_purchases').fetchone()[0],1)
