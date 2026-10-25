from wallet_fixture import fund_wallet
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from tio.rental import RentalStore, rental_tax_units, training_rental_tax, eligible_rental_items, ROOT
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.protocol.rental import decode_rental_request
from tio.protocol.asset_count import decode_asset_count
from tio.battle_rewards import settle


# Credits-only tariff (config/rental_catalog.json): +10 for 3 hours.
BASE = 1_000_000
PRICE = 3000


def request(lot=331410, hours=3, recipient=1, currency=1):
    return b'\xb4\x10'+struct.pack('<IHIB', lot, hours, recipient, currency)


class RentalTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)/'rent.db'; self.now = 1700000000
        trial = json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        self.original = bytes.fromhex(trial['inventory_packet_hex'])
        OwnedPetStore(self.path).ensure('alice',bytes.fromhex(trial['packet_hex']),self.original,human=True)
        fund_wallet(self.path, 'alice', credits=BASE, gold=0)
        self.store = RentalStore(self.path, clock=lambda:self.now)

    def saved(self):
        return OwnedPetStore(self.path).inventory('alice',1)

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as db:
            return [db.execute('SELECT * FROM '+t+' ORDER BY 1,2').fetchall()
                    for t in ('owned_pets','wallets','rentals','item_sequences','warehouse_items')]

    def test_catalog_and_purchase_persistence(self):
        packet, = self.store.handle('alice',b'\xb4\x0e')
        self.assertEqual((packet[:2],len(packet)),(b'\xb4\x0f',6+1044*19))
        inv, assets = self.store.handle('alice',request())
        self.assertEqual((decode_asset_count(assets).credits,decode_asset_count(assets).gold),(BASE-PRICE,0))
        item = decode_item_list(inv)[1][-1]
        self.assertEqual((item.template_id,item.count,item.unknown_bytes_02,item.optional_u32),(314,1,b'\x0a\0\0\1',10800))
        self.assertEqual(item.unknown_words,(950,)*3)
        self.now += 3600
        RentalStore(self.path,clock=lambda:self.now).refresh('alice')
        self.assertEqual(decode_item_list(self.saved())[1][-1].optional_u32,7200)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,BASE-PRICE)

    def test_complete_equipment_catalog_and_all_filter_combinations(self):
        import xml.etree.ElementTree as ET
        offers=tuple(self.store.offers.values())
        identities={o.item_id for o in offers}
        self.assertEqual(identities,set(eligible_rental_items(self.store.rules)))
        self.assertEqual(len(identities),87)
        self.assertTrue({301,302,303,304,310,326,255,265,266,258,259,260,261,262,335,336,341}<=identities)
        self.assertFalse(identities & {9,10,11,30,51,52,300,317,318,319,320,321,325,333,334,337,340,353,65500,65513})
        xml={int(n.get('id')):n for n in ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot()}
        for identity in identities:
            selected=[o for o in offers if o.item_id==identity]
            self.assertEqual({(o.enhancement,o.hours) for o in selected},
                             {(level,hours) for level in (10,15,20) for hours in (3,4,8,24)})
            self.assertTrue(all(o.credits>0 and o.gold==0 for o in selected))
            self.assertTrue(xml[identity].get('name'))
        self.assertLess(len(self.store.catalog),65533)

    def test_every_template_can_be_rented_with_credits_and_expires(self):
        selected=[o for o in self.store.offers.values() if o.enhancement==10 and o.hours==3]
        warehouse=WarehouseStore(self.path,capacity=100)
        # Exercise every offer without an impossible 88-item bag. The city
        # warehouse has its own slot limit, so expire the leases in batches.
        for start in range(0,len(selected),20):
            batch=selected[start:start+20]
            for offer in batch:
                with self.subTest(template=offer.item_id):
                    packet,_=self.store.handle('alice',request(offer.lot_id))
                    record=decode_item_list(packet)[1][-1]
                    self.assertEqual((record.template_id,record.unknown_bytes_03[0],record.optional_u32),(offer.item_id,10,10800))
                    self.assertEqual(record.unknown_words,(self.store.rules.items[offer.item_id]['durability']+650,)*3)
                    warehouse.exchange('alice',1,deposits=((record.instance_id,1),))
            self.assertEqual(len(warehouse.items('alice')),len(batch))
            self.now+=10800
            self.store.refresh('alice')
            self.assertEqual(self.saved(),self.original)
            self.assertEqual(warehouse.items('alice'),())
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,BASE-sum(o.credits for o in selected))

    def test_rented_miner_weapon_and_armor_receive_real_enhancement_bonus(self):
        from test_weapon_proficiency import setup,profile,change
        from tio.protocol.battle_attack import AttackRequest
        gear=[]
        for identity,level,slot in ((335,10,16),(260,20,4)):
            offer=next(o for o in self.store.offers.values() if (o.item_id,o.enhancement,o.hours)==(identity,level,3))
            packet,_=self.store.handle('alice',request(offer.lot_id))
            gear.append(replace(decode_item_list(packet)[1][-1],unknown_u8_01=1,location_raw=slot))
        p=change(profile(16),{'0x8c446f':6})
        field,combat=setup(335,packet=p)
        combat.register(1,encode_item_list(1,gear),human=True,pet_packet=p)
        field._actors[2]=replace(field.actor(2),x=2)
        combat.attack(7,AttackRequest(1,2,1))
        self.assertEqual(field.actor(2).health,921)  # (75 + 18) * 85%, truncated.
        self.assertEqual(combat.defense(1),144)  # Heavy miner body115 + bonus29.

    def test_rejections_are_atomic(self):
        before = self.snapshot()
        for packet in (request(hours=2),request(currency=2),request(currency=0),request(recipient=999),
                       request(lot=1),request()+b'\0',request()[:-1]):
            with self.subTest(packet=packet),self.assertRaises(ValueError):self.store.handle('alice',packet)
            self.assertEqual(self.snapshot(),before)
        with self.assertRaises(ValueError):self.store.handle('bob',request())
        with self.assertRaises(ValueError):self.store.handle('alice',request(),allow_mutation=False)
        self.assertEqual(self.snapshot(),before)
        for packet in (b'',b'\xb4',b'\xb4\x0e\0',b'\xb4\xff'):
            with self.assertRaises(ValueError):decode_rental_request(packet)

    def test_insufficient_credits_and_database_rollback(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE wallets SET credits=?',(PRICE-1,))
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'Insufficient credits'):self.store.handle('alice',request())
        self.assertEqual(self.snapshot(),before)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE wallets SET credits=?',(BASE,))
            db.execute("CREATE TRIGGER reject_rental BEFORE INSERT ON rentals BEGIN SELECT RAISE(ABORT,'test'); END")
        before=self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):self.store.handle('alice',request())
        self.assertEqual(self.snapshot(),before)

    def test_concurrent_purchases_reserve_distinct_ids(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies=list(pool.map(lambda _:self.store.handle('alice',request()),range(2)))
        items=decode_item_list(self.saved())[1]
        self.assertEqual(len({i.instance_id for i in items}),3)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,BASE-2*PRICE)

    def test_expiry_boundary_and_battle_deferral(self):
        self.store.handle('alice',request())
        self.now += 10799
        self.assertEqual(self.store.refresh('alice'),())
        self.assertEqual(decode_item_list(self.saved())[1][-1].optional_u32,1)
        self.now += 1
        before=self.snapshot()
        self.assertEqual(self.store.refresh('alice',in_battle=True),())
        self.assertEqual(self.snapshot(),before)
        replies=self.store.refresh('alice')
        self.assertEqual(replies,(self.original,))
        self.assertEqual(self.saved(),self.original)
        self.assertEqual(self.store.refresh('alice'),())
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,BASE-PRICE)

    def test_warehouse_transfer_preserves_deadline_and_expires_offline(self):
        self.store.handle('alice',request())
        item=decode_item_list(self.saved())[1][-1]
        warehouse=WarehouseStore(self.path,capacity=200)
        warehouse.exchange('alice',1,deposits=((item.instance_id,1),))
        self.now += 3600
        self.store.refresh('alice')
        self.assertEqual(warehouse.items('alice')[0].optional_u32,7200)
        warehouse.exchange('alice',1,withdrawals=((item.instance_id,1),))
        self.assertEqual(decode_item_list(self.saved())[1][-1].instance_id,item.instance_id)
        warehouse.exchange('alice',1,deposits=((item.instance_id,1),))
        self.now += 7200
        replies=RentalStore(self.path,clock=lambda:self.now).refresh('alice')
        self.assertEqual(replies[0][0],0x6a)
        self.assertEqual(warehouse.items('alice'),())
        self.assertEqual(self.saved(),self.original)

    def test_rented_item_cannot_be_upgraded(self):
        from tio.enhancement import EnhancementStore
        inv,_=self.store.handle('alice',request())
        owner,items,unknown=decode_item_list(inv)
        kit=replace(items[0],template_id=30,instance_id=9999,unknown_u8_01=0,location_raw=0)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=?',(encode_item_list(owner,items+(kit,),unknown),))
        before=self.snapshot()
        packet=b'\xc8\x2a'+struct.pack('<IBI',items[-1].instance_id,1,kit.instance_id)
        with self.assertRaises(ValueError):EnhancementStore(self.path).handle('alice',packet)
        self.assertEqual(self.snapshot(),before)

    def test_tax_and_once_only_payment(self):
        inv,_=self.store.handle('alice',request())
        item=decode_item_list(inv)[1][-1]
        equipped=replace(item,unknown_u8_01=1,location_raw=16)
        self.assertEqual(rental_tax_units(inv),0)
        self.assertEqual(rental_tax_units(encode_item_list(1,(equipped,))),1)
        full=replace(equipped,template_id=263,instance_id=1003,location_raw=4)
        self.assertEqual(rental_tax_units(encode_item_list(1,(full,equipped))),4)
        self.assertEqual([training_rental_tax(1000,(n,)) for n in range(5)],[0,225,450,675,900])
        self.assertEqual(training_rental_tax(1000,(4,0)),450)
        from tio.reward_policy import RewardContext
        context=RewardContext((1,), (('bob',(1,)),), True)
        self.assertEqual(settle(self.path,'alice','match',1,rental_units=(4,),reward_context=context).credits,BASE-PRICE+10)
        self.assertEqual(settle(self.path,'alice','match',1,rental_units=(4,),reward_context=context).credits,BASE-PRICE+10)
        self.assertEqual(settle(self.path,'alice','match',1).credits,BASE-PRICE+10)


if __name__=='__main__':unittest.main()
