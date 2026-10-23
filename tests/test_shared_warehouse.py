"""One character's stock/capacity across every eligible location, without migration."""
from dataclasses import replace
from contextlib import closing
import sqlite3
import unittest

import test_mine_warehouses as fixture
from tio import warehouse_completion as stock
from tio.character_identity import alias
from tio.cities import CITIES
from tio.db_transaction import transaction
from tio.locations import MINE_LOCATIONS
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.warehouse import WarehouseStore
from tio.warehouse_resources import counts


class SharedWarehouseTests(unittest.TestCase):
    setUp = fixture.MineWarehouseTests.setUp
    move = fixture.MineWarehouseTests.move
    snapshot = fixture.MineWarehouseTests.snapshot

    def insert(self, items, town, owner='alice', bucket='city'):
        with transaction(self.path) as db:
            for item in items:
                db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',
                           (owner,item.instance_id,encode_item_list(0,(item,),7)))
                if bucket is not None:
                    db.execute('INSERT INTO warehouse_places VALUES (?,?,?,?,?)',
                               (owner,item.instance_id,bucket,town,'before-shared-release'))

    def test_all_eligible_locations_read_same_saved_stock_and_counters_without_writes(self):
        a=replace(self.kit,instance_id=501,unknown_u32_01=2)
        b=replace(self.kit,instance_id=502,template_id=17,unknown_u32_01=1,unknown_words=(328,600,600))
        c=replace(self.kit,instance_id=503,unknown_u32_01=3)
        self.insert((a,),2);self.insert((b,),13);self.insert((c,),14,bucket='overflow')
        self.insert((replace(a,instance_id=504),),3,bucket=None)
        before=self.snapshot()
        towns=sorted({*CITIES,9,*MINE_LOCATIONS})
        self.assertEqual(towns,[2,3,4,5,8,9,13,14,15,16,18])
        for town in towns:
            self.move(town)
            self.assertEqual({i.instance_id for i in self.store.items('alice')},{501,502,503,504})
            with transaction(self.path) as db:
                status=stock.status(db,'alice')
                self.assertEqual((status['used'],status['capacity'],status['accessible']),(2,32,4))
                self.assertEqual(status['scope'],'character')
                self.assertEqual(counts(db,'alice'),(328,7))
            self.assertEqual(self.snapshot(),before)

    def test_deposit_mine_withdraw_city_and_restart_keep_item_metadata_and_quantity(self):
        _,items=self.store.exchange('alice',1,deposits=((100,3),))
        saved=items[0];self.move(18)
        self.store=stock.WarehouseCompletionStore(self.path)
        packet,left=self.store.exchange('alice',1,withdrawals=((saved.instance_id,2),))
        self.assertEqual(left,(replace(saved,unknown_u32_01=1),))
        bag=decode_item_list(packet)[1]
        self.assertEqual(sum(i.count for i in bag),9)
        self.assertTrue(all(replace(i,instance_id=100,unknown_u32_01=10)==self.kit for i in bag))
        self.move(15)
        self.assertEqual(self.store.items('alice'),left)
        packet,left=self.store.exchange('alice',1,withdrawals=((saved.instance_id,1),))
        self.assertEqual(left,())
        self.move(2)
        before=self.snapshot()
        with self.assertRaises(ValueError):self.store.exchange('alice',1,withdrawals=((saved.instance_id,1),))
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(sum(i.count for i in decode_item_list(packet)[1]),10)

    def test_old_overcapacity_stock_is_not_migrated_deleted_or_allowed_to_grow(self):
        gun=replace(self.kit,template_id=301,unknown_u32_01=1,unknown_words=(300,)*3)
        self.insert(tuple(replace(gun,instance_id=1000+i) for i in range(32)),2)
        self.insert(tuple(replace(gun,instance_id=2000+i) for i in range(32)),13)
        for town in (3,14,18):
            self.move(town);before=self.snapshot()
            self.assertEqual(len(self.store.items('alice')),64)
            self.assertEqual(self.snapshot(),before)
            with self.assertRaisesRegex(ValueError,'Недостаточно места'):
                self.store.exchange('alice',1,deposits=((100,1),))
            self.assertEqual(self.snapshot(),before)
        self.store.exchange('alice',1,withdrawals=((1000,1),))
        self.assertEqual(len(self.store.items('alice')),63)

    def test_full_shared_stock_still_merges_matching_ammo_across_towns(self):
        gun=replace(self.kit,template_id=301,unknown_u32_01=1,unknown_words=(300,)*3)
        ammo=replace(self.kit,template_id=3,unknown_u32_01=50)
        self.insert(tuple(replace(gun,instance_id=1000+i) for i in range(31)),2)
        self.insert((replace(ammo,instance_id=2000),),3)
        with transaction(self.path) as db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',
                       (encode_item_list(1,(replace(ammo,instance_id=200),)),'alice'))
        self.move(16)
        _,items=self.store.exchange('alice',1,deposits=((200,20),))
        self.assertEqual(len(items),32)
        self.assertEqual(next(i for i in items if i.instance_id==2000).count,70)
        with transaction(self.path) as db:
            self.assertEqual(db.execute('SELECT town,origin FROM warehouse_places WHERE account=? AND instance_id=2000',
                                        ('alice',)).fetchone(),(3,'before-shared-release'))
        self.move(9)
        with transaction(self.path) as db:
            merged=stock.compact_all(db,'alice',WarehouseStore._read(db,'alice').values())
            self.assertEqual(sum(i.count for i in merged if i.template_id==3),70)

    def test_paid_expansion_is_one_shared_entitlement_in_every_location(self):
        from wallet_fixture import fund_wallet
        from tio.services import purchase
        import struct
        fund_wallet(self.path,'alice',credits=100000,gold=0)
        gun=replace(self.kit,template_id=301,unknown_u32_01=1,unknown_words=(300,)*3)
        self.insert(tuple(replace(gun,instance_id=1000+i) for i in range(32)),2)
        self.move(3)
        purchase(self.path,'alice',b'\xb1\x04\0'+struct.pack('<I',1)+b'\1'+struct.pack('<I',1))
        self.move(13);self.store.exchange('alice',1,deposits=((100,1),))
        self.move(18)
        with transaction(self.path) as db:
            status=stock.status(db,'alice')
            self.assertEqual((status['capacity'],status['used']),(40,33))

    def test_other_character_of_same_login_cannot_read_or_withdraw(self):
        owner=alias('alice',2)
        with closing(sqlite3.connect(self.path)) as db:
            pet=db.execute('SELECT pet_packet FROM owned_pets WHERE account=?',('alice',)).fetchone()[0]
        OwnedPetStore(self.path).ensure(owner,pet,encode_item_list(1,()),human=True)
        with transaction(self.path) as db:
            db.execute('INSERT INTO character_locations VALUES (?,13)',(owner,))
        self.store.exchange('alice',1,deposits=((100,10),))
        for stranger in ('bob',owner):
            self.assertEqual(self.store.items(stranger),())
            before=self.snapshot()
            with self.assertRaises(ValueError):self.store.exchange(stranger,1,withdrawals=((100,1),))
            self.assertEqual(self.snapshot(),before)


if __name__=='__main__':unittest.main()
