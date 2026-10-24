"""Mine checkpoint storage: scoped ownership, conservation and travel guards."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tio import warehouse_completion as completion
from tio.db_transaction import transaction
from tio.locations import MINE_LOCATIONS
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from tio.warehouse_resources import counts
from tio.warehouse import WarehouseStore

ROOT = Path(__file__).resolve().parents[1]


class MineWarehouseTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)/'players.sqlite3'
        pet = bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        self.kit = ItemRecord(100, 30, bytes(2), 10, 0, 0, (1,1,1), bytes(4), None, bytes(3))
        for owner in ('alice', 'bob'):
            OwnedPetStore(self.path).ensure(owner, pet, encode_item_list(1, (self.kit,)), human=True)
        self.store = completion.WarehouseCompletionStore(self.path)
        with transaction(self.path) as db:
            db.execute('CREATE TABLE character_locations(account TEXT PRIMARY KEY,town_id INTEGER NOT NULL)')
            db.executemany('INSERT INTO character_locations VALUES (?,13)', [('alice',),('bob',)])
            db.execute('CREATE TABLE map_journeys(account TEXT PRIMARY KEY)')

    def move(self, town, owner='alice'):
        with transaction(self.path) as db:
            db.execute('UPDATE character_locations SET town_id=? WHERE account=?', (town,owner))

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as db:
            return {t: db.execute('SELECT * FROM '+t+' ORDER BY 1,2').fetchall()
                    for t in ('owned_pets','warehouse_items','warehouse_places','item_sequences')}

    def test_all_mine_checkpoints_deposit_withdraw_and_reopen(self):
        self.assertEqual(set(MINE_LOCATIONS), {13,14,15,16})
        for town in MINE_LOCATIONS:
            with self.subTest(town=town):
                self.move(town)
                bag, warehouse = self.store.exchange('alice',1,deposits=((100,10),))
                self.assertEqual(decode_item_list(bag)[1], ())
                self.assertEqual(warehouse, (self.kit,))
                with transaction(self.path) as db:
                    status = completion.status(db,'alice')
                    self.assertEqual((status['town'], status['capacity'], status['used']), (town,32,1))
                    self.assertEqual(counts(db,'alice'), (0,10))
                reopened = completion.WarehouseCompletionStore(self.path)
                self.assertEqual(reopened.items('alice'), (self.kit,))
                packet, warehouse = reopened.exchange('alice',1,withdrawals=((100,10),))
                self.assertEqual(decode_item_list(packet)[1], (self.kit,))
                self.assertEqual(warehouse, ())

    def test_partial_stacks_are_shared_between_mines_and_city_but_accounts_are_private(self):
        allocations = []
        for town in (*MINE_LOCATIONS, 3):
            self.move(town)
            _, items = self.store.exchange('alice',1,deposits=((100,1),))
            self.assertEqual(sum(i.count for i in items),len(allocations)+1)
            allocations.append(max(i.instance_id for i in items))
            with transaction(self.path) as db:
                self.assertEqual(counts(db,'alice'),(0,len(allocations)))
        # Upgrade Kits stack: every checkpoint adds to the same shared record.
        self.assertEqual(len(set(allocations)),1)
        self.assertEqual([i.count for i in self.store.items('alice')],[5])
        for town in (*MINE_LOCATIONS, 3):
            self.move(town)
            self.assertEqual({i.instance_id for i in self.store.items('alice')},set(allocations))
            before = self.snapshot()
            self.move(town,'bob')
            self.assertEqual(self.store.items('bob'), ())
            with self.assertRaises(ValueError): self.store.exchange('bob',1,withdrawals=((allocations[0],1),))
            self.assertEqual(self.snapshot(),before)
        self.store.exchange('alice',1,withdrawals=((allocations[0],5),))
        self.move(13)
        with self.assertRaises(ValueError): self.store.exchange('alice',1,withdrawals=((allocations[0],1),))
        with closing(sqlite3.connect(self.path)) as db:
            bag = decode_item_list(db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',('alice',)).fetchone()[0])[1]
            self.assertEqual(sum(i.count for i in bag)+sum(i.count for i in WarehouseStore._read(db,'alice').values()),10)

    def test_capacity_is_shared_between_checkpoints_and_failure_is_atomic(self):
        gun = replace(self.kit, template_id=301, unknown_u32_01=1, unknown_words=(300,300,300))
        with transaction(self.path) as db:
            completion.stash(db,'alice',tuple(replace(gun,instance_id=1000+i) for i in range(32)),origin='mine-capacity-test')
        for town in (13,14,3,16):
            self.move(town)
            before = self.snapshot()
            with self.assertRaisesRegex(ValueError,'Недостаточно места'):
                self.store.exchange('alice',1,deposits=((100,1),))
            self.assertEqual(self.snapshot(),before)
            with transaction(self.path) as db:self.assertEqual(completion.status(db,'alice')['used'],32)
        self.store.exchange('alice',1,withdrawals=((1000,1),))
        self.move(14)
        self.store.exchange('alice',1,deposits=((100,1),))
        self.assertEqual(len(self.store.items('alice')),32)

    def test_world_travel_and_other_nonwarehouse_locations_stay_rejected(self):
        for town in (-1,0,6,11,12,17,19,65535):
            self.move(town)
            before = self.snapshot()
            with self.assertRaises(ValueError): self.store.exchange('alice',1,deposits=((100,1),))
            self.assertEqual(self.snapshot(),before)
        for town in MINE_LOCATIONS:
            self.move(town)
            with transaction(self.path) as db: db.execute('INSERT INTO map_journeys VALUES (?)',('alice',))
            before = self.snapshot()
            with self.assertRaises(ValueError): self.store.exchange('alice',1,deposits=((100,1),))
            self.assertEqual(self.snapshot(),before)
            with transaction(self.path) as db: db.execute('DELETE FROM map_journeys WHERE account=?',('alice',))

    def test_simultaneous_withdrawals_cannot_duplicate_an_item(self):
        self.store.exchange('alice',1,deposits=((100,10),))
        def withdraw(_):
            try:
                self.store.exchange('alice',1,withdrawals=((100,10),))
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(sorted(workers.map(withdraw, range(2))),[False,True])
        with closing(sqlite3.connect(self.path)) as db:
            bag = decode_item_list(db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',('alice',)).fetchone()[0])[1]
        self.assertEqual(bag,(self.kit,))
        self.assertEqual(self.store.items('alice'),())


if __name__ == '__main__':
    unittest.main()
