"""One allocator decides which item IDs an account already uses."""
from pathlib import Path
import re
import sqlite3
import unittest

from tio.item_ids import next_item_id, taken_item_ids
from tio.protocol.item_list import ItemRecord, encode_item_list

ROOT = Path(__file__).resolve().parents[1]


def item(identity):
    return ItemRecord(identity, 301, bytes(2), 1, 0, 0, (300,)*3, bytes(4), None, bytes(3))


class ItemIdAllocatorTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE owned_pets(account TEXT, pet_id INTEGER, inventory_packet BLOB)')

    def bag(self, account, pet, *ids):
        self.db.execute('INSERT INTO owned_pets VALUES (?,?,?)', (account, pet, encode_item_list(pet, tuple(map(item, ids)))))

    def test_every_source_is_reserved_and_other_accounts_are_ignored(self):
        self.bag('alice', 1, 3); self.bag('alice', 2, 40)  # 40: a reserve mercenary
        self.bag('bob', 1, 900)
        self.assertEqual(next_item_id(self.db, 'alice'), 41)
        self.db.execute('CREATE TABLE warehouse_items(account TEXT, instance_id INTEGER, item_packet BLOB)')
        self.db.execute('INSERT INTO warehouse_items VALUES (?,?,?)', ('alice', 70, b''))
        self.assertEqual(next_item_id(self.db, 'alice'), 71)
        self.db.execute('CREATE TABLE rentals(account TEXT, instance_id INTEGER, lot INTEGER, expires INTEGER)')
        self.db.execute('INSERT INTO rentals VALUES (?,?,?,?)', ('alice', 80, 1, 0))
        self.assertEqual(next_item_id(self.db, 'alice'), 81)
        self.db.execute('CREATE TABLE item_sequences(account TEXT PRIMARY KEY, next_id INTEGER)')
        self.db.execute('INSERT INTO item_sequences VALUES (?,?)', ('alice', 500))
        self.assertEqual(next_item_id(self.db, 'alice'), 500)
        self.assertEqual(next_item_id(self.db, 'alice', {999}), 1000)
        self.assertEqual(taken_item_ids(self.db, 'alice'), {3, 40, 70, 80})
        self.assertEqual(next_item_id(self.db, 'carol'), 1)

    def test_no_module_reads_the_sequence_on_its_own(self):
        """New ID code must go through tio.item_ids (battle items: match_id_floor)."""
        offenders = []
        for path in (*ROOT.glob('tio/**/*.py'), *ROOT.glob('server/**/*.py')):
            if path.name == 'item_ids.py': continue
            text = path.read_text(encoding='utf-8')
            if re.search(r'SELECT\s+next_id\s+FROM\s+item_sequences', text):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
