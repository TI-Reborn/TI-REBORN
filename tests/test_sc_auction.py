from pathlib import Path
import tempfile
import unittest

from tio.characters import CharacterStore
from tio.db_transaction import transaction
from tio.onboarding import prepare
from tio.protocol.character_create import CharacterCreateRequest
from tio.sc_auction import SCAuctionStore, NATIVE_MAX, NATIVE_SECONDS_MAX, policy
from tio.wallets import WalletStore


class SCEligibleBoundaryTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'state.db';characters=CharacterStore(self.path)
        for account,name in (('alice-login','Alice'),('bobby-login','Bobby'),('untouched-login','David')):
            characters.create(account,CharacterCreateRequest(name.encode(),0,(1,0,0,0)));prepare(self.path,account)
        self.wallets=WalletStore(self.path)
        with transaction(self.path) as db:
            self.foreign=(db.execute("SELECT * FROM wallets WHERE account='untouched-login'").fetchall(),
                db.execute("SELECT * FROM owned_pets WHERE account='untouched-login'").fetchall())

    def tearDown(self):
        with transaction(self.path) as db:
            self.assertEqual((db.execute("SELECT * FROM wallets WHERE account='untouched-login'").fetchall(),
                db.execute("SELECT * FROM owned_pets WHERE account='untouched-login'").fetchall()),self.foreign)

    def store(self,**offer):
        rules=policy();rules['offers']=[{**rules['offers'][0],'duration':10,'extension':3,**offer}]
        store=SCAuctionStore(self.path,rules=rules,choose=lambda accounts:accounts[0]);store.tick(now=100)
        return store

    def credits(self,account):return self.wallets.ensure(account).credits

    def test_price_equal_cap_bid_allowed_then_next_bot_skipped_and_holds_refunded(self):
        store=self.store(start_price=NATIVE_MAX-1,price_step=1)
        for account in ('alice-login','bobby-login'):
            store.set_bot(account,1,0,0,3,request='price-cap-bot-'+account,now=101)
        store.tick(now=109,replenish=False)
        self.assertEqual((store.get(1)['price'],store.get(1)['bids']),(NATIVE_MAX,1))
        self.assertEqual(store.bot('alice-login',1)['held'],10)
        self.assertEqual(store.tick(now=112,replenish=False),0)
        self.assertEqual(store.bot('bobby-login',1)['remaining'],3)
        self.assertEqual(store.bot('bobby-login',1)['held'],15)
        store.tick(now=113,replenish=False)
        self.assertEqual(store.get(1)['state'],'won')
        self.assertEqual((self.credits('alice-login'),self.credits('bobby-login')),(2995,3000))
        self.assertEqual(store.bot('bobby-login',1)['held'],0)

    def test_exact_remaining_seconds_cap_still_allows_prepaid_bot(self):
        store=self.store(extension=NATIVE_SECONDS_MAX-1)
        store.set_bot('alice-login',1,0,0,2,request='time-cap-equal-bot',now=101)
        self.assertEqual(store.tick(now=109,replenish=False),1)
        self.assertEqual(store.get(1)['ends']-109,NATIVE_SECONDS_MAX)
        self.assertEqual(store.get(1)['bids'],1)
        self.assertEqual(store.bot('alice-login',1)['held'],5)
        self.assertEqual(self.credits('alice-login'),2990)

    def test_one_second_above_cap_skips_bot_and_close_refunds_all_unused_budget(self):
        store=self.store(extension=NATIVE_SECONDS_MAX)
        store.set_bot('alice-login',1,0,0,3,request='time-cap-above-bot',now=101)
        self.assertEqual(store.tick(now=109,replenish=False),0)
        self.assertEqual(store.get(1)['bids'],0)
        self.assertEqual(store.bot('alice-login',1)['held'],15)
        store.tick(now=110,replenish=False);store.tick(now=111,replenish=False)
        self.assertEqual(store.get(1)['state'],'unsold')
        self.assertEqual(self.credits('alice-login'),3000)
        with transaction(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sc_auction_history WHERE action='bid'").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM sc_auction_history WHERE action='bot_refund'").fetchone()[0],1)


if __name__=='__main__':unittest.main()
