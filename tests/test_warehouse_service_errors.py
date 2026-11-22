"""Warehouse refusals reach the player as specific localized messages."""
import unittest

from tio.protocol.system_message import encode_shop_error
from tio.warehouse_completion import current_town
from tio.warehouse_service import warehouse_error_reply


class WarehouseErrorTests(unittest.TestCase):
    def test_a_location_without_a_warehouse_is_named_as_such(self):
        import sqlite3
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE character_locations (account TEXT PRIMARY KEY,town_id INTEGER NOT NULL)')
            db.execute("INSERT INTO character_locations VALUES ('a',99)")
            with self.assertRaisesRegex(ValueError, 'Склад доступен'):
                current_town(db, 'a')

    def test_legacy_location_refusal_still_has_a_specific_message(self):
        error = ValueError('Склад доступен только в городе или у входа в шахту')
        self.assertEqual(warehouse_error_reply(error),
                         encode_shop_error('склада: склад доступен только в городе или у входа в шахту'))


if __name__ == '__main__':
    unittest.main()
