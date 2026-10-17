from wallet_fixture import fund_wallet
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tio.battle_rewards import settle, receipt
from tio.reward_policy import RewardContext, calculate
from tio.wallets import WalletStore


class RewardPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.sqlite3'
        for name in ('alice','bob','carol'):fund_wallet(self.path, name, credits=10_000, gold=10_000)

    def context(self, level=1, enemy=1, active=True, opponent='bob'):
        return RewardContext((level,),((opponent,(enemy,)),),active)

    def award(self, match, result=1, **kwargs):
        context=kwargs.pop('reward_context',self.context())
        settle(self.path,'alice',match,result,reward_context=context,**kwargs)
        return receipt(self.path,'alice',match)

    def test_outcomes_strength_rank_and_floor(self):
        with closing(sqlite3.connect(self.path)) as db:
            for n,(level,enemy,result,rank,expected) in enumerate([
                (1,1,1,0,100),(1,1,0,0,25),(1,1,2,0,50),
                (10,10,1,20,152),(20,20,1,140,376),
                (20,1,1,0,78),(1,20,1,0,115),(1,1,1,-90,10)]):
                # Separate identities isolate repeated-opponent policy.
                gross,_=calculate(db,'alice',str(n),result,self.context(level,enemy,opponent='enemy'+str(n)),rank,now=100)
                self.assertEqual(gross,expected)

    def test_six_hour_pairs_symmetric_frozen_and_reconnect_safe(self):
        expected=[100,100,100,50,50,50,25]
        for n,gross in enumerate(expected):
            self.assertEqual(self.award(str(n),now=100+n)[0],gross)
            settle(self.path,'bob',str(n),1,reward_context=self.context(opponent='alice'),now=999)
            self.assertEqual(receipt(self.path,'bob',str(n))[0],gross)
        self.assertEqual(self.award('next',now=21707)[0],100)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reward_pairs').fetchone()[0],8)

    def test_retry_concurrent_no_recalculation_even_after_policy_inputs_change(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:self.award('once',now=100),range(8)))
        before=WalletStore(self.path).ensure('alice')
        self.award('once',reward_context=self.context(20,20,False),now=999999)
        self.assertEqual(WalletStore(self.path).ensure('alice'),before)
        self.assertEqual(before.credits,10100)
        with self.assertRaises(ValueError):self.award('once',result=0)

    def test_no_income_for_afk_escape_training_or_mining(self):
        from tio.crystal_market import CrystalMarket
        CrystalMarket(self.path)
        self.assertEqual(self.award('afk',reward_context=self.context(active=False)),(0,0))
        self.assertEqual(self.award('escape',escaped=True),(0,0))
        self.assertEqual(self.award('training',reward_context=None),(0,0))
        self.assertEqual(self.award('mine',mined_crystals=0),(0,0))

    def test_rental_and_atomic_failure(self):
        from tio.owned_pets import OwnedPetStore
        OwnedPetStore(self.path)
        self.assertEqual(self.award('rent',rental_units=(4,0)),(100,45))
        with self.assertRaises(ValueError):self.award('bad',health={999:1},now=100)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM reward_pairs WHERE match_id='bad'").fetchone())
            self.assertIsNone(db.execute("SELECT 1 FROM battle_rewards WHERE match_id='bad'").fetchone())

    def test_overflow_rolls_back_pair_and_reward(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=4294967295 WHERE account='alice'")
        with self.assertRaises(ValueError):self.award('overflow')
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=0 WHERE account='alice'")
        self.assertEqual(self.award('overflow'),(100,0))

    def test_multiple_opponents_and_average_squad_levels(self):
        for n in range(3):self.award(str(n),now=100)
        ctx=RewardContext((1,3),(('bob',(2,)),('carol',(2,))),True)
        self.assertEqual(self.award('team',reward_context=ctx,now=101),(77,0))
        with closing(sqlite3.connect(self.path)) as db:
            audit=json.loads(db.execute("SELECT calculation FROM battle_rewards WHERE match_id='team'").fetchone()[0])
        self.assertEqual((audit['base'],audit['repeat']),('103','3/4'))

    def test_legacy_receipt_survives_migration(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE battle_rewards(match_id TEXT,account TEXT,result INTEGER,credits INTEGER,PRIMARY KEY(match_id,account))')
            db.execute("INSERT INTO battle_rewards VALUES ('old','alice',1,1000)")
        self.award('old')
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,10000)


if __name__=='__main__':unittest.main()
