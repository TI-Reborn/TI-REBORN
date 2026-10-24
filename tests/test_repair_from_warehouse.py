"""Quick repair debits real personal-city kits atomically, without transfers."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from contextlib import closing
import sqlite3,struct,unittest
from unittest.mock import patch
from test_warehouse_resources import WarehouseResourcesTests,item
from tio.db_transaction import transaction
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.warehouse import decode_warehouse_list
from tio.repair import repair

class WarehouseRepairTests(unittest.TestCase):
    setUp=WarehouseResourcesTests.setUp
    stash=WarehouseResourcesTests.stash
    assets=WarehouseResourcesTests.assets

    def bag(self,owner='alice',extra=(),current=50,maximum=350):
        gear=replace(item(9001,301,resource=current,capacity=maximum),unknown_u8_01=1,location_raw=16)
        with transaction(self.path) as db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',(encode_item_list(1,(gear,*extra)),owner))

    def run_repair(self,owner='alice',target=9001):
        return repair(self.path,owner,b'\xc2\x03'+struct.pack('<II',1,target))

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as db:return tuple(db.iterdump())

    def test_quick_repair_without_bag_kit_debits_warehouse_and_sends_counter(self):
        self.bag();self.stash((item(1,17,resource=328,capacity=600),),town=3)
        rows=self.run_repair()
        self.assertEqual(decode_item_list(rows[0])[1][0].unknown_words,(341,341,350))
        self.assertEqual(self.store.items('alice')[0].unknown_words,(37,600,600))
        self.assertEqual(decode_asset_count(next(p for p in rows if p[:2]==b'\xc8\x39')).repair_points,37)
        self.assertEqual(decode_warehouse_list(next(p for p in rows if p[0]==0x6a))[3][0].durability,37)
        before=self.snapshot()
        with self.assertRaises(ValueError):self.run_repair()
        self.assertEqual(self.snapshot(),before)

    def test_pool_crosses_kits_and_deletes_exhausted_only(self):
        self.bag();self.stash((item(1,17,resource=100,capacity=600),item(2,18,resource=612,capacity=1200)),town=3)
        self.run_repair()
        self.assertEqual([(i.instance_id,i.unknown_words[0]) for i in self.store.items('alice')],[(2,421)])
        self.assertEqual(self.assets().repair_points,421)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT kit_id,spent FROM item_repairs ORDER BY id').fetchall(),[(1,100),(2,191)])

    def test_insufficient_pool_repairs_partially_and_empties_stock(self):
        self.bag();self.stash((item(1,17,resource=100,capacity=600),),town=3)
        rows=self.run_repair()
        self.assertEqual(decode_item_list(rows[0])[1][0].unknown_words,(150,347,350))
        self.assertEqual(self.store.items('alice'),())
        self.assertEqual(self.assets().repair_points,0)

    def test_legacy_stack_splits_preserving_units_points_location_and_ids(self):
        self.bag();self.stash((item(1,17,quantity=3,resource=600),),town=3)
        self.run_repair();stock=self.store.items('alice')
        self.assertEqual(self.assets().repair_points,1800-291)
        self.assertEqual([(i.instance_id,i.count,i.unknown_words[0]) for i in stock],[(1,2,600),(9002,1,309)])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT bucket,town FROM warehouse_places WHERE instance_id=9002').fetchone(),('city',3))

    def test_all_town_stocks_and_overflow_supply_repair_but_other_account_is_untouched(self):
        self.bag();self.bag('bob')
        self.stash((item(1,17,resource=100,capacity=600),))
        self.stash((item(2,18,resource=100,capacity=1200),),town=2,bucket='overflow')
        self.stash((item(3,19,resource=3600),),town=2)
        self.stash((item(1,19,resource=3600),),'bob',town=3)
        self.run_repair()
        self.assertEqual(self.assets().repair_points,3509)
        self.assertEqual(self.assets('bob').repair_points,3600)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT instance_id FROM warehouse_items WHERE account=?',('alice',)).fetchall(),[(3,)])

    def test_missing_stock_falls_back_to_existing_bag_repair(self):
        self.bag(extra=(item(5,17,resource=600),))
        rows=self.run_repair();self.assertEqual(len(rows),2)
        self.assertEqual(decode_item_list(rows[0])[1][1].unknown_words[0],309)

    def test_warehouse_preferred_when_bag_also_has_kit(self):
        self.bag(extra=(item(5,17,resource=600),));self.stash((item(1,17,resource=600),),town=3)
        rows=self.run_repair()
        self.assertEqual(decode_item_list(rows[0])[1][1].unknown_words[0],600)
        self.assertEqual(self.assets().repair_points,309)

    def test_failure_rolls_back_both_inventory_and_stock(self):
        self.bag();self.stash((item(1,17,resource=600),),town=3);before=self.snapshot()
        for where in ('tio.repair.record','tio.protocol.warehouse.encode_private_warehouse_snapshot','tio.protocol.asset_count.encode_asset_count'):
            with patch(where,side_effect=sqlite3.OperationalError('injected')):
                with self.assertRaises(sqlite3.OperationalError):self.run_repair()
            self.assertEqual(self.snapshot(),before)

    def test_foreign_target_and_travelling_rejected_without_spend(self):
        self.bag();self.stash((item(1,17,resource=600),),town=3);before=self.snapshot()
        with self.assertRaises(ValueError):self.run_repair(target=123)
        self.assertEqual(self.snapshot(),before)
        with transaction(self.path) as db:
            db.execute('CREATE TABLE map_journeys(account TEXT)');db.execute("INSERT INTO map_journeys VALUES ('alice')")
        before=self.snapshot()
        with self.assertRaises(ValueError):self.run_repair()
        self.assertEqual(self.snapshot(),before)

    def test_concurrent_replay_spends_once_and_accounts_remain_private(self):
        for name in ('alice','bob'):
            self.bag(name);self.stash((item(1,17,resource=600),),name,town=3)
        def attempt(name):
            try:self.run_repair(name);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(attempt,('alice','bob','alice','bob')))
        self.assertEqual(sum(results),2)
        self.assertEqual([self.assets(n).repair_points for n in ('alice','bob')],[309,309])

if __name__=='__main__':unittest.main()
