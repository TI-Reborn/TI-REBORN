"""Owner marks survive shared storage, withdrawal and owner recall."""
from dataclasses import replace
import struct
import time
import unittest
from unittest.mock import patch

import test_clans as clans
from tio import bank_economy as bank
from tio.db_transaction import transaction
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import encode_item_list, decode_item_list
from tio.protocol.item_marks import metadata
from tio.protocol.warehouse_transfer import WarehouseTransfer, encode_warehouse_transfer
from tio.warehouse import WarehouseStore


class ClanMarkTests(unittest.TestCase):
    def setUp(self):
        self.fixture = clans.ClanTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        with transaction(f.path) as db:
            item = replace(f.item, unknown_u32_01=1)
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='alice'",
                       (encode_item_list(1, (item,)),))
            result = bank.mark_item(db, 'alice', item.instance_id, 1, '1234', 'test-mark', now=100)
        self.mark_id = result['mark_id']

    def deposit(self):
        f = self.fixture
        _, items = f.exchange('alice', deposits=((f.item.instance_id, 1),))
        return items[0]

    def test_withdrawal_keeps_owner_and_reclaim_returns_item(self):
        f = self.fixture
        item = self.deposit()
        with transaction(f.path) as db:
            packet = bank.project_marks(db, 'bob', f.store.warehouse_packets('bob', 1)[0], now=200)
        self.assertEqual(metadata(packet)[item.instance_id], ('Alice', 86300))
        f.rights('bob', clans.DEFAULT_RIGHTS | clans.WITHDRAW_WAREHOUSE)
        inventory, _ = f.exchange('bob', withdrawals=((item.instance_id, 1),))
        held = next(i for i in decode_item_list(inventory)[1] if i.unknown_bytes_02[2])
        with transaction(f.path) as db:
            row = bank._mark(db, 'alice', self.mark_id)
            self.assertEqual((row['holder'], row['instance']), ('bob', held.instance_id))
            bank.reclaim_marked(db, 'alice', self.mark_id, '1234', 'recall', now=300)
        self.assertEqual(WarehouseStore(f.path).items('alice')[0].unknown_bytes_02[2], 1)

    def test_owner_can_recall_directly_from_clan_storage(self):
        f = self.fixture
        self.deposit()
        with transaction(f.path) as db:
            self.assertEqual(len(bank.window_mark_rows(db, 'alice', 200)), 1)
            bank.reclaim_marked(db, 'alice', self.mark_id, '1234', 'recall', now=200)
        self.assertEqual(f.store.items('bob', 1), ())
        self.assertEqual(len(WarehouseStore(f.path).items('alice')), 1)

    def test_expiry_returns_item_and_clears_mark(self):
        f = self.fixture
        self.deposit()
        with transaction(f.path) as db:
            bank.expire_marks(db, now=86501)
        self.assertEqual(f.store.items('bob', 1), ())
        self.assertEqual(WarehouseStore(f.path).items('alice')[0].unknown_bytes_02[2], 0)

    def test_failed_deposit_rolls_back_custody_and_inventory(self):
        f = self.fixture
        before = f.pets.inventory('alice', 1)
        with patch('tio.clans.record', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.deposit()
        self.assertEqual(f.pets.inventory('alice', 1), before)
        self.assertEqual(f.store.items('bob', 1), ())
        with transaction(f.path) as db:
            self.assertEqual(bank._mark(db, 'alice', self.mark_id)['holder'], 'alice')

    def test_repeated_deposit_cannot_duplicate_marked_item(self):
        self.deposit()
        with self.assertRaises(clans.ClanRejected):
            self.deposit()
        self.assertEqual(len(self.fixture.store.items('bob', 1)), 1)

    def test_forged_mark_without_active_ledger_is_rejected(self):
        f = self.fixture
        with transaction(f.path) as db:
            db.execute("UPDATE bank_item_marks SET state='removed' WHERE id=?", (self.mark_id,))
        with self.assertRaises(clans.ClanRejected):
            self.deposit()
        self.assertEqual(f.store.items('bob', 1), ())


class ClanMarkNetworkTests(unittest.TestCase):
    def setUp(self):
        from test_native_item_marks import NativeItemMarkTests
        from tio.protocol.pet_info import decode_pet_info, encode_pet_info
        f = NativeItemMarkTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.mark()
        with transaction(f.path) as db:
            raw = db.execute("SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=1").fetchone()[0]
            pet = decode_pet_info(raw, human_equipment=True)
            pet = replace(pet, fields={**pet.fields, '0x8c4aef': 4})
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=1", (encode_pet_info(pet),))
        store = clans.ClansStore(f.path)
        store.create('alice', b'Mark Test')
        store.invite('alice', b'Bob')
        store.accept('bob', 1)
        self.fixture = f
        self.store = store

    def test_private_warehouse_lists_away_mark_and_can_recall_after_withdrawal(self):
        f = self.fixture
        peers = f.peers
        exchange = f.case.exchange_inventory_requests

        def listing(replies, holder=None):
            packets = [p for p in replies if p.startswith(b'\xc8\x29')]
            if holder is not None:
                suffix = (holder + '\0').encode('utf-16le')
                packets = [p for p in packets if p.endswith(suffix)]
            self.assertTrue(packets, 'Missing current native marked-items list')
            return packets[-1]

        exchange(peers['alice'], [b'\x69\x00'])
        deposit = WarehouseTransfer(1, 1, ((f.item.instance_id, 1),), ())
        replies = exchange(peers['alice'], [encode_warehouse_transfer(deposit)])
        deposited = listing(replies, 'Клановый склад')
        count, reference, template = struct.unpack_from('<III', deposited, 2)
        self.assertEqual((count, template), (1, f.item.template_id))
        self.assertEqual(deposited[31:-2].decode('utf-16le'), 'Клановый склад')
        self.assertEqual(WarehouseStore(f.path).items('alice'), ())

        item, = self.store.items('alice', 1)
        with transaction(f.path) as db:
            db.execute('UPDATE clan_members SET permissions=permissions|? WHERE account=?',
                       (clans.WITHDRAW_WAREHOUSE, 'bob'))
        withdraw = WarehouseTransfer(1, 1, (), ((item.instance_id, 1),))
        exchange(peers['bob'], [encode_warehouse_transfer(withdraw)])
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            packet = peers['alice'].receive()
            if packet.startswith(b'\xc8\x29') and packet.endswith('Bob\0'.encode('utf-16le')):
                break
        else:
            self.fail('Open owner warehouse did not receive the new holder')
        borrowed = listing(exchange(peers['alice'], [b'\x69\x00']), 'Bob')
        self.assertEqual(struct.unpack_from('<III', borrowed, 2), (1, reference, template))
        self.assertEqual(borrowed[31:-2].decode('utf-16le'), 'Bob')
        self.assertEqual(listing(f.send('bob', 4)), b'\xc8\x29' + bytes(4))

        recalled = listing(f.send('alice', 3, struct.pack('<IB', reference, 1)), 'Alice')
        self.assertEqual(recalled[31:-2].decode('utf-16le'), 'Alice')
        returned, = WarehouseStore(f.path).items('alice')
        self.assertEqual(returned.template_id, template)
        self.assertEqual(self.store.items('bob', 1), ())
        _, inventory, _ = decode_item_list(OwnedPetStore(f.path).inventory('bob', 1))
        self.assertFalse(any(i.unknown_bytes_02[2] for i in inventory))

    def test_peer_receives_owner_name_from_native_warehouse_query(self):
        f = self.fixture
        store = self.store
        _, items = store.exchange('alice', 1, 1, deposits=((f.item.instance_id, 1),))
        replies = f.case.exchange_inventory_requests(f.peers['bob'], [b'\x69\x01'])
        packets = [p for p in replies if p[:5] == b'\x6a\x01\0\0\0']
        self.assertTrue(any(metadata(p).get(items[0].instance_id, ('',))[0] == 'Alice' for p in packets),
                        [p.hex() for p in packets])

    def test_passive_warehouse_updates_keep_marks_after_deposit(self):
        f = self.fixture
        f.peers['alice'].send(encode_warehouse_transfer(
            WarehouseTransfer(1, 1, ((f.item.instance_id, 1),), ())))
        for account, expected_updates in (('alice', 2), ('bob', 1)):
            with self.subTest(account=account):
                updates = []
                for _ in range(256):
                    packet = f.peers[account].receive()
                    if packet[:5] == b'\x6a\x01\0\0\0' and len(packet) > 13:
                        updates.append(packet)
                        if len(updates) == expected_updates:
                            break
                self.assertEqual(len(updates), expected_updates)
                item, = self.store.items(account, 1)
                self.assertEqual(item.template_id, f.item.template_id)
                for packet in updates:
                    name, remaining = metadata(packet).get(item.instance_id, ('', 0))
                    self.assertEqual(name, 'Alice', packet.hex())
                    self.assertGreater(remaining, 0)


if __name__ == '__main__':
    unittest.main()
