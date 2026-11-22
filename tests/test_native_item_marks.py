import json
import struct
import unittest

from tio import bank_economy as bank
from tio.db_transaction import transaction
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from tio.protocol.item_marks import metadata
from tio.warehouse import WarehouseStore
import test_multi_account as fixture


class NativeItemMarkTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.MultiAccountTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.path = self.case.config.database
        self.case.start()
        self.peers = {}
        for account in ('alice', 'bob'):
            peer = self.case.handoff(self.case.begin(account))
            self.case.enter(peer, account.title())
            self.peers[account] = peer
        self.item = ItemRecord(9001, 301, bytes(2), 1, 0, 0, (43, 55, 350),
                               bytes(4), None, bytes(3))
        with transaction(self.path) as db:
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='alice' AND pet_id=1",
                       (encode_item_list(1, (self.item,)),))
        self.pin = b'57163809'

    def send(self, account, opcode, suffix=b''):
        return self.case.exchange_inventory_requests(self.peers[account], [bytes((0xb8, opcode))+suffix])

    def mark(self):
        replies = self.send('alice', 1, struct.pack('<IH', self.item.instance_id, 0)+self.pin+b'\0')
        self.assertTrue(any(p[:2] == b'\xc8\x29' for p in replies),
                        [p[13:-2].decode('utf-16le') for p in replies if p[:2] == b'\xf0\x8a'])
        return replies

    def test_native_mark_lend_reclaim_and_pin_removal(self):
        replies = self.mark()
        marks = [metadata(p).get(self.item.instance_id, ('', 0))
                 for p in replies if p[:1] == b'\x30']
        self.assertTrue(any(name == 'Alice' and 7 * 86400 - 10 <= seconds <= 7 * 86400
                            for name, seconds in marks), marks)
        self.send('alice', 1, struct.pack('<IH', self.item.instance_id, 0)+self.pin+b'\0')
        with transaction(self.path) as db:
            self.assertEqual(db.execute("SELECT credits FROM wallets WHERE account='alice'").fetchone(), (9300,))
            mark_id, = db.execute('SELECT id FROM bank_item_marks').fetchone()
            lent = bank.lend_marked(db, 'alice', mark_id, 'bob', 'native-test-loan')
        rows = self.send('alice', 4)
        listing = next(p for p in rows if p[:2] == b'\xc8\x29')
        count, reference, template = struct.unpack_from('<III', listing, 2)
        self.assertEqual((count, template), (1, self.item.template_id))
        self.assertIn(b'\xc8\x29'+bytes(4), self.send('bob', 4))
        self.send('bob', 3, struct.pack('<IB', reference, 1))  # Other owner's list ID.
        self.assertEqual(WarehouseStore(self.path).items('bob')[0].instance_id, lent['instance'])
        self.send('alice', 3, struct.pack('<IB', reference, 1))
        self.send('alice', 3, struct.pack('<IB', reference, 1))
        item, = WarehouseStore(self.path).items('alice')
        self.assertEqual((item.unknown_words, item.unknown_bytes_02[2]), (self.item.unknown_words, 1))
        self.assertEqual(WarehouseStore(self.path).items('bob'), ())
        self.send('alice', 2, struct.pack('<I', item.instance_id)+b'0000\0')
        self.assertEqual(WarehouseStore(self.path).items('alice')[0].unknown_bytes_02[2], 1)
        self.send('alice', 2, struct.pack('<I', item.instance_id)+self.pin+b'\0')
        self.assertEqual(WarehouseStore(self.path).items('alice')[0].unknown_bytes_02[2], 0)
        with transaction(self.path) as db:
            self.assertEqual(db.execute('SELECT state FROM bank_item_marks').fetchone(), ('removed',))
        events = json.dumps(list(self.case.server.multi.active_accounts['alice'].events))
        self.assertIn('<private economy command>', events)
        self.assertNotIn(self.pin.hex(), events)

    def test_holder_can_return_to_owner_by_physical_id(self):
        self.mark()
        with transaction(self.path) as db:
            mark_id, = db.execute('SELECT id FROM bank_item_marks').fetchone()
            lent = bank.lend_marked(db, 'alice', mark_id, 'bob', 'native-test-loan')
        self.send('bob', 3, struct.pack('<IB', lent['instance'], 1))
        item, = WarehouseStore(self.path).items('alice')
        self.assertEqual(item.unknown_bytes_02[2], 1)
        self.assertEqual(WarehouseStore(self.path).items('bob'), ())
        self.assertFalse(decode_item_list(OwnedPetStore(self.path).inventory('alice', 1))[1])
