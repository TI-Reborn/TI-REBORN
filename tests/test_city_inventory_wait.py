"""A stale city inventory read must complete without inventing a fighter."""
import json
import struct
import unittest

from tio.db_transaction import transaction
from tio.locations import LocationStore
from tio.city_inventory import city_inventory_replies
from tio.protocol.item_list import ItemRecord, encode_item_list, decode_item_list
from tio.protocol.warehouse import decode_warehouse_list
from tio.protocol.warehouse_transfer import (
    WarehouseTransfer, encode_warehouse_transfer,
)
from tio.warehouse import WarehouseStore
import test_multi_account as network


class CityInventoryWaitTests(unittest.TestCase):
    def test_stale_read_returns_the_real_primary_inventory(self):
        own = encode_item_list(1, ())
        self.assertEqual(city_inventory_replies((22,), {1: own}.get), (own,))

    def test_repeated_stale_ids_require_only_one_completion(self):
        own = encode_item_list(1, ())
        self.assertEqual(city_inventory_replies((22, 22, 23), {1: own}.get), (own,))

    def test_existing_secondary_reply_already_completes_the_read(self):
        own, secondary = encode_item_list(1, ()), encode_item_list(2, ())
        self.assertEqual(city_inventory_replies((22, 2), {1: own, 2: secondary}.get),
                         (secondary,))

    def test_absent_primary_is_not_fabricated(self):
        self.assertEqual(city_inventory_replies((22,), lambda owner: None), ())


class CityInventoryWaitTCPTests(unittest.TestCase):
    def setUp(self):
        self.case = network.MultiAccountTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.items = {}
        trial = json.loads((network.ROOT / 'evidence/owned_pet_trial.json').read_text())
        pet = bytes.fromhex(trial['packet_hex'])
        LocationStore(self.case.config.database)
        for index, (login, town) in enumerate((("alice", 13), ("bob", 3))):
            item = ItemRecord(1001 + index, 263, bytes(2), 1, 0, 0,
                              (290, 300, 300), bytes(4), None, bytes(3))
            self.items[login] = item
            network.OwnedPetStore(self.case.config.database).ensure(
                login, pet, encode_item_list(1, (item,)), human=True)
            with transaction(self.case.config.database) as database:
                database.execute('INSERT INTO character_locations(account,town_id) VALUES (?,?)',
                                 (login, town))
        self.case.start()
        self.peers = {}
        for login in self.items:
            peer = self.case.handoff(self.case.begin(login))
            self.case.enter(peer, login.title())
            self.peers[login] = peer

    def collect(self, peer) -> list[bytes]:
        peer.send(b'\x70')
        packets = []
        for _ in range(256):
            packet = peer.receive()
            if packet == b'\x9e':
                return packets
            packets.append(packet)
        self.fail('Response stream did not reach the ping completion')

    def test_two_accounts_receive_only_their_own_stale_read_completion(self):
        for login, peer in self.peers.items():
            peer.send(b'\x2f' + struct.pack('<HI', 1, 0xffffffff))
            packets = self.collect(peer)
            inventories = [p for p in packets if p[:1] == b'\x30']
            self.assertIn(encode_item_list(1, (self.items[login],)), inventories)
            self.assertTrue(all(decode_item_list(p)[0] == 1 for p in inventories))
            self.assertTrue(all(decode_item_list(p)[1] == (self.items[login],)
                                for p in inventories))

    def test_armor_moves_on_first_request_after_stale_read_in_mine_and_reservation(self):
        store = WarehouseStore(self.case.config.database)
        for login, peer in self.peers.items():
            with self.subTest(account=login):
                item = self.items[login]
                peer.send(b'\x2f' + struct.pack('<HI', 1, 0xffffffff))
                self.collect(peer)
                peer.send(encode_warehouse_transfer(WarehouseTransfer(
                    0, 1, ((item.instance_id, 1),), ())))
                packets = self.collect(peer)
                stock = [decode_warehouse_list(p)[3] for p in packets if p[:1] == b'\x6a']
                self.assertTrue(any([i.instance_id for i in batch] == [item.instance_id]
                                    for batch in stock))
                self.assertEqual(store.items(login), (item,))
                self.assertEqual(decode_item_list(
                    network.OwnedPetStore(self.case.config.database).inventory(login, 1))[1], ())
                peer.send(encode_warehouse_transfer(WarehouseTransfer(
                    0, 1, (), ((item.instance_id, 1),))))
                self.collect(peer)
                self.assertEqual(store.items(login), ())
                self.assertEqual(decode_item_list(
                    network.OwnedPetStore(self.case.config.database).inventory(login, 1))[1], (item,))


if __name__ == '__main__':
    unittest.main()
