"""Shop-to-warehouse native contract using the actual hosted server sources."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from wallet_fixture import fund_wallet
from tio.city_catalogs import CityCatalogs
from tio.owned_pets import OwnedPetStore
from tio.shop import ShopStore
from tio.warehouse import WarehouseStore,WarehouseRejected
from tio.warehouse_queries import reply
from tio.warehouse_service import transfer_private_items
from tio.protocol.item_list import decode_item_list,encode_item_list
from tio.protocol.shop_purchase import ShopPurchase
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer,decode_warehouse_transfer
from tio.protocol.warehouse import decode_warehouse_list

ROOT=Path(__file__).resolve().parents[1]
KITS={17:600,18:1200,19:3600}


class RepairWarehouseTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'shared.sqlite3'
        pet=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        for name in ('alice','bob'):
            OwnedPetStore(self.path).ensure(name,pet,encode_item_list(1,()),human=True)
            fund_wallet(self.path,name,credits=1000000,gold=0)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE character_locations(account TEXT PRIMARY KEY,town_id INTEGER NOT NULL)')
            db.executemany('INSERT INTO character_locations VALUES (?,3)',(('alice',),('bob',)))
        self.catalog=CityCatalogs(ROOT/'config/city_catalogs.json')
        self.shop=ShopStore(self.path,self.catalog)

    def buy(self,template,name='alice'):
        offer=next(o for o in self.catalog.items[0] if o.item_id==template)
        bought=self.shop.purchase(name,ShopPurchase(1,0,offer.unknown_u32_01,1))
        return next(i for i in decode_item_list(bought.inventory)[1] if i.template_id==template)

    def transfer(self,first=(),second=(),name='alice'):
        request=WarehouseTransfer(0,1,first,second)
        packet=encode_warehouse_transfer(request)
        self.assertEqual(decode_warehouse_transfer(packet),request)
        return transfer_private_items(self.path,name,packet,capacity=32)

    def test_all_three_purchased_kits_are_sent_in_6a_and_withdraw_intact(self):
        originals=[self.buy(t) for t in KITS]
        for item in originals:self.assertEqual(item.unknown_words,(KITS[item.template_id],)*3)
        packets=self.transfer(tuple((i.instance_id,1) for i in originals))
        self.assertEqual(decode_item_list(packets[0])[1],())
        kind,total,segment,items=decode_warehouse_list(packets[1])
        self.assertEqual((kind,total,segment),(0,1,0))
        self.assertEqual([(i.instance_id,i.template_id,i.count,i.durability,i.max_durability,i.calculated_max_durability) for i in items],
                         [(i.instance_id,i.template_id,i.count,*i.unknown_words) for i in originals])
        # A fresh service/store instance reads the same saved objects. No row
        # migration or special repair-kit transfer message is needed.
        self.assertEqual(WarehouseStore(self.path).items('alice'),tuple(originals))
        self.assertEqual(reply(self.path,'alice',b'\x69\0'),packets[1:-1])
        back=self.transfer(second=tuple((i.instance_id,1) for i in originals))
        self.assertEqual(decode_item_list(back[0])[1],tuple(originals))
        self.assertEqual(decode_warehouse_list(back[1])[3],())

    def test_used_kit_keeps_resource_and_identity(self):
        original=self.buy(17);used=replace(original,unknown_words=(328,600,600))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',(encode_item_list(1,(used,)),'alice'))
        deposited=self.transfer(((used.instance_id,1),))
        shown=decode_warehouse_list(deposited[1])[3][0]
        self.assertEqual((shown.instance_id,shown.durability,shown.max_durability),(used.instance_id,328,600))
        returned=self.transfer(second=((used.instance_id,1),))
        self.assertEqual(decode_item_list(returned[0])[1],(used,))

    def test_two_accounts_share_backend_but_never_each_others_items(self):
        alice=self.buy(17);bob=self.buy(19,'bob')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda pair:self.transfer(((pair[1].instance_id,1),),name=pair[0]),(('alice',alice),('bob',bob))))
        self.assertEqual([decode_warehouse_list(p[1])[3][0].template_id for p in results],[17,19])
        self.assertEqual(WarehouseStore(self.path).items('alice'),(alice,))
        self.assertEqual(WarehouseStore(self.path).items('bob'),(bob,))
        self.assertNotEqual(reply(self.path,'alice',b'\x69\0'),reply(self.path,'bob',b'\x69\0'))

    def test_repeated_deposit_rejected_without_duplication(self):
        item=self.buy(18);self.transfer(((item.instance_id,1),))
        with self.assertRaises(WarehouseRejected):self.transfer(((item.instance_id,1),))
        self.assertEqual(WarehouseStore(self.path).items('alice'),(item,))
        self.assertEqual(decode_item_list(OwnedPetStore(self.path).inventory('alice',1))[1],())

    def test_existing_warehouse_rows_are_read_without_rewriting(self):
        originals=[self.buy(t) for t in KITS]
        self.transfer(tuple((i.instance_id,1) for i in originals))
        with closing(sqlite3.connect(self.path)) as db:before=tuple(db.iterdump())
        for _ in range(3):
            self.assertEqual(len(decode_warehouse_list(reply(self.path,'alice',b'\x69\0')[0])[3]),3)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(tuple(db.iterdump()),before)
