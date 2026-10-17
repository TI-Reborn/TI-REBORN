"""Actual native shop mutations plus clan benefits; isolated SQLite, no GUI claim."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import json
import sqlite3
import struct
import unittest

from tio import clan_benefits as benefits,premium
from tio.clans import schema as clan_schema,ClanRejected
from tio.db_transaction import transaction
from tio.shop import ShopStore,PurchaseRejected
from tio.protocol.shop_purchase import ShopPurchase
from tio.protocol.shop_sale import ShopSale
from tio.protocol.item_list import decode_item_list


class ShopClanTests(unittest.TestCase):
    def setUp(self):
        from tests.test_shop import ShopTests
        self.f=ShopTests(methodName='runTest');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.path,self.store=self.f.path,self.f.store
        with transaction(self.path) as db:
            clan_schema(db);benefits.schema(db)
            db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB)')
            db.execute("INSERT INTO characters VALUES ('alice',1,X'416C696365')")
            db.execute("INSERT INTO clans(id,name,name_key,leader,influence,credits) VALUES (1,X'436C616E','clan','alice',10000,1000)")
            db.execute("INSERT INTO clan_members(account,clan_id,permissions) VALUES ('alice',1,0)")
            db.execute('CREATE TABLE character_locations(account TEXT PRIMARY KEY,town_id INTEGER)')
            db.execute("INSERT INTO character_locations VALUES ('alice',2)")
            db.execute('CREATE TABLE territory_claims(location INTEGER PRIMARY KEY,owner_clan INTEGER,tax_percent INTEGER,revision INTEGER)')
            db.execute('CREATE TABLE territory_claim_history(location INTEGER,revision INTEGER,owner_clan INTEGER,tax_percent INTEGER)')
            db.execute('INSERT INTO territory_claims VALUES (6,1,10,1)')
            db.execute('INSERT INTO territory_claim_history VALUES (6,1,1,10)')

    def rows(self,sql,args=()):
        with closing(sqlite3.connect(self.path)) as db:return db.execute(sql,args).fetchall()

    def metric(self,metric):
        return self.rows('SELECT value FROM achievement_counters WHERE account=? AND metric=?',('alice',metric))

    def gold(self,item=304,quantity=1,owner=1):
        offer=next(o for o in self.store.catalogs.premium_items if o.item_id==item)
        return struct.pack('<BIIIIIQI',0x78,1,offer.offer_id,quantity,owner,0,self.store.catalogs.price_revision,0)

    def purchase(self,identity=None):return self.store.purchase_premium('alice',self.gold(304,2),identity=identity)

    def state(self):
        return (self.rows('SELECT * FROM wallets'),self.rows('SELECT inventory_packet FROM owned_pets'),
                self.rows('SELECT influence,credits FROM clans'),self.rows('SELECT contribution FROM clan_members'),
                self.rows('SELECT * FROM item_sequences'),self.rows('SELECT * FROM shop_receipts'),
                self.rows('SELECT * FROM clan_benefit_receipts'))

    def test_native_gold_debit_discount_actual_contribution_and_premium_achievement(self):
        premium.purchase(self.path,'alice',premium.encode_purchase(1,10))
        result=self.purchase('order1')
        self.assertEqual((result.charged_gold,result.assets.gold),(10,9980))
        self.assertEqual(self.rows('SELECT influence FROM clans'),[(10010,)])
        self.assertEqual(self.rows('SELECT contribution FROM clan_members'),[(10,)])
        self.assertEqual(self.metric('premium_purchase'),[(1,)])
        self.assertEqual(self.metric('clan_influence'),[(10,)])
        self.assertEqual(self.metric('shop_purchase'),[])
        self.assertEqual(self.rows("SELECT event_id FROM achievement_events ORDER BY event_id"),
                         [(f'influence:gold:{result.operation_id}',),(result.operation_id,)])

    def test_explicit_retry_after_restart_and_concurrent_call_never_charges_twice(self):
        first=self.purchase('order1');before=self.state()
        self.store=ShopStore(self.path,self.store.catalogs)
        with ThreadPoolExecutor(max_workers=4) as pool:replies=list(pool.map(lambda _:self.purchase('order1'),range(4)))
        self.assertTrue(all(reply==first for reply in replies));self.assertEqual(self.state(),before)
        with self.assertRaisesRegex(PurchaseRejected,'Conflicting'):
            self.store.purchase_premium('alice',self.gold(304,1),identity='order1')
        with self.assertRaisesRegex(PurchaseRejected,'Conflicting'):
            self.store.purchase('alice',ShopPurchase(1,0,81,1),identity='order1')
        self.assertEqual(self.state(),before)

    def test_replay_returns_current_inventory_and_wallet_after_intervening_order(self):
        first=self.purchase('order1')
        later=self.store.purchase('alice',ShopPurchase(1,0,81,1),identity='order2')
        before=self.state();replay=self.purchase('order1')
        self.assertEqual((replay.operation_id,replay.charged_gold),(first.operation_id,first.charged_gold))
        self.assertEqual((replay.inventory,replay.assets),(later.inventory,later.assets))
        self.assertEqual(self.state(),before)

    def test_completed_shop_receipts_are_immutable(self):
        self.purchase('immutable');before=self.state()
        for sql in ('UPDATE shop_receipts SET charged_gold=0','DELETE FROM shop_receipts'):
            with self.assertRaises(sqlite3.IntegrityError):
                with transaction(self.path) as db:db.execute(sql)
        self.assertEqual(self.state(),before)

    def test_no_nonce_native_identical_orders_each_charge_and_have_distinct_receipts(self):
        first=self.purchase();second=self.purchase()
        self.assertNotEqual(first.operation_id,second.operation_id)
        self.assertEqual(self.rows('SELECT contribution FROM clan_members'),[(24,)])
        self.assertEqual(self.metric('premium_purchase'),[(2,)])
        self.assertEqual(self.metric('clan_influence'),[(24,)])

    def test_ordinary_purchase_subscription_and_conversion_do_not_earn_gold_shop_contribution(self):
        from tio.bank_economy import convert_gold
        ordinary=self.store.purchase('alice',ShopPurchase(1,0,81,1))
        self.assertEqual(ordinary.charged_gold,0);self.assertEqual(self.metric('shop_purchase'),[(1,)])
        premium.purchase(self.path,'alice',premium.encode_purchase(1,10))
        with transaction(self.path) as db:convert_gold(db,'alice',1,'convert1')
        self.assertEqual(self.rows('SELECT influence FROM clans'),[(10000,)])
        self.assertEqual(self.rows('SELECT contribution FROM clan_members'),[(0,)])
        self.assertEqual(self.metric('premium_purchase'),[]);self.assertEqual(self.metric('clan_influence'),[])

    def test_unclanned_paid_purchase_is_not_backfilled_by_replay_after_join(self):
        with transaction(self.path) as db:db.execute("DELETE FROM clan_members WHERE account='alice'")
        first=self.purchase('outside')
        with transaction(self.path) as db:db.execute("INSERT INTO clan_members(account,clan_id,permissions) VALUES ('alice',1,0)")
        self.assertEqual(self.purchase('outside'),first)
        self.assertEqual(self.rows('SELECT contribution FROM clan_members'),[(0,)])
        self.assertEqual(self.metric('premium_purchase'),[(1,)]);self.assertEqual(self.metric('clan_influence'),[(0,)])

    def test_achievement_fault_and_outer_action_failure_roll_back_debit_items_and_benefits(self):
        before=self.state()
        with patch('tio.achievements.event',side_effect=ValueError('achievement failure')):
            with self.assertRaises(ValueError):self.purchase('fault')
        self.assertEqual(self.state(),before)
        with self.assertRaises(RuntimeError):
            with transaction(self.path):
                self.purchase('outer-fault')
                raise RuntimeError('journal/action failure')
        self.assertEqual(self.state(),before)

    def test_contribution_overflow_rejects_entire_paid_purchase(self):
        with transaction(self.path) as db:db.execute('UPDATE clans SET influence=4294967295')
        before=self.state()
        with self.assertRaises(ClanRejected):self.purchase('overflow')
        self.assertEqual(self.state(),before)

    def test_sale_quote_is_read_only_and_real_sale_credits_net_and_safe_once(self):
        request=ShopSale(1,1001,1);before=self.path.read_bytes()
        self.assertEqual(self.store.sell('alice',request,quote=True),88)  # gross97, tax9.
        self.assertEqual(self.path.read_bytes(),before)
        result=self.store.sell('alice',request,identity='sale1')
        self.assertEqual((result.charged_credits,result.assets.credits),(-88,10088))
        self.assertEqual(self.rows('SELECT credits FROM clans'),[(1009,)])
        self.assertEqual(decode_item_list(result.inventory)[1],())
        before=self.state();self.assertEqual(self.store.sell('alice',request,identity='sale1'),result)
        self.assertEqual(self.state(),before)

    def test_partial_stack_sales_and_legacy_without_city_are_not_reused_operations(self):
        offer=next(o for o in self.store.catalogs.items[0] if o.item_id==3)
        bought=self.store.purchase('alice',ShopPurchase(1,0,offer.unknown_u32_01,1))
        stack=next(i for i in decode_item_list(bought.inventory)[1] if i.template_id==3)
        request=ShopSale(1,stack.instance_id,10)
        net=self.store.sell('alice',request,quote=True)
        first=self.store.sell('alice',request);second=self.store.sell('alice',request)
        self.assertNotEqual(first.operation_id,second.operation_id)
        self.assertEqual(second.assets.credits-first.assets.credits,net)
        self.assertEqual(next(i for i in decode_item_list(second.inventory)[1] if i.template_id==3).count,30)
        with transaction(self.path) as db:db.execute("DELETE FROM character_locations WHERE account='alice'")
        self.assertEqual(self.store.sell('alice',ShopSale(1,1001,1),quote=True),97)

    def test_seller_wallet_limit_applies_to_actual_net_not_before_tax_gross(self):
        with transaction(self.path) as db:db.execute('UPDATE wallets SET credits=?',(0xffffffff-90,))
        result=self.store.sell('alice',ShopSale(1,1001,1))
        self.assertEqual(result.assets.credits,0xffffffff-2)
        self.assertEqual(self.rows('SELECT credits FROM clans'),[(1009,)])

    def test_sale_overflow_inventory_fault_and_city_conflict_preserve_safe_and_items(self):
        request=ShopSale(1,1001,1);before=self.state()
        with self.assertRaises(PurchaseRejected):self.store.sell('alice',request,town=5)
        self.assertEqual(self.state(),before)
        with transaction(self.path) as db:
            db.execute("CREATE TRIGGER fail_inventory BEFORE UPDATE ON owned_pets BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.sell('alice',request,identity='failure')
        self.assertEqual(self.state(),before)
        with transaction(self.path) as db:
            db.execute('DROP TRIGGER fail_inventory');db.execute('UPDATE clans SET credits=4294967295')
        before=self.state()
        with self.assertRaises(ClanRejected):self.store.sell('alice',request)
        self.assertEqual(self.state(),before)

    def test_sale_outside_city_and_corrupt_claim_history_reject_without_mutation(self):
        request=ShopSale(1,1001,1)
        with transaction(self.path) as db:db.execute("UPDATE character_locations SET town_id=-1")
        before=self.state()
        with self.assertRaises(PurchaseRejected):self.store.sell('alice',request)
        self.assertEqual(self.state(),before)
        with transaction(self.path) as db:
            db.execute('UPDATE character_locations SET town_id=2');db.execute('UPDATE territory_claim_history SET tax_percent=0')
        before=self.state()
        with self.assertRaises(ClanRejected):self.store.sell('alice',request,quote=True)
        self.assertEqual(self.state(),before)


class ClanPolicyIntegrationTests(unittest.TestCase):
    def setUp(self):
        from tests.test_clan_benefits import ClanBenefitTests
        self.f=ClanBenefitTests(methodName='runTest');self.f.setUp();self.addCleanup(self.f.doCleanups)

    def test_validated_achievement_reader_retains_premium_medal_and_deduplicates_awards(self):
        with transaction(self.f.path) as db:
            db.execute('CREATE TABLE achievement_awards(account TEXT,id INTEGER,body TEXT)')
            body=json.dumps({'prizes':[{'kind':1,'value':1.1}]})
            db.executemany('INSERT INTO achievement_awards VALUES (?,?,?)',[('alice',12,body)]*2)
            db.execute('CREATE TABLE premium_accounts(account TEXT PRIMARY KEY,kind INTEGER,expires INTEGER)')
            db.execute("INSERT INTO premium_accounts VALUES ('alice',3,100)")
            db.execute("INSERT INTO clan_assault_medals VALUES ('old','alice','attack',1,'23/20')")
            self.assertEqual(str(benefits.influence_multiplier(db,'alice',now=10)),'759/400')
            self.assertEqual(str(benefits.influence_multiplier(db,'alice',now=100)),'253/200')
        first=self.f.call(benefits.settle_experience,'alice','earned',{1:1000},now=10)
        self.assertEqual(first['amount'],94)
        with transaction(self.f.path) as db:
            db.execute('INSERT INTO achievement_awards VALUES (?,?,?)',('alice',12,json.dumps({'prizes':[]})))
        before=self.f.read('SELECT influence FROM clans')
        with self.assertRaises(ValueError):self.f.call(benefits.settle_experience,'alice','conflict',{1:1000},now=10)
        self.assertEqual(self.f.read('SELECT influence FROM clans'),before)

    def test_close_week_old_unmarked_final_and_totals_never_backfill_rewards(self):
        old=self.f.event('legacy',captured=True,finalized=False)
        with transaction(self.f.path) as db:
            old.pop('benefits_version')
            db.execute("UPDATE warfare_events SET finalized=1,phase='FINISHED' WHERE id='legacy'")
            db.execute('INSERT INTO warfare_event_receipts VALUES (?,?,0)',('legacy',json.dumps(old)))
            db.execute('INSERT INTO clan_assault_totals VALUES (?,?,?,?)',('legacy',2,self.f.week,1000))
        before=self.f.read('SELECT influence FROM clans')
        self.assertEqual(self.f.call(benefits.close_week,self.f.week,now=self.f.week+benefits.WEEK),[])
        self.assertEqual(self.f.read('SELECT influence FROM clans'),before)
        self.assertEqual(self.f.read('SELECT * FROM clan_assault_prizes'),[])
        self.assertEqual(self.f.read('SELECT * FROM clan_weekly_badges'),[])

    def test_close_week_mixed_legacy_and_new_uses_only_marked_actual_scores_and_replays(self):
        old=self.f.event('legacy',captured=False,finalized=False)
        with transaction(self.f.path) as db:
            old['benefits_version']=True
            db.execute("UPDATE warfare_events SET finalized=1,phase='FINISHED' WHERE id='legacy'")
            db.execute('INSERT INTO warfare_event_receipts VALUES (?,?,0)',('legacy',json.dumps(old)))
        self.f.event('new',captured=False,scores=[(1,'alice',20,1),(2,'carol',30,1)])
        rows=self.f.call(benefits.close_week,self.f.week,now=self.f.week+benefits.WEEK)
        self.assertEqual([(r['clan_id'],r['score']) for r in rows],[(2,30),(1,20)])
        self.assertEqual(self.f.read('SELECT DISTINCT event_id FROM clan_assault_prizes'),[('new',)])
        self.assertEqual(self.f.call(benefits.close_week,self.f.week,now=self.f.week+2*benefits.WEEK),rows)

    def test_weekly_badge_fault_rolls_back_capture_prizes_medals_and_closing_receipt(self):
        self.f.event('new',captured=True)
        with transaction(self.f.path) as db:
            db.execute("CREATE TRIGGER fail_week BEFORE INSERT ON clan_weekly_badges BEGIN SELECT RAISE(ABORT,'fixture'); END")
        before=self.f.read('SELECT influence FROM clans')
        with self.assertRaises(sqlite3.IntegrityError):
            self.f.call(benefits.close_week,self.f.week,now=self.f.week+benefits.WEEK)
        self.assertEqual(self.f.read('SELECT influence FROM clans'),before)
        for table in ('clan_assault_prizes','clan_assault_medals','clan_assault_totals','clan_benefit_receipts','clan_weekly_badges','clan_weeks'):
            self.assertEqual(self.f.read('SELECT * FROM '+table),[],table)


if __name__=='__main__':unittest.main()
