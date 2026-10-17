"""Real shared fund debits, accepted receipts, winner payouts and safe refunds."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import importlib
import json
from pathlib import Path
import sqlite3
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

from tio import base_fund_completion as fund
from tio.db_transaction import transaction
from test_clan_benefits import ClanBenefitTests as BenefitFixture
from test_city_operations import CityOperationsTests as CityFixture

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/gameplay-followup/stage4-defense-fund'


def runtime(name,*,source=False):
    actual=importlib.import_module(name)
    if not source and hasattr(importlib.import_module('tio.clan_benefits'),'base_fund_completion_installed'):return actual
    path=REPORT/('source' if source else 'runtime')/Path(*name.split('.')).with_suffix('.py')
    module=ModuleType(name.rsplit('.',1)[0]+'._fund_'+('old_' if source else '')+name.rsplit('.',1)[1]);module.__package__=name.rsplit('.',1)[0]
    module.__file__=str(ROOT/Path(*name.split('.')).with_suffix('.py'));sys.modules[module.__name__]=module
    exec(compile(path.read_text(encoding='utf-8'),str(path),'exec'),module.__dict__);return module


B=runtime('tio.clan_benefits');OLD=runtime('tio.clan_benefits',source=True)
GAMEPLAY=runtime('server.clan_gameplay');CITY=runtime('server.city_operations')
GAMEPLAY.benefits=B;CITY.benefits=B


class BaseFundCompletionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=BenefitFixture(methodName='runTest');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups);self.path=self.fixture.path
        self.patch=patch.object(fund,'benefits',return_value=B);self.patch.start();self.addCleanup(self.patch.stop)
        with transaction(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS character_locations(account TEXT PRIMARY KEY,town_id INTEGER NOT NULL)')
            db.executemany('INSERT OR REPLACE INTO character_locations VALUES (?,3)',[(a,) for a in ('alice','bob','carol','dana','erin')])
        self.final=self.fixture.event(finalized=False);self.now=self.fixture.read('SELECT starts FROM warfare_events')[0][0]-1

    def call(self,method,*args,**kwargs):
        with transaction(self.path) as db:return method(db,*args,**kwargs)

    def read(self,sql,args=()):return self.fixture.read(sql,args)

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:return {name:db.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall() for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def donate(self,owner='bob',amount=101,identity='fund_request_00001'):
        return self.call(B.fund_defense,owner,'event1',amount,identity,now=self.now)

    def finish(self,*,scores=None,three=False):
        with transaction(self.path) as db:
            if scores is not None:
                db.execute('DELETE FROM warfare_scores WHERE event_id=?',('event1',));self.final['scores']={}
                for cid,account,units,contested in scores:
                    db.execute('INSERT INTO warfare_scores VALUES (?,?,?,?,1,0,10,0,?)',('event1',cid,account,units,contested))
                    self.final['scores'][str(cid)]=self.final['scores'].get(str(cid),0)+units
                self.final['captured']=False;self.final['claim']['owner_clan']=1
            if three:
                roster=[dict(clan_ids=[1,3,4],members=[]),dict(clan_ids=[2],members=[])]
                db.execute('UPDATE warfare_matches SET roster=? WHERE event_id=?',(json.dumps(roster),'event1'))
            db.execute("UPDATE warfare_events SET phase='FINISHED',finalized=1 WHERE id='event1'")
            db.execute('INSERT INTO warfare_event_receipts VALUES (?,?,0)',('event1',json.dumps(self.final)))

    def test_all_willing_players_pay_personal_credits_without_clan_or_leader_or_side_requirement(self):
        with transaction(self.path) as db:db.execute("DELETE FROM clan_members WHERE account='bob'")
        original=self.read('SELECT id,credits,influence FROM clans ORDER BY id')
        for owner in ('alice','bob','carol'):
            result=self.donate(owner,101,'fund_request_'+owner)
            self.assertEqual(result['payer'],'player_credits');self.assertEqual(result['charged_credits'],101)
        self.assertEqual(self.read('SELECT id,credits,influence FROM clans ORDER BY id'),original)
        self.assertEqual(self.read('SELECT credits FROM wallets WHERE account IN (\'alice\',\'bob\',\'carol\') ORDER BY account'),[(9899,)]*3)
        self.assertEqual(self.read('SELECT credits FROM clan_defense_funds'),[(303,)])
        self.assertEqual(self.read('SELECT COUNT(*) FROM base_fund_personal_contributions'),[(3,)])

    def test_native_private_command_supports_unclanned_city_actor_and_never_broadcasts(self):
        with transaction(self.path) as db:
            db.execute("DELETE FROM clan_members WHERE account='bob'")
            replies=GAMEPLAY.command(db,'bob','!base help',city_idle=True,now=self.now)
            self.assertTrue(any(b'\x22'==p[:1] and p[5]==4 for p in replies))
            packets=GAMEPLAY.command(db,'bob','!base fund event1 101 fund_request_bob_01',city_idle=True,now=self.now)
            self.assertIn('из личных кредитов'.encode('utf-16le'),packets[0]);self.assertEqual(packets[0][5],4)
            with self.assertRaises(ValueError):GAMEPLAY.command(db,'bob','!base tax 6 2 1',city_idle=True,now=self.now)
            with self.assertRaises(ValueError):GAMEPLAY.command(db,'bob','!base fund event1 1 fund_request_bob_02',city_idle=False,now=self.now)

    def test_replay_conflict_concurrent_accounts_and_restart_spend_once(self):
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:self.donate(),range(4)))
        self.assertEqual(results,[results[0]]*4);self.assertEqual(self.read("SELECT credits FROM wallets WHERE account='bob'"),[(9899,)])
        before=self.rows()
        with self.assertRaises(ValueError):self.donate(amount=102)
        self.assertEqual(self.rows(),before)
        self.now+=100000;self.assertEqual(self.donate(),results[0]);self.assertEqual(self.rows(),before)
        self.now-=100000
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda a:self.donate(a,50,'same_request_both_accounts'),('alice','carol')))
        self.assertEqual(self.read('SELECT credits FROM clan_defense_funds'),[(201,)])

    def test_insufficient_overflow_clock_boundaries_stale_owner_and_durable_city_gates_roll_back(self):
        before=self.rows()
        for amount in (0,-1,True,10001,2**32):
            with self.assertRaises(ValueError):self.donate(amount=amount)
            self.assertEqual(self.rows(),before)
        for stamp in (self.now+1,self.now+2,float('nan'),True):
            with self.assertRaises(ValueError):self.call(B.fund_defense,'bob','event1',1,'fund_bad_clock',now=stamp)
            self.assertEqual(self.rows(),before)
        with transaction(self.path) as db:db.execute("UPDATE territory_claims SET revision=2")
        before=self.rows()
        with self.assertRaises(ValueError):self.donate()
        self.assertEqual(self.rows(),before)
        with transaction(self.path) as db:
            db.execute('UPDATE territory_claims SET revision=1')
            db.execute('CREATE TABLE map_journeys(account TEXT PRIMARY KEY)');db.execute("INSERT INTO map_journeys VALUES ('bob')")
        before=self.rows()
        with self.assertRaises(ValueError):self.donate()
        self.assertEqual(self.rows(),before)
        with transaction(self.path) as db:
            db.execute('DELETE FROM map_journeys');db.execute('INSERT INTO clan_defense_funds VALUES (?,?,?,0)',('event1',1,B.MAX))
        before=self.rows()
        with self.assertRaises(ValueError):self.donate(amount=1)
        self.assertEqual(self.rows(),before)

    def test_outer_failure_and_receipt_failure_preserve_items_wallet_escrow_and_identity(self):
        before=self.rows()
        with self.assertRaises(RuntimeError):
            with transaction(self.path) as db:
                B.fund_defense(db,'bob','event1',101,'fund_rejected_outer',now=self.now)
                raise RuntimeError('Outer action rejected')
        self.assertEqual(self.rows(),before)
        with transaction(self.path) as db:db.execute("CREATE TRIGGER reject_fund_receipt BEFORE INSERT ON clan_benefit_receipts WHEN NEW.operation='fund' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        before=self.rows()
        with self.assertRaises(sqlite3.IntegrityError):self.donate()
        self.assertEqual(self.rows(),before)

    def test_three_actual_defender_winners_receive_50_30_20_independent_of_attack_capture(self):
        self.donate(amount=101);self.finish(three=True)
        result=self.call(B.settle_assault,'event1')
        self.assertEqual(result['defense_fund'],{'1':51,'3':30,'4':20});self.assertEqual(self.final['captured'],True)
        self.assertEqual(self.read('SELECT id,credits FROM clans ORDER BY id'),[(1,10051),(2,10000),(3,10030),(4,10020)])
        saved=self.rows();self.assertEqual(self.call(B.settle_assault,'event1'),result);self.assertEqual(self.rows(),saved)

    def test_less_than_three_defenders_preserve_normalization_policy_and_exact_total(self):
        self.donate(amount=101);self.finish()
        result=self.call(B.settle_assault,'event1');self.assertEqual(result['defense_fund'],{'1':64,'3':37});self.assertEqual(sum(result['defense_fund'].values()),101)

    def test_no_winners_refund_original_personal_and_legacy_clan_payers_without_rewrite(self):
        old=self.call(OLD.fund_defense,'alice','event1',77,'legacy_fund_00001')
        saved=self.rows();self.assertEqual(self.donate('alice',77,'legacy_fund_00001'),old);self.assertEqual(self.rows(),saved)
        self.donate('bob',101);self.donate('carol',50,'fund_refund_carol')
        self.finish(scores=[(1,'alice',0,0),(2,'carol',0,0)])
        result=self.call(B.settle_assault,'event1');self.assertEqual(result['defense_fund'],{'1':77});self.assertEqual(result['defense_refunds'],{'bob':101,'carol':50})
        self.assertEqual(self.read('SELECT id,credits FROM clans ORDER BY id'),[(i,10000) for i in range(1,5)])
        self.assertEqual(self.read('SELECT account,credits FROM wallets ORDER BY account'),[(a,10000) for a in ('alice','bob','carol','dana','erin')])
        self.assertEqual(self.read('SELECT claimed FROM base_fund_refund_escrow'),[(1,),(1,)])
        saved=self.rows();self.assertEqual(self.call(B.settle_assault,'event1'),result);self.assertEqual(self.rows(),saved)

    def test_wallet_overflow_stays_durable_and_private_refund_claim_is_once_only(self):
        self.donate();self.finish(scores=[(1,'alice',0,0),(2,'carol',0,0)])
        with transaction(self.path) as db:db.execute("UPDATE wallets SET credits=? WHERE account='bob'",(B.MAX,))
        result=self.call(B.settle_assault,'event1');self.assertEqual(result['defense_refunds'],{'bob':101})
        self.assertEqual(self.call(fund.refund_balance,'bob'),101);self.assertEqual(self.call(fund.refund_balance,'alice'),0)
        self.assertEqual(self.call(fund.claim_refunds,'bob'),dict(credited=0,pending=101))
        with transaction(self.path) as db:db.execute("UPDATE wallets SET credits=credits-101 WHERE account='bob'")
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.call(fund.claim_refunds,'bob'),range(2)))
        self.assertEqual(sum(r['credited'] for r in results),101);self.assertEqual(self.read("SELECT credits FROM wallets WHERE account='bob'"),[(B.MAX,)])
        with transaction(self.path) as db:
            packets=GAMEPLAY.command(db,'bob','!base refunds',city_idle=True,now=self.now)
            self.assertEqual(packets[0][5],4)
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM base_fund_refund_escrow')

    def test_refund_receipt_failure_rolls_back_finalization_benefits_and_all_personal_money(self):
        self.donate();self.finish(scores=[(1,'alice',0,0),(2,'carol',0,0)]);before=self.rows()
        with patch.object(B,'receipt',side_effect=RuntimeError('failed accepted settlement receipt')):
            with self.assertRaises(RuntimeError):self.call(B.settle_assault,'event1')
        self.assertEqual(self.rows(),before)

    def test_city_v1_all_contributors_see_form_and_owned_permissions_receipt_personal_delta(self):
        case=CityFixture(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
        operations=CITY.CityOperations(case.router,clock=lambda:case.now)
        with transaction(case.path) as db:
            db.execute("DELETE FROM clan_members WHERE account='bob'")
            claim=json.dumps(dict(location=6,owner_clan=1,tax_percent=10,revision=1))
            db.execute('INSERT INTO warfare_events VALUES (?,?,?,?,?,?,?,?,?,?)',('city-event-1',6,case.now+1000,case.now+2000,'REGISTRATION',1,case.now,'{}',claim,0))
        status=operations.status(dict(username='bob',slot=1));self.assertIsNone(status['clan']);base=next(b for b in status['bases'] if b['townId']==6)
        self.assertFalse(base['canSetTax']);self.assertFalse(base['canSetTime']);self.assertTrue(base['events'][0]['canFund'])
        request=case.request('base_fund',username='bob',eventId='city-event-1',credits=101,requestId='fund_city_bob_0001')
        first=operations.action(request);second=operations.action(request)
        self.assertEqual(first['receipt'],dict(requestId=request['requestId'],action='base_fund',creditsDelta=-101,goldDelta=0));self.assertTrue(second['replayed']);self.assertEqual(first['receipt'],second['receipt'])
        self.assertEqual(case.read("SELECT credits FROM wallets WHERE account='bob'"),[(9899,)]);self.assertEqual(case.read('SELECT credits FROM clans'),[(10000,)])
        self.assertEqual(set(status),set(case.ops.status(dict(username='bob',slot=1))))
        with transaction(case.path) as db:db.execute("UPDATE wallets SET credits=0 WHERE account='bob'")
        self.assertEqual(operations.status(dict(username='bob',slot=1))['bases'],[])


if __name__=='__main__':unittest.main()
