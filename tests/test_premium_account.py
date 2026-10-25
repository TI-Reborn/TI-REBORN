from wallet_fixture import fund_wallet
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import sqlite3,tempfile,time,unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from tio import premium
from tio.wallets import WalletStore
from tio.battle_rewards import settle,receipt
from tio.reward_policy import RewardContext
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.durability import wear_inventory
from test_durability import gear
from test_shop import ShopTests
from test_weapon_proficiency import profile
from tio.weapon_proficiency import ProficiencyRules


BASE=1_000_000


class PremiumTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'state.db';self.now=int(time.time())
        # Premium is sold for credits now (gold is retired); prices come from config.
        for a in ('alice','bob'):fund_wallet(self.path, a, credits=BASE, gold=0)

    def buy(self,offer=1,now=None,account='alice'):
        return premium.purchase(self.path,account,premium.encode_purchase(offer,premium.OFFERS[offer][1]),now=self.now if now is None else now)

    def test_purchase_duplicate_concurrency_extension_switch_expiry_isolation(self):
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:self.buy(),range(8)))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,BASE-premium.OFFERS[1][1])
        self.assertEqual(premium.current(self.path,'alice',self.now),(1,86400))
        self.assertEqual(premium.current(self.path,'bob',self.now),(0,0))
        self.buy(4,now=self.now+10)
        self.assertEqual(premium.current(self.path,'alice',self.now+10),(3,31*86400-10))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,BASE-premium.OFFERS[1][1]-premium.OFFERS[4][1])
        self.assertEqual(premium.current(self.path,'alice',self.now+31*86400),(0,0))
        self.buy(2,now=self.now+40*86400)
        self.assertEqual(premium.current(self.path,'alice',self.now+40*86400),(1,30*86400))
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM premium_purchases').fetchone()[0],3)

    def test_invalid_and_insufficient_funds_do_not_charge(self):
        for packet in (b'\xc8\x3a',premium.encode_purchase(1,1),premium.encode_purchase(1,10)+b'!'):
            with self.assertRaises(ValueError):premium.purchase(self.path,'alice',packet)
        short=premium.OFFERS[1][1]-1
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE wallets SET credits=? WHERE account=?',(short,'alice'))
        with self.assertRaises(ValueError):self.buy()
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,short)
        self.assertEqual(premium.current(self.path,'alice'),(0,0))

    def test_xml_prices_and_status_projection_expire(self):
        root=ET.fromstring(premium.shared_xml())
        # The native attribute is still called goldCost; it carries the credit price.
        self.assertEqual([(int(n.get('id')),int(n.get('hours')),int(n.get('goldCost'))) for n in root],
                         [(i,hours,cost) for i,(hours,cost) in premium.OFFERS.items()])
        self.assertEqual([h for h,_ in premium.OFFERS.values()],[24,720,24,720])
        self.buy()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(premium.project(db,'alice',WalletStore(self.path).ensure('alice'),self.now).optional_raw,(86400,1))
            self.assertIsNone(premium.project(db,'alice',WalletStore(self.path).ensure('alice'),self.now+86400).optional_raw)

    def test_credits_bonus_once_zero_rewards_and_expiry(self):
        self.buy()
        context=RewardContext((1,),(('bob',(1,)),),True)
        for identity,now,expected in [('first',self.now,150),('expired',self.now+86400,100)]:
            for _ in range(2):settle(self.path,'alice',identity,1,reward_context=context,now=now)
            self.assertEqual(receipt(self.path,'alice',identity),(expected,0))
        settle(self.path,'alice','training',1,now=self.now)
        self.assertEqual(receipt(self.path,'alice','training'),(0,0))

    def test_anti_experience_reservation_exception_and_expiry(self):
        self.buy(3)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE character_locations(account TEXT PRIMARY KEY,town_id INTEGER)')
            db.execute("INSERT INTO character_locations VALUES ('alice',3)")
            self.assertEqual(premium.experience_multiplier(db,'alice',self.now),(1,1))
            db.execute("UPDATE character_locations SET town_id=4")
            self.assertEqual(premium.experience_multiplier(db,'alice',self.now),(0,1))
            self.assertEqual(premium.experience_multiplier(db,'bob',self.now),(1,1))
            self.assertEqual(premium.experience_multiplier(db,'alice',self.now+86400),(1,1))

    def test_half_wear_carries_odd_units_and_skill_multiplier(self):
        inventory=encode_item_list(1,(gear(words=(300,350,350),slot=16),))
        carry={}
        for i in range(1,21):
            inventory=wear_inventory(inventory,weapon=100,weapon_ap=1,half_wear=True,remainders=carry)
            self.assertEqual(decode_item_list(inventory)[1][0].unknown_words[0],300-(i+1)//2)
        rules=ProficiencyRules();p=profile(26)
        trained=rules.train(p,True,'Automatic',5,True,multiplier=1.5)
        self.assertAlmostEqual(rules.value(trained,True,'Automatic')-35,.3,places=4)

    def test_settlement_applies_experience_and_rank_bonus_atomically(self):
        from tio.owned_pets import OwnedPetStore
        from tio.protocol.pet_info import decode_pet_info
        from tio.level_progression import XP
        store=OwnedPetStore(self.path)
        for account in ('alice','bob'):store.ensure(account,profile(),encode_item_list(1,()),human=True)
        self.buy()
        for account in ('alice','bob'):
            before=decode_pet_info(store.list(account)[0][1],human_equipment=True).fields[XP]
            for _ in range(2):settle(self.path,account,'bonus',1,experience_report={1:100},rank_report={1:(10,False)},now=self.now)
            after=decode_pet_info(store.list(account)[0][1],human_equipment=True).fields[XP]
            self.assertEqual(after-before,150 if account=='alice' else 100)
            with closing(sqlite3.connect(self.path)) as db:
                self.assertEqual(db.execute('SELECT earned FROM rank_battle_audit WHERE account=? AND match_id=?',(account,'bonus')).fetchone()[0],30 if account=='alice' else 20)


class PremiumShopTests(ShopTests):
    def test_discount_catalog_matches_charge_and_base_catalog_unchanged(self):
        premium.purchase(self.path,'alice',premium.encode_purchase(1,premium.OFFERS[1][1]))
        from tio.protocol.city_catalogs import decode_item_shop
        from tio.protocol.shop_purchase import ShopPurchase
        base=self.store.catalogs.item_shop(0)
        shown=decode_item_shop(self.store.catalogs.item_shop(0,discounted=True))[1]
        offer=next(o for o in shown if o.unknown_u32_01==81)
        result=self.store.purchase('alice',ShopPurchase(1,0,81,2))
        self.assertEqual(result.charged_credits,offer.unknown_u32_03*2)
        self.assertEqual(result.charged_credits,240)
        self.assertEqual(self.store.catalogs.item_shop(0),base)

    def test_gold_discount_rounding_matches_catalog_and_no_resale_arbitrage(self):
        from test_original_shop_prices import gold_request
        premium.purchase(self.path,'alice',premium.encode_purchase(1,premium.OFFERS[1][1]))
        result=self.store.purchase_premium('alice',gold_request(304,2))
        self.assertEqual(result.charged_gold,10)  # 6 * .8 -> 5 gold per displayed pack.
        self.assertEqual(result.assets.gold,9980)
        for items in self.store.catalogs.items.values():
            for o in items:self.assertLessEqual(o.unknown_u32_03*65//100,(o.unknown_u32_03*4+4)//5)


if __name__=='__main__':unittest.main()
