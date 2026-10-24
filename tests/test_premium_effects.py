"""Premium effects through character, shop, combat and reward entry points."""
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from server.accounts import Accounts
from tio import premium
from tio.character_identity import alias
from tio.characters import CharacterStore
from tio.owned_pets import OwnedPetStore
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.item_list import encode_item_list, decode_item_list
from tio.protocol.pet_info import decode_pet_info
from tio.wallets import WalletStore
from tio.db_transaction import transaction
from tio.battle_rewards import settle, receipt
from tio.reward_policy import RewardContext
from tio.weapon_proficiency import ProficiencyRules
from test_weapon_proficiency import profile, setup
from tio.protocol.battle_attack import AttackRequest, encode_attack_request


class PremiumEffectTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'game.sqlite3';self.now=int(time.time())
        for login in ('alice','bob'):
            Accounts(self.path).create(login,'Disposable-test-password',character=login.title())
        CharacterStore(self.path).create('alice',CharacterCreateRequest(b'AliceTwo',0,(1,0,0,0)))
        self.second=alias('alice',2);self.owners=('alice',self.second,'bob')
        for owner in self.owners:
            WalletStore(self.path).ensure(owner)
            OwnedPetStore(self.path).ensure(owner,profile(10),encode_item_list(1,()),human=True)
        with transaction(self.path) as db:
            db.execute('UPDATE wallets SET credits=100000')
            db.execute('CREATE TABLE IF NOT EXISTS character_locations(account TEXT PRIMARY KEY,town_id INTEGER)')
            for owner in self.owners:
                db.execute('INSERT INTO character_locations(account,town_id) VALUES (?,2) ON CONFLICT(account) DO UPDATE SET town_id=2',(owner,))

    def buy(self,owner='alice',offer=1,now=None):
        return premium.purchase(self.path,owner,premium.encode_purchase(offer,premium.OFFERS[offer][1]),now=self.now if now is None else now)

    def rows(self,sql,args=()):
        with closing(sqlite3.connect(self.path)) as db:return db.execute(sql,args).fetchall()

    def test_subscription_read_is_shared_read_only_and_expires_for_all_slots(self):
        self.buy();before=self.path.read_bytes()
        for owner in ('alice',self.second):
            self.assertEqual(premium.current(self.path,owner,self.now),(1,86400))
            self.assertEqual(premium.current(self.path,owner,self.now+86400),(0,0))
        self.assertEqual(premium.current(self.path,'bob',self.now),(0,0))
        self.assertEqual(self.path.read_bytes(),before)
        with self.assertRaises(ValueError):premium.current(self.path,alias('bob',2),self.now)

    def test_purchase_from_second_slot_debits_its_wallet_and_extends_shared_term(self):
        first=self.buy(self.second)
        self.assertEqual(first.credits,98500)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,100000)
        self.assertEqual(self.rows('SELECT account,kind,expires FROM premium_accounts'),[('alice',1,self.now+86400)])
        self.buy('alice',now=self.now+1)  # duplicate crosses character slots
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,100000)
        self.buy('alice',3,now=self.now+10)
        for owner in ('alice',self.second):
            self.assertEqual(premium.current(self.path,owner,self.now+10),(3,172800-10))
        self.assertEqual(self.rows('SELECT account,credits FROM premium_purchases ORDER BY id'),[(self.second,1500),('alice',1500)])
        with self.assertRaises(ValueError):self.buy(alias('bob',3))
        self.assertEqual(len(self.rows('SELECT * FROM premium_purchases')),2)

    def test_real_shop_quote_and_debit_use_shared_entitlement(self):
        from tio.shop import ShopStore
        from tio.city_catalogs import CityCatalogs
        from tio.protocol.city_catalogs import decode_item_shop
        from tio.protocol.shop_purchase import ShopPurchase
        self.buy()
        store=ShopStore(self.path,CityCatalogs(Path(__file__).resolve().parents[1]/'config/city_catalogs.json'))
        shown=decode_item_shop(store.catalog(self.second,0,discounted=bool(premium.current(self.path,self.second)[0])))[1]
        ordinary=decode_item_shop(store.catalog('bob',0))[1]
        a=next(x for x in shown if x.unknown_u32_01==81)
        b=next(x for x in ordinary if x.unknown_u32_01==81)
        self.assertEqual(a.unknown_u32_03,(b.unknown_u32_03*4+4)//5)
        result=store.purchase(self.second,ShopPurchase(1,0,81,1),identity='premium-effect')
        self.assertEqual(result.charged_credits,a.unknown_u32_03)
        self.assertEqual(result.assets.credits,100000-a.unknown_u32_03)

    def test_second_slot_receives_experience_rank_and_credit_bonuses_once(self):
        from tio.level_progression import XP
        self.buy();before={o:decode_pet_info(OwnedPetStore(self.path).list(o)[0][1],human_equipment=True).fields[XP] for o in (self.second,'bob')}
        for owner,enemy in ((self.second,'bob'),('bob',self.second)):
            for _ in range(2):
                settle(self.path,owner,'shared-match',1,experience_report={1:200},rank_report={1:(10,False)},reward_context=RewardContext((10,),((enemy,(10,)),),True,2),now=self.now)
        for owner,expected,rank in ((self.second,300,30),('bob',200,20)):
            xp=decode_pet_info(OwnedPetStore(self.path).list(owner)[0][1],human_equipment=True).fields[XP]
            self.assertEqual(xp-before[owner],expected)
            self.assertEqual(self.rows('SELECT earned FROM rank_battle_audit WHERE account=?',(owner,)),[(rank,)])
        self.assertEqual(receipt(self.path,self.second,'shared-match')[0],receipt(self.path,'bob','shared-match')[0]*3//2)

    def test_anti_experience_preserves_clan_influence_and_repeat_limits(self):
        from tio.clans import schema
        from tio.level_progression import XP
        self.buy(offer=3)
        with transaction(self.path) as db:
            schema(db)
            db.execute("INSERT INTO clans(id,name,name_key,leader) VALUES (1,?,'fixture',?)",(b'FixtureClan',self.second))
            for owner in (self.second,'bob'):db.execute('INSERT INTO clan_members(account,clan_id,permissions) VALUES (?,1,0)',(owner,))
        before=decode_pet_info(OwnedPetStore(self.path).list(self.second)[0][1],human_equipment=True).fields[XP]
        for n in range(4):
            for owner,enemy in ((self.second,'bob'),('bob',self.second)):
                for _ in range(2):
                    settle(self.path,owner,'anti-'+str(n),1,experience_report={1:200},reward_context=RewardContext((10,),((enemy,(10,)),),True,2),now=self.now+n)
        after=decode_pet_info(OwnedPetStore(self.path).list(self.second)[0][1],human_equipment=True).fields[XP]
        self.assertEqual(after,before)
        # Three full contributions, then half; anti-XP must not become zero influence.
        amounts={owner:[json.loads(body)['amount'] for body, in self.rows("SELECT receipt FROM clan_benefit_receipts WHERE account=? AND operation='xp' ORDER BY identity",(owner,))] for owner in (self.second,'bob')}
        self.assertEqual(amounts[self.second],[15,15,15,7])
        self.assertEqual(amounts['bob'],[10,10,10,5])

    def test_anti_experience_checks_selected_character_location(self):
        self.buy(offer=3)
        with transaction(self.path) as db:
            db.execute("UPDATE character_locations SET town_id=3 WHERE account='alice'")
            self.assertEqual(premium.experience_multiplier(db,'alice',self.now),(1,1))
            self.assertEqual(premium.experience_multiplier(db,self.second,self.now),(0,1))
            db.execute('DELETE FROM character_locations WHERE account=?',(self.second,))
            self.assertEqual(premium.experience_multiplier(db,self.second,self.now),(0,1))

    def test_actual_combat_applies_skill_and_half_wear_on_second_slot(self):
        def fire(owner):
            field,combat=setup(packet=profile(10))
            inventory=combat.inventories[1]
            with transaction(self.path) as db:
                db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=1',(profile(10),inventory,owner))
            combat.persistence[1]=(self.path,owner)
            before=decode_item_list(inventory)[1][0].unknown_words[0]
            combat.attack(7,AttackRequest(1,5,1))
            after=decode_item_list(combat.inventories[1])[1][0].unknown_words[0]
            raw=OwnedPetStore(self.path).list(owner)[0][1]
            return ProficiencyRules().value(raw,True,'Automatic')-35,before-after
        self.buy();trained,wear=fire(self.second);normal,normal_wear=fire('bob')
        self.assertAlmostEqual(trained,normal*1.5,places=4);self.assertEqual(wear,normal_wear)
        self.buy(offer=3,now=self.now+10);anti,anti_wear=fire(self.second)
        self.assertAlmostEqual(anti,normal,places=4)
        self.assertEqual(anti_wear,(normal_wear+1)//2)


if __name__=='__main__':unittest.main()
