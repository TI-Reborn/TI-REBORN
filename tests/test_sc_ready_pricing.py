"""Independent cost equations and authoritative SC transaction boundaries."""
import copy,json,sqlite3,struct,tempfile,unittest
from fractions import Fraction as F
from pathlib import Path
from contextlib import closing
from tio.sc_pricing import expected_self_upgrade_cost,ReadySCPrices,migrate_carts
from tio.shop_completion import ShopCompletion,CompletedSCShopStore
from tests import test_credits_only as fixtures
sc=fixtures.sc

ROOT=Path(__file__).resolve().parents[1]
RULES=json.loads((ROOT/'config/enhancement.json').read_text())
POLICY=json.loads((ROOT/'config/shop_completion.json').read_text())

def reference_cost(base,kit,target,rules,special):
    """Solve absorbing-state equations independently of the pricing recurrence."""
    matrix=[[F(0) for _ in range(target+1)] for _ in range(target)]
    for i in range(target):
        p=F(1) if i<rules['safe_levels'] else F(rules['weapon_success_percent'],100)
        matrix[i][i]=1;matrix[i][-1]=F(kit)
        if i+1<target:matrix[i][i+1]-=p
        fallback=max(0,i-1) if special else 0
        matrix[i][fallback]-=1-p
        if not special:matrix[i][-1]+=(1-p)*base
    for column in range(target):
        pivot=next(n for n in range(column,target) if matrix[n][column])
        matrix[column],matrix[pivot]=matrix[pivot],matrix[column]
        divisor=matrix[column][column];matrix[column]=[x/divisor for x in matrix[column]]
        for row in range(target):
            if row!=column:
                factor=matrix[row][column]
                matrix[row]=[x-factor*y for x,y in zip(matrix[row],matrix[column])]
    return base+matrix[0][-1]

class SCReadyPriceModelTests(unittest.TestCase):
    def test_expected_cost_matches_independent_absorbing_state_solution(self):
        for safe in (0,2):
            rules={**RULES,'safe_levels':safe}
            for special in (False,True):
                for level in (3,10,15):
                    with self.subTest(safe=safe,special=special,level=level):
                        actual=expected_self_upgrade_cost(6000,1050,level,rules,kind='weapon',special=special)
                        self.assertEqual(actual,reference_cost(6000,1050,level,rules,special))
    def test_guaranteed_success_is_base_plus_one_kit_per_level(self):
        rules={**RULES,'weapon_success_percent':100}
        for special in (False,True):
            self.assertEqual(expected_self_upgrade_cost(5000,1050,25,rules,kind='weapon',special=special),31250)
    def test_ordinary_destruction_requires_replacements(self):
        rules={**RULES,'weapon_success_percent':50}
        self.assertEqual(expected_self_upgrade_cost(100,10,10,rules,kind='weapon',special=False),35820)
        self.assertEqual(expected_self_upgrade_cost(100,10,10,rules,kind='weapon',special=True),920)
    def test_armor_and_weapon_use_their_own_success_chances(self):
        rules={**RULES,'weapon_success_percent':50,'armor_success_percent':100}
        self.assertEqual(expected_self_upgrade_cost(100,10,10,rules,kind='armor',special=False),200)
        self.assertGreater(expected_self_upgrade_cost(100,10,10,rules,kind='weapon',special=False),200)
    def test_se_prices_include_tier_premium_rounded_up(self):
        prices=ReadySCPrices(POLICY['sc']['ready_price'],RULES,POLICY['sc']['enhancements'])
        self.assertEqual([prices.quote(6000,1050,n,kind='armor',special=True) for n in (0,10,15,20,25)],
                         [6000,54400,98700,153100,217700])
    def test_unreachable_upgrade_and_client_overflow_are_rejected(self):
        with self.assertRaises(ValueError):expected_self_upgrade_cost(100,10,10,{**RULES,'weapon_success_percent':0},kind='weapon',special=False)
        prices=ReadySCPrices(POLICY['sc']['ready_price'],RULES,POLICY['sc']['enhancements'])
        with self.assertRaises(ValueError):prices.quote(2_000_000_000,1050,25,kind='weapon',special=False)
    def test_invalid_premiums_and_fall_back_rule_are_rejected(self):
        policy=copy.deepcopy(POLICY['sc']['ready_price']);policy['total_percent_by_level']['10']=100
        with self.assertRaises(ValueError):ReadySCPrices(policy,RULES,POLICY['sc']['enhancements'])
        with self.assertRaises(ValueError):expected_self_upgrade_cost(100,10,10,{**RULES,'se_failure_level_loss':2},kind='armor',special=True)

class SCReadyPurchaseTests(unittest.TestCase):
    setUp=fixtures.CreditsOnlyTests.setUp
    wallet=fixtures.CreditsOnlyTests.wallet
    inventory=fixtures.CreditsOnlyTests.inventory
    def offer(self,item,level):return next(o for o in self.sc.offers.values() if o.item_id==item and o.enhancement==level)
    def test_se_direct_purchase_has_full_durability_and_deduplicated_credit_receipt(self):
        o=self.offer(248,10);self.assertEqual(o.credits,54400)
        self.sc.handle('alice',sc(6,o.lot_id,1,1),identity='sc-ready-direct')
        self.assertEqual(self.wallet(),(45600,0));self.assertEqual(self.wallet('bob'),(100000,0))
        item=decode_items(self.inventory())[0]
        self.assertEqual((item.unknown_bytes_03[0],item.unknown_words),(10,(1000,)*3))
        before=self.inventory();self.sc.handle('alice',sc(6,o.lot_id,1,1),identity='sc-ready-direct')
        self.assertEqual(self.inventory(),before);self.assertEqual(self.wallet(),(45600,0))
    def test_insufficient_funds_do_not_change_basket_inventory_or_receipt(self):
        o=self.offer(248,15);self.sc.handle('alice',sc(9,o.lot_id))
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE wallets SET credits=98699 WHERE account='alice'")
        before=self.inventory()
        with self.assertRaises(ValueError):self.sc.handle('alice',sc(11,1,1),identity='sc-ready-poor')
        self.assertEqual(self.inventory(),before);self.assertEqual(self.wallet(),(98699,0))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT quantity FROM sc_cart WHERE account='alice'").fetchone()[0],1)
            self.assertFalse(db.execute("SELECT 1 FROM sc_receipts WHERE identity='sc-ready-poor'").fetchone())
    def test_cart_sum_above_native_limit_rolls_back_the_addition(self):
        o=self.offer(315,25)
        self.sc.handle('alice',sc(9,o.lot_id))
        with self.assertRaises(ValueError):self.sc.handle('alice',sc(9,o.lot_id))
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute("SELECT quantity FROM sc_cart WHERE account='alice'").fetchone()[0],1)
    def test_old_price_lot_cannot_be_purchased_after_revision(self):
        o=self.offer(248,10);old=o.lot_id-0x1000000
        before=self.inventory()
        for request in (sc(6,old,1,1),sc(9,old)):
            with self.assertRaises(ValueError):self.sc.handle('alice',request)
        self.assertEqual(self.inventory(),before);self.assertEqual(self.wallet(),(100000,0))
    def test_price_revision_does_not_reset_shared_ordinary_shop_stock(self):
        o=self.offer(248,10)
        self.assertEqual((o.lot_id>>24)&15,3);self.assertEqual(self.sc.completion.policy['version'],2)
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('INSERT INTO shop_global_stock VALUES (2,2,0,81,3,0,NULL)')
        CompletedSCShopStore(self.path)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT quantity FROM shop_global_stock').fetchone()[0],3)
    def test_every_enhanced_offer_exceeds_expected_self_upgrade_and_base_offers_stay_unchanged(self):
        c=self.sc.completion
        for o in self.sc.offers.values():
            if o.item_id not in c.enhancement.items:continue
            base=c.prices[o.item_id]['credits'];rule=c.enhancement.items[o.item_id]
            expected=expected_self_upgrade_cost(base,1050,o.enhancement,c.enhancement.config,kind=rule['kind'],special=rule['special'])
            if o.enhancement:self.assertGreaterEqual(o.credits,expected*F(c.ready_prices.percent[o.enhancement],100))
            else:self.assertEqual(o.credits,base)
            self.assertEqual((o.base_credits,o.base_gold,o.gold),(o.credits,0,0))
    def test_migration_only_invalidates_quotes_and_is_idempotent(self):
        o=self.offer(248,10);self.sc.handle('alice',sc(9,o.lot_id))
        original_wallet=self.wallet();original_inventory=self.inventory()
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');receipt=migrate_carts(db)
            self.assertEqual(len(receipt['cancelled_quotes']['sc_cart']),1)
            self.assertFalse(db.execute('SELECT 1 FROM sc_cart').fetchone())
        self.sc.handle('bob',sc(9,o.lot_id))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self.assertEqual(migrate_carts(db),receipt)
            self.assertEqual(db.execute('SELECT account FROM sc_cart').fetchone()[0],'bob')
        self.assertEqual(self.wallet(),original_wallet);self.assertEqual(self.inventory(),original_inventory)

def decode_items(packet):
    from tio.protocol.item_list import decode_item_list
    return decode_item_list(packet)[1]
