from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch
import json,sqlite3,struct,tempfile,unittest

from tio import clan_benefits as b
from tio.clans import schema as clan_schema, ClanRejected, CREST
from tio.db_transaction import transaction
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import encode_item_list
from tio.territories import schema as warfare_schema
from tio.warehouse import WarehouseStore

ROOT=Path(__file__).resolve().parents[1]


def bmp(color=7):
    return b'BM'+struct.pack('<III',822,0,54)+struct.pack('<IiiHHIIiiII',40,16,16,1,24,0,768,0,0,0,0)+bytes([color])*768


class ClanBenefitTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.path=Path(folder.name)/'players.sqlite3'
        pets=OwnedPetStore(self.path);WarehouseStore(self.path)
        raw=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        for account in ('alice','bob','carol','dana','erin'):pets.ensure(account,raw,encode_item_list(1,()),human=True)
        with transaction(self.path) as db:
            clan_schema(db);warfare_schema(db);b.schema(db)
            db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB)')
            db.execute('CREATE TABLE wallets(account TEXT PRIMARY KEY,credits INTEGER,gold INTEGER)')
            for a in ('alice','bob','carol','dana','erin'):
                db.execute('INSERT INTO characters VALUES (?,1,?)',(a,a.encode()));db.execute('INSERT INTO wallets VALUES (?,10000,1000)',(a,))
            for cid,leader in ((1,'alice'),(2,'carol'),(3,'dana'),(4,'erin')):
                db.execute('INSERT INTO clans(id,name,name_key,leader,influence,credits) VALUES (?,?,?,?,100000,10000)',(cid,leader.encode(),leader,leader))
            for a,c in (('alice',1),('bob',1),('carol',2),('dana',3),('erin',4)):
                db.execute('INSERT INTO clan_members(account,clan_id,permissions) VALUES (?,?,0)',(a,c))
            db.execute("INSERT INTO territory_claims VALUES (6,1,10,1)")
            db.execute("INSERT INTO territory_claim_history VALUES (6,1,1,10,'fixture','fixture',0)")
        self.week=b.week_start(1791600000)

    def read(self,sql,args=()):
        with closing(sqlite3.connect(self.path)) as db:return db.execute(sql,args).fetchall()

    def call(self,method,*args,**kwargs):
        with transaction(self.path) as db:return method(db,*args,**kwargs)

    def event(self,identity='event1',*,finalized=True,captured=True,scores=None,ends=None):
        scores=scores or [(1,'alice',20,1),(1,'bob',10,1),(2,'carol',30,1),(3,'dana',15,1),(4,'erin',5,1)]
        ends=ends or self.week+10000+1000*self.read('SELECT COUNT(*) FROM warfare_events')[0][0];totals={}
        for c,_,n,_ in scores:totals[str(c)]=totals.get(str(c),0)+n
        frozen={'location':6,'owner_clan':1,'tax_percent':10,'revision':1}
        final=dict(event_id=identity,town=6,winner_clan=2,captured=captured,claim={**frozen,'owner_clan':2 if captured else 1,'revision':2 if captured else 1},scores=totals,benefits_version=1)
        with transaction(self.path) as db:
            db.execute('INSERT INTO warfare_events VALUES (?,?,?,?,?,?,?,?,?,?)',(identity,6,ends-100,ends,'FINISHED' if finalized else 'REGISTRATION',3,ends,'{}',json.dumps(frozen),int(finalized)))
            for c,a,n,contested in scores:db.execute('INSERT INTO warfare_scores VALUES (?,?,?,?,1,0,10,0,?)',(identity,c,a,n,contested))
            roster=[dict(clan_ids=[1,3],members=[]),dict(clan_ids=[2,4],members=[])]
            db.execute("INSERT INTO warfare_matches VALUES (?,?,1,1,2,NULL,'settled',?,0)",('pair:'+identity,identity,json.dumps(roster)))
            if finalized:db.execute('INSERT INTO warfare_event_receipts VALUES (?,?,0)',(identity,json.dumps(final)))
        return final

    def test_xp_coefficients_premium_achievement_and_receipts(self):
        with transaction(self.path) as db:
            db.execute('CREATE TABLE premium_accounts(account TEXT PRIMARY KEY,kind INTEGER,expires INTEGER)')
            db.execute("INSERT INTO premium_accounts VALUES ('alice',3,9999999999)")
            db.execute('CREATE TABLE achievement_awards(account TEXT,id INTEGER,body TEXT)')
            db.execute('INSERT INTO achievement_awards VALUES (?,?,?)',('alice',1,json.dumps(dict(prizes=[dict(kind=1,value=1.1)]))))
        self.assertEqual(self.call(b.settle_experience,'alice','battle1',{1:1000},city_coefficient='2',now=10)['amount'],165)
        self.assertEqual(self.call(b.settle_experience,'alice','reservation',{1:1000},city_coefficient=0)['amount'],0)
        first=self.call(b.settle_experience,'alice','ordinary',{1:100},now=10)
        self.assertEqual(first,self.call(b.settle_experience,'alice','ordinary',{1:100},now=10))
        self.assertEqual(self.read("SELECT contribution FROM clan_members WHERE account='alice'")[0][0],173)
        with self.assertRaises(ClanRejected):self.call(b.settle_experience,'alice','ordinary',{1:101})
        with self.assertRaises(ClanRejected):self.call(b.settle_experience,'alice','foreign',{99:100})

    def test_unclanned_xp_is_not_backfilled_after_join(self):
        with transaction(self.path) as db:db.execute("DELETE FROM clan_members WHERE account='bob'")
        first=self.call(b.settle_experience,'bob','past',{1:10000})
        self.assertEqual(first['amount'],0)
        with transaction(self.path) as db:db.execute("INSERT INTO clan_members(account,clan_id,permissions) VALUES ('bob',1,0)")
        self.assertEqual(self.call(b.settle_experience,'bob','past',{1:10000}),first)

    def test_gold_adds_exactly_one_per_spent_gold_and_concurrent_retry(self):
        def invoke(_):return self.call(b.premium_gold_spent,'alice','sale:17',73)
        with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(invoke,range(4)))
        self.assertTrue(all(row==rows[0] for row in rows))
        self.assertEqual(self.read('SELECT influence FROM clans WHERE id=1')[0][0],100073)
        self.assertEqual(self.read("SELECT gold FROM wallets WHERE account='alice'")[0][0],1000) # caller debits actual purchase.

    def test_hourly_decay_no_retroactive_same_hour_or_reverse_clock(self):
        self.assertEqual(self.call(b.decay,now=100*3600),{})
        self.call(b.decay,now=124*3600)
        value=self.read('SELECT influence FROM clans WHERE id=1')[0][0]
        self.assertTrue(97000<=value<=98000,value)
        self.assertEqual(self.call(b.decay,now=124*3600),{})
        self.assertEqual(self.call(b.decay,now=110*3600),{})
        self.assertEqual(self.read('SELECT influence FROM clans WHERE id=1')[0][0],value)

    def test_decay_level_multiplier_fractional_small_value_bounded_catchup(self):
        with transaction(self.path) as db:
            db.execute('UPDATE clans SET level=1 WHERE id=2');db.execute('UPDATE clans SET influence=1 WHERE id=3')
        self.call(b.decay,now=0);self.call(b.decay,now=3600)
        self.assertEqual(self.read('SELECT influence FROM clans WHERE id=3')[0][0],1)
        self.call(b.decay,now=24*3600)
        levels=self.read('SELECT influence FROM clans WHERE id IN (1,2) ORDER BY id')
        self.assertGreater(levels[0][0],levels[1][0])
        self.call(b.decay,now=1000*3600)
        self.assertEqual(self.read('SELECT last_hour FROM clan_decay WHERE clan_id=1')[0][0],192)

    def test_crest_validation_rights_real_cost_and_durable_id(self):
        with self.assertRaises(ClanRejected):self.call(b.set_crest,'bob',bmp(),'other')
        with transaction(self.path) as db:db.execute('UPDATE clan_members SET permissions=? WHERE account=?',(CREST,'bob'))
        first=self.call(b.set_crest,'bob',bmp(),'set1');self.assertEqual(first['charged'],1000)
        self.assertEqual(first,self.call(b.set_crest,'bob',bmp(),'set1'))
        second=self.call(b.set_crest,'bob',bmp(),'set2');self.assertEqual(second['charged'],0)
        self.assertEqual(self.read("SELECT credits FROM wallets WHERE account='bob'")[0][0],9000)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(b.crest_id(db,1),first['crest_id']);self.assertEqual(b.crest_content(db,first['crest_id']),bmp())
        for raw in (bmp()+b'X',bmp()[:700],bmp().replace(b'BM',b'ZZ',1),bmp()[:28]+b'\x08\0'+bmp()[30:]):
            with self.assertRaises(ClanRejected):self.call(b.set_crest,'alice',raw,'invalid')

    def test_crest_storage_failure_rolls_back_wallet_and_public_crest(self):
        with transaction(self.path) as db:db.execute("CREATE TRIGGER failcrest BEFORE INSERT ON clan_crests BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.call(b.set_crest,'alice',bmp(),'failed')
        self.assertEqual(self.read("SELECT credits FROM wallets WHERE account='alice'")[0][0],10000)
        self.assertEqual(self.read('SELECT * FROM clan_crest_blobs'),[])

    def test_owner_tax_city_mapping_premium_exemption_and_conservation(self):
        with self.assertRaises(ClanRejected):self.call(b.set_base_tax,'bob',6,5,expected_revision=1)
        with self.assertRaises(ClanRejected):self.call(b.set_base_tax,'carol',6,5,expected_revision=1)
        with self.assertRaises(ClanRejected):self.call(b.set_base_tax,'alice',6,11,expected_revision=1)
        self.assertEqual(self.call(b.set_base_tax,'alice',6,7,expected_revision=1),2)
        taxed=self.call(b.sales_tax,'bob','sold1',2,101)
        self.assertEqual((taxed['tax'],taxed['net']),(7,94))
        self.assertEqual(taxed,self.call(b.sales_tax,'bob','sold1',2,101))
        self.assertEqual(self.read('SELECT credits FROM clans WHERE id=1')[0][0],10007)
        self.assertEqual(self.call(b.sales_tax,'bob','premium',2,1000,premium=True)['tax'],0)
        self.assertEqual(self.call(b.sales_tax,'bob','elsewhere',5,1000)['tax'],0)
        with self.assertRaises(ClanRejected):self.call(b.set_base_tax,'alice',6,8,expected_revision=1)

    def test_owner_schedule_fixed_weekday_created_event_and_owner_change(self):
        config=json.loads((ROOT/'config/territories.json').read_text());entry=next(x for x in config['territories'] if x['id']==6)
        default=int(datetime.fromisoformat(entry['first_start_utc'].replace('Z','+00:00')).timestamp())+b.WEEK
        choice=b.schedule_options(default)[0]
        self.call(b.set_next_assault,'alice',6,default,choice,now=default-86400)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(b.scheduled_start(db,6,default),choice)
        with self.assertRaises(ClanRejected):self.call(b.set_next_assault,'alice',6,default+86400,choice+86400,now=default-86400)
        self.event(ends=choice+100)
        with transaction(self.path) as db:db.execute('UPDATE warfare_events SET starts=?',(choice,))
        with self.assertRaises(ClanRejected):self.call(b.set_next_assault,'alice',6,default,choice,now=default-86400)
        with transaction(self.path) as db:db.execute('UPDATE territory_claims SET owner_clan=NULL,tax_percent=0')
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(b.scheduled_start(db,6,default),default)

    def test_finalized_assault_capture_medals_tokens_and_no_retry_rewards(self):
        self.event();first=self.call(b.settle_assault,'event1')
        self.assertEqual(first['capture_influence'],10000)
        self.assertEqual(first['players']['dana']['side'],'defense')
        self.assertEqual(self.read('SELECT influence FROM clans WHERE id=2')[0][0],110000)
        self.assertEqual(self.read('SELECT COUNT(*),SUM(golden) FROM range_accounts')[0],(5,5))
        self.assertEqual(first,self.call(b.settle_assault,'event1'))
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(b.influence_multiplier(db,'alice'),Fraction(23,20))
        self.assertEqual(self.read('SELECT COUNT(*) FROM clan_assault_prizes')[0][0],5)

    def test_unfinished_uncontested_and_changed_scores_reject_or_no_rewards(self):
        self.event(finalized=False)
        with self.assertRaises(ClanRejected):self.call(b.settle_assault,'event1')
        self.event('peace',captured=False,scores=[(1,'alice',100,0),(2,'carol',0,0)])
        peace=self.call(b.settle_assault,'peace');self.assertEqual(peace['players'],{})
        self.assertEqual(self.read('SELECT * FROM clan_assault_totals WHERE event_id=?',('peace',)),[])
        self.event('tampered')
        with transaction(self.path) as db:db.execute("UPDATE warfare_scores SET ov_units=999 WHERE event_id='tampered' AND account='alice'")
        with self.assertRaises(ClanRejected):self.call(b.settle_assault,'tampered')
        self.assertEqual(self.read('SELECT * FROM clan_assault_medals'),[])

    def test_defense_fund_escrow_split_conserves_and_failure_is_atomic(self):
        final=self.event(finalized=False,captured=False)
        self.call(b.fund_defense,'alice','event1',101,'fund1')
        self.call(b.fund_defense,'alice','event1',101,'fund1')
        self.assertEqual(self.read('SELECT credits FROM clans WHERE id=1')[0][0],9899)
        with transaction(self.path) as db:
            db.execute("UPDATE warfare_events SET finalized=1,phase='FINISHED'")
            db.execute('INSERT INTO warfare_event_receipts VALUES (?,?,0)',('event1',json.dumps(final)))
            db.execute("CREATE TRIGGER failmedal BEFORE INSERT ON clan_assault_medals BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.call(b.settle_assault,'event1')
        self.assertEqual(self.read('SELECT settled FROM clan_defense_funds')[0][0],0)
        self.assertEqual(self.read('SELECT * FROM clan_assault_totals'),[])
        with transaction(self.path) as db:db.execute('DROP TRIGGER failmedal')
        result=self.call(b.settle_assault,'event1')
        self.assertEqual(result['defense_fund'],{'1':64,'3':37})
        self.assertEqual(sum(result['defense_fund'].values()),101)
        self.assertEqual(result,self.call(b.settle_assault,'event1'))
        self.assertEqual(self.call(b.fund_defense,'alice','event1',101,'fund1')['escrow'],101)

    def test_weekly_top20_bonus_bands_current_membership_and_expiry(self):
        with transaction(self.path) as db:
            for c in range(5,25):db.execute('INSERT INTO clans(id,name,name_key,leader) VALUES (?,?,?,?)',(c,str(c).encode(),str(c),'leader'+str(c)))
        leaders=dict(self.read('SELECT id,leader FROM clans'))
        self.event('weekly',captured=False,scores=[(c,leaders[c],100-c,1) for c in range(1,25)])
        with self.assertRaises(ClanRejected):self.call(b.close_week,self.week,now=self.week+10)
        rows=self.call(b.close_week,self.week,now=self.week+b.WEEK)
        self.assertEqual(len(rows),20)
        self.assertEqual([rows[i-1]['rank_per_kill'] for i in (1,2,5,6,10,11,20)],[5,4,4,3,3,2,2])
        self.assertEqual(rows,self.call(b.close_week,self.week,now=self.week+2*b.WEEK))
        with transaction(self.path) as db:
            self.assertEqual(b.rank_per_kill(db,'bob',now=self.week+b.WEEK),5)
            db.execute("DELETE FROM clan_members WHERE account='bob'")
            self.assertEqual(b.rank_per_kill(db,'bob',now=self.week+b.WEEK),0)
            db.execute("INSERT INTO clan_members(account,clan_id,permissions) VALUES ('bob',2,0)")
            self.assertEqual(b.rank_per_kill(db,'bob',now=self.week+b.WEEK),4)
            self.assertEqual(b.rank_per_kill(db,'bob',now=self.week+2*b.WEEK),0)

    def test_week_close_waits_for_unsettled_event_and_uses_authoritative_scores(self):
        final=self.event(finalized=False,captured=False)
        with self.assertRaises(ClanRejected):self.call(b.close_week,self.week,now=self.week+b.WEEK)
        with transaction(self.path) as db:
            db.execute("UPDATE warfare_events SET finalized=1,phase='FINISHED'");db.execute('INSERT INTO warfare_event_receipts VALUES (?,?,0)',('event1',json.dumps(final)))
        rows=self.call(b.close_week,self.week,now=self.week+b.WEEK)
        self.assertEqual([r['clan_id'] for r in rows],[1,2,3,4]) # equal30 ties byclanID.
        self.assertEqual(self.read('SELECT COUNT(*) FROM clan_assault_medals')[0][0],5)

    def test_pending_boosters_full_warehouse_delivery_and_serialization_rollback(self):
        self.event();self.call(b.settle_assault,'event1')
        self.assertEqual(self.call(b.deliver_prizes,'alice',capacity=0),())
        self.assertEqual(self.read("SELECT delivered FROM clan_assault_prizes WHERE account='alice'")[0][0],0)
        with patch('tio.protocol.warehouse.encode_private_warehouse_snapshot',side_effect=ValueError('serialize fixture')):
            with self.assertRaises(ValueError):self.call(b.deliver_prizes,'alice',capacity=10)
        self.assertEqual(self.read("SELECT * FROM warehouse_items WHERE account='alice'"),[])
        packets=self.call(b.deliver_prizes,'alice',capacity=10);self.assertTrue(packets)
        self.assertEqual(self.call(b.deliver_prizes,'alice',capacity=10),())
        self.assertEqual(len(WarehouseStore(self.path).items('alice')),1)
        self.assertEqual(WarehouseStore(self.path).items('alice')[0].template_id,5003)
        self.assertEqual(WarehouseStore(self.path).items('bob'),())

    def test_no_implicit_partial_transactions_or_mutable_receipts(self):
        with closing(sqlite3.connect(self.path)) as db:
            with self.assertRaises(RuntimeError):b.premium_gold_spent(db,'alice','unsafe',5)
        self.call(b.premium_gold_spent,'alice','safe',5)
        with transaction(self.path) as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM clan_benefit_receipts')

    def test_overflow_never_partially_credits_contribution_or_receipts(self):
        with transaction(self.path) as db:
            db.execute('UPDATE clans SET influence=?,credits=? WHERE id=1',(b.MAX,b.MAX))
        with self.assertRaises(ClanRejected):self.call(b.premium_gold_spent,'alice','overflow-gold',1)
        with self.assertRaises(ClanRejected):self.call(b.sales_tax,'bob','overflow-tax',2,100)
        self.assertEqual(self.read('SELECT influence,credits FROM clans WHERE id=1')[0],(b.MAX,b.MAX))
        self.assertEqual(self.read("SELECT contribution FROM clan_members WHERE account='alice'")[0][0],0)
        self.assertEqual(self.read('SELECT * FROM clan_benefit_receipts'),[])

    def test_uncontested_defense_fund_refunds_owner_without_minting_tokens(self):
        final=self.event(finalized=False,captured=False,scores=[(1,'alice',0,0),(2,'carol',0,0)])
        self.call(b.fund_defense,'alice','event1',123,'fund1')
        with transaction(self.path) as db:
            db.execute("UPDATE warfare_events SET finalized=1,phase='FINISHED'")
            db.execute('INSERT INTO warfare_event_receipts VALUES (?,?,0)',('event1',json.dumps(final)))
        result=self.call(b.settle_assault,'event1')
        self.assertEqual(result['defense_fund'],{'1':123})
        self.assertEqual(self.read('SELECT credits FROM clans WHERE id=1')[0][0],10000)
        self.assertEqual(self.read('SELECT * FROM clan_assault_prizes'),[])
        self.assertEqual(self.call(b.settle_assault,'event1'),result)

    def test_real_shared_assault_finalizer_and_benefits_join_one_transaction(self):
        from tests.test_territories import TerritoriesTests
        fixture=TerritoriesTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        pair=fixture.pair();fixture.store.settle_match(fixture.event['id'],'match-1',fixture.results(pair,kill=True),(344,280))
        fixture.now=fixture.event['ends']+1;fixture.store.sync()
        with transaction(fixture.path) as db:
            final=fixture.store.finalize(fixture.event['id'])
            bonus=b.settle_assault(db,fixture.event['id'])
            winner=final['winner_clan'];ordinary=final['influence'][str(winner)]
            self.assertEqual(db.execute('SELECT influence FROM clans WHERE id=?',(winner,)).fetchone()[0],ordinary+10000)
        with transaction(fixture.path) as db:
            self.assertEqual(b.settle_assault(db,fixture.event['id']),bonus)
            tokens=db.execute('SELECT SUM(golden) FROM range_accounts').fetchone()[0]
            self.assertEqual(tokens,len(bonus['players']))


if __name__=='__main__':unittest.main()
