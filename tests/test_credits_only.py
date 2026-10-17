import json,sqlite3,struct,tempfile,unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from server.accounts import Accounts
from tio.city_catalogs import CityCatalogs
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.shop import ShopStore
from tio.shop_completion import CompletedSCShopStore
from tio.protocol.shop_purchase import ShopPurchase
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.premium_shop import decode_premium_purchase
from tio.protocol.binary import Reader
from tio.enhancement import EnhancementStore
from tio.rental import RentalStore
from tio import premium,bank_economy,market_inventory
from tio.protocol.player_trade import CURRENCIES,GOLD_ID

ROOT=Path(__file__).resolve().parents[1]
def sc(action,*fields):return bytes((0xb4,action))+b''.join(struct.pack('<I',i) for i in fields)

class CreditsOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.sqlite3'
        self.pet=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        for a in ('alice','bob'):
            Accounts(self.path).create(a,'test-only-password-123',character=a.title())
            OwnedPetStore(self.path).ensure(a,self.pet,encode_item_list(1,()),human=True)
            WalletStore(self.path).ensure(a)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE wallets SET credits=100000,gold=0')
            db.execute('CREATE TABLE character_locations(account TEXT PRIMARY KEY,town_id INTEGER NOT NULL)')
            db.executemany('INSERT INTO character_locations VALUES (?,2)',[(a,) for a in ('alice','bob')])
        self.cats=CityCatalogs(ROOT/'config/city_catalogs.json')
        self.shop=ShopStore(self.path,self.cats)
        self.sc=CompletedSCShopStore(self.path)
    def wallet(self,a='alice'):
        with closing(sqlite3.connect(self.path)) as db,db:return db.execute('SELECT credits,gold FROM wallets WHERE account=?',(a,)).fetchone()
    def inventory(self,a='alice'):return OwnedPetStore(self.path).inventory(a,1)
    def buy(self,item,a='alice',identity=None):
        offer=next(o for o in self.cats.items[0] if o.item_id==item)
        return self.shop.purchase(a,ShopPurchase(1,0,offer.unknown_u32_01,1),identity=identity)
    def test_recommended_se_prices_and_same_pack_prices(self):
        expected={248:6000,249:2200,250:3800,251:5500,252:7500,253:4800,256:18000,264:15000,266:6000}
        for i,p in expected.items():self.assertEqual(next(o.unknown_u32_03 for o in self.cats.items[0] if o.item_id==i),p)
        for o in self.cats.premium_items:
            regular=next(i for rows in self.cats.items.values() for i in rows if i.item_id==o.item_id)
            self.assertEqual((o.gold,o.pack_count,o.currency),(regular.unknown_u32_03,regular.unknown_u32_02,1))
    def test_se_purchase_spends_credits_isolated_and_repeat_receipt(self):
        first=self.buy(248,identity='owned-request-se')
        self.assertEqual(first.charged_credits,6000);self.assertEqual(first.charged_gold,0)
        self.assertEqual(self.wallet(),(94000,0));self.assertEqual(self.wallet('bob'),(100000,0))
        inv=self.inventory();self.buy(248,identity='owned-request-se')
        self.assertEqual(self.wallet(),(94000,0));self.assertEqual(self.inventory(),inv)
    def test_no_credit_purchase_when_only_gold_is_present(self):
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE wallets SET credits=0,gold=999999 WHERE account='alice'")
        before=self.inventory()
        with self.assertRaises(ValueError):self.buy(248)
        self.assertEqual(self.inventory(),before);self.assertEqual(self.wallet(),(0,999999))
    def test_premium_tab_currency_is_credits_and_spends_same_price(self):
        o=next(o for o in self.cats.premium_items if o.item_id==248)
        packet=b'\x78'+struct.pack('<IIIII',1,o.offer_id,1,1,0)+struct.pack('<QI',self.cats.price_revision,0)
        result=self.shop.purchase_premium('alice',packet,identity='elite-tab')
        self.assertEqual(result.charged_credits,6000);self.assertEqual(result.charged_gold,0)
        r=Reader(self.cats.premium_shop(0));r.read(1+4+8+1);count=r.u32()
        for _ in range(count):
            r.read(2+4+4+4+4);self.assertEqual(r.u8(),1);r.read(4+1+1+4+1+4+4+1+1)
        r.finish()
    def test_sc_both_price_pairs_credit_only(self):
        self.assertTrue(self.sc.offers)
        for o in self.sc.offers.values():self.assertEqual((o.base_gold,o.gold),(0,0));self.assertGreater(o.credits,0)
        offer=next(o for o in self.sc.offers.values() if o.item_id==248 and o.enhancement==0)
        self.sc.handle('alice',sc(6,offer.lot_id,1,1),identity='sc-credit')
        self.assertEqual(self.wallet(),(94000,0))
    def test_sc_rejects_retired_currency_without_mutation(self):
        offer=next(iter(self.sc.offers.values()));before=self.inventory()
        with self.assertRaises(ValueError):self.sc.handle('alice',sc(6,offer.lot_id,1,2))
        self.assertEqual(self.wallet(),(100000,0));self.assertEqual(self.inventory(),before)
    def test_sc_cart_and_insufficient_credit_are_atomic(self):
        offer=next(o for o in self.sc.offers.values() if o.item_id==248 and o.enhancement==0)
        self.sc.handle('alice',sc(9,offer.lot_id),identity='cart-add')
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE wallets SET credits=5999 WHERE account='alice'")
        with self.assertRaises(ValueError):self.sc.handle('alice',sc(11,1,1),identity='cart-buy')
        self.assertEqual(self.wallet(),(5999,0))
        with closing(sqlite3.connect(self.path)) as db,db:self.assertEqual(db.execute("SELECT quantity FROM sc_cart WHERE account='alice'").fetchone()[0],1)
    def test_premium_subscription_credits_and_duplicate(self):
        packet=premium.encode_purchase(1,1500)
        premium.purchase(self.path,'alice',packet,now=10000);premium.purchase(self.path,'alice',packet,now=10001)
        self.assertEqual(self.wallet(),(98500,0));self.assertEqual(self.wallet('bob'),(100000,0))
        self.assertEqual(premium.current(self.path,'alice',now=10001),(1,86399))
    def test_rental_credit_only_and_ownership(self):
        rental=RentalStore(self.path,clock=lambda:10000)
        o=next(iter(rental.offers.values()))
        self.assertGreater(o.credits,0);self.assertEqual(o.gold,0)
        packet=b'\xb4\x10'+struct.pack('<IHIB',o.lot_id,o.hours,1,1)
        rental.handle('alice',packet)
        self.assertEqual(self.wallet(),(100000-o.credits,0));self.assertEqual(self.wallet('bob'),(100000,0))
        with self.assertRaises(ValueError):rental.handle('alice',b'\xb4\x10'+struct.pack('<IHIB',o.lot_id,o.hours,1,2))
    def test_se_failure_minus_one_level_and_100_durability(self):
        self.buy(248);item=decode_item_list(self.inventory())[1][0]
        kit_result=self.buy(30)
        items=list(decode_item_list(self.inventory())[1]);items[0]=replace(item,unknown_words=(805,805,805),unknown_bytes_02=bytes((7,0,0,0)),unknown_bytes_03=bytes((7,0,1)))
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',(encode_item_list(1,items),'alice'))
        packet=b'\xc8\x2a'+struct.pack('<IBI',items[0].instance_id,1,items[1].instance_id)
        result=EnhancementStore(self.path,randbelow=lambda _:99).handle('alice',packet)
        saved=decode_item_list(self.inventory())[1][0]
        self.assertEqual(result.outcome,'weakened');self.assertEqual(result.level,6)
        self.assertEqual(saved.unknown_words,(705,705,740));self.assertEqual(saved.instance_id,item.instance_id)
        self.assertEqual(saved.unknown_bytes_03[0],6);self.assertEqual(len(decode_item_list(self.inventory())[1]),1)
    def test_se_failed_low_durability_keeps_broken_item(self):
        self.buy(248);self.buy(30);items=list(decode_item_list(self.inventory())[1])
        items[0]=replace(items[0],unknown_words=(20,80,545),unknown_bytes_02=bytes((3,0,0,0)),unknown_bytes_03=bytes((3,0,1)))
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',(encode_item_list(1,items),'alice'))
        packet=b'\xc8\x2a'+struct.pack('<IBI',items[0].instance_id,1,items[1].instance_id)
        EnhancementStore(self.path,randbelow=lambda _:99).handle('alice',packet)
        saved=decode_item_list(self.inventory())[1][0];self.assertEqual(saved.unknown_words,(0,1,480))
    def test_retired_conversion_and_gold_transfers_reject(self):
        self.assertNotIn(GOLD_ID,CURRENCIES)
        with closing(sqlite3.connect(self.path)) as db,db:
            with self.assertRaises(ValueError):bank_economy.convert_gold(db,'alice',1,'old-convert')
            with self.assertRaises(ValueError):market_inventory.credit(db,'alice',1,'gold')
            with self.assertRaises(ValueError):market_inventory.debit(db,'alice',1,'gold')
        self.assertEqual(self.wallet(),(100000,0))
    def test_concurrent_purchases_never_overspend(self):
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE wallets SET credits=6000 WHERE account='alice'")
        def buy(n):
            try:self.buy(248,identity='concurrent-'+str(n));return True
            except ValueError:return False
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(buy,range(2)))
        self.assertEqual(sum(results),1);self.assertEqual(self.wallet(),(0,0))

if __name__=='__main__':unittest.main()
