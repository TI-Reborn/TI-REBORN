from contextlib import closing
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from tio.warehouse import WarehouseStore, WarehouseRejected
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import decode_item_list, encode_item_list


class WarehouseStoreTests(unittest.TestCase):
    def seed_stack(self):
        item=replace(self.items[0],unknown_u32_01=10,unknown_words=(123,234,345))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=?',(encode_item_list(1,(item,)),))
        return item

    def test_partial_deposit_and_withdraw_conserve_metadata_and_quantity(self):
        item=self.seed_stack()
        inv,stored=self.store.exchange('alice',1,deposits=((1001,4),))
        self.assertEqual(decode_item_list(inv)[1],(replace(item,unknown_u32_01=6),))
        self.assertEqual(stored,(replace(item,instance_id=1002,unknown_u32_01=4),))
        inv,stored=self.store.exchange('alice',1,withdrawals=((1002,2),))
        self.assertEqual(stored,(replace(item,instance_id=1002,unknown_u32_01=2),))
        items=decode_item_list(inv)[1]
        self.assertEqual(items[-1],replace(item,instance_id=1003,unknown_u32_01=2))
        self.assertEqual(sum(i.count for i in (*items,*stored)),10)
        self.assertEqual(WarehouseStore(self.path).items('alice'),stored)

    def test_partial_withdraw_does_not_free_a_slot(self):
        self.seed_stack()
        self.store.exchange('alice',1,deposits=((1001,4),))
        before=self.pets.inventory('alice',1),self.store.items('alice')
        with self.assertRaises(WarehouseRejected):
            self.store.exchange('alice',1,deposits=((1001,1),),withdrawals=((1002,1),))
        self.assertEqual((self.pets.inventory('alice',1),self.store.items('alice')),before)

    def test_failed_split_rolls_back_quantity_and_id_allocation(self):
        item=self.seed_stack()
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER reject_split BEFORE INSERT ON warehouse_items BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.exchange('alice',1,deposits=((1001,4),))
        self.assertEqual(decode_item_list(self.pets.inventory('alice',1))[1],(item,))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT * FROM item_sequences').fetchall(),[])

    def test_whole_deposit_reserves_id_for_shop(self):
        self.store.exchange('alice',1,deposits=((1002,1),))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT next_id FROM item_sequences WHERE account=?',('alice',)).fetchone(),(1003,))

    def test_wire_transfer_updates_both_locations(self):
        from tio.warehouse_service import transfer_private_items
        from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer
        from tio.protocol.warehouse import decode_warehouse_list
        def transfer(first,second,kind=0):
            packet=encode_warehouse_transfer(WarehouseTransfer(kind,1,first,second))
            return transfer_private_items(self.path,'alice',packet,capacity=1)
        replies=transfer(((1001,1),),())
        self.assertEqual(decode_item_list(replies[0])[1],self.items[1:])
        self.assertEqual(decode_warehouse_list(replies[1])[3][0].instance_id,1001)
        with self.assertRaises(WarehouseRejected):transfer((),((1001,1),),1)
        replies=transfer((),((1001,1),))
        self.assertEqual(set(decode_item_list(replies[0])[1]),set(self.items))
        self.assertEqual(decode_warehouse_list(replies[1])[3],())

    def test_snapshot_segments_and_read_only_store(self):
        from tio.protocol.warehouse import encode_private_warehouse_snapshot,decode_warehouse_list
        packets=encode_private_warehouse_snapshot(self.items,segment_size=1)
        decoded=[decode_warehouse_list(p) for p in packets]
        self.assertEqual([d[:3] for d in decoded],[(0,2,0),(0,2,1)])
        self.assertEqual([d[3][0].instance_id for d in decoded],[1001,1002])
        self.assertEqual(decode_warehouse_list(encode_private_warehouse_snapshot(())[0]),(0,1,0,()))
        read_only=WarehouseStore(self.path)
        self.assertEqual(read_only.items('alice'),())
        with self.assertRaises(WarehouseRejected):read_only.exchange('alice',1,deposits=((1001,1),))
        self.assertEqual(self.pets.inventory('alice',1),self.original)

    def test_saved_item_projection_preserves_warehouse_fields(self):
        from tio.protocol.warehouse import warehouse_item_from_inventory,encode_warehouse_list,decode_warehouse_list
        original=replace(self.items[0],unknown_words=(230,300,280),
                         unknown_bytes_02=bytes((7,1,1,1)),
                         unknown_bytes_03=bytes((5,2,1)),optional_u32=123456)
        inventory=encode_item_list(1,(original,))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=?',(inventory,))
        self.store.exchange('alice',1,deposits=((1001,1),))
        item=warehouse_item_from_inventory(self.store.items('alice')[0])
        self.assertEqual((item.durability,item.max_durability,item.calculated_max_durability),(230,300,280))
        self.assertEqual((item.enhance_level,item.damage_enhance_level,item.special_enhance),(5,2,True))
        self.assertEqual((item.marked,item.rented,item.mark_time_left),(True,True,123456))
        self.assertEqual(decode_warehouse_list(encode_warehouse_list(0,1,0,(item,)))[3],(item,))
        returned,_=self.store.exchange('alice',1,withdrawals=((1001,1),))
        self.assertEqual(returned,inventory)

    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'warehouse.sqlite3'
        trial=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        pet=bytes.fromhex(trial['packet_hex'])
        owner,items,flag=decode_item_list(bytes.fromhex(trial['inventory_packet_hex']))
        self.items=(items[0],replace(items[0],instance_id=1002))
        self.original=encode_item_list(owner,self.items,flag)
        self.pets=OwnedPetStore(self.path)
        self.pets.ensure('alice',pet,self.original,human=True)
        self.store=WarehouseStore(self.path,capacity=1)

    def test_deposit_exchange_withdraw_and_reopen_preserves_data(self):
        self.store.exchange('alice',1,deposits=((1001,1),))
        self.assertEqual(WarehouseStore(self.path,capacity=1).items('alice'),self.items[:1])
        _,stored=self.store.exchange('alice',1,deposits=((1002,1),),withdrawals=((1001,1),))
        self.assertEqual(stored,self.items[1:])
        inventory,stored=self.store.exchange('alice',1,withdrawals=((1002,1),))
        self.assertEqual(stored,())
        self.assertEqual(inventory,self.original)

    def test_rejections_are_atomic(self):
        for account,pet,deposit,withdraw in (
                ('bob',1,((1001,1),),()),('alice',2,((1001,1),),()),
                ('alice',1,((1001,1),(999,1)),()),('alice',1,((1001,2),),()),
                ('alice',1,((1001,1),(1001,1)),()),('alice',1,((1001,1),(1002,1)),()),
                ('alice',1,((1001,1),),((1001,1),)),('alice',1,(),((1001,1),))):
            with self.assertRaises(WarehouseRejected):
                self.store.exchange(account,pet,deposits=deposit,withdrawals=withdraw)
            self.assertEqual(self.pets.inventory('alice',1),self.original)
            self.assertEqual(self.store.items('alice'),())

    def test_equipped_item_deposit_clears_placement_and_withdraws_to_backpack(self):
        equipped=encode_item_list(1,(replace(self.items[0],unknown_u8_01=1,location_raw=16),))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=?',(equipped,))
        inventory,stored=self.store.exchange('alice',1,deposits=((1001,1),))
        self.assertEqual(decode_item_list(inventory)[1],())
        self.assertEqual(stored,(replace(self.items[0],unknown_u8_01=0,location_raw=0),))
        inventory,stored=self.store.exchange('alice',1,withdrawals=((1001,1),))
        self.assertEqual(decode_item_list(inventory)[1],(replace(self.items[0],unknown_u8_01=0,location_raw=0),))
        self.assertEqual(stored,())

    def test_failed_equipped_deposit_keeps_equipment(self):
        equipped=encode_item_list(1,(replace(self.items[0],unknown_u8_01=1,location_raw=16),))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=?',(equipped,))
            db.execute("CREATE TRIGGER reject_equipped BEFORE INSERT ON warehouse_items BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.exchange('alice',1,deposits=((1001,1),))
        self.assertEqual(self.pets.inventory('alice',1),equipped)
        self.assertEqual(self.store.items('alice'),())

    def test_partial_equipped_deposit_does_not_change_placement_or_quantity(self):
        equipped=encode_item_list(1,(replace(self.items[0],unknown_u8_01=1,location_raw=16,unknown_u32_01=10),))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=?',(equipped,))
        with self.assertRaises(WarehouseRejected):self.store.exchange('alice',1,deposits=((1001,3),))
        self.assertEqual(self.pets.inventory('alice',1),equipped)
        self.assertEqual(self.store.items('alice'),())

    def test_storage_failure_rolls_back_inventory(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER reject_deposit BEFORE INSERT ON warehouse_items BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.exchange('alice',1,deposits=((1001,1),))
        self.assertEqual(self.pets.inventory('alice',1),self.original)
        self.assertEqual(self.store.items('alice'),())

    def test_concurrent_repeated_deposit_cannot_duplicate(self):
        def deposit(_):
            try:self.store.exchange('alice',1,deposits=((1001,1),));return True
            except WarehouseRejected:return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(deposit,range(2))),[False,True])
        self.assertEqual(self.store.items('alice'),self.items[:1])
        self.assertEqual(decode_item_list(self.pets.inventory('alice',1))[1],self.items[1:])
        self.assertEqual(self.store.items('bob'),())
