"""Pending achievements cannot disconnect a player outside a city."""
from contextlib import closing
from pathlib import Path
import sqlite3
import struct
import time
import unittest

from tio.achievements import AchievementStore, update
from tio.locations import LocationStore, center, MINE_LOCATIONS
from tio.protocol.system_message import encode_current_town
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore


class NoncityDeliveryTests(unittest.TestCase):
    def setUp(self):
        from test_achievements import AchievementTests
        self.case = AchievementTests(); self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.path = self.case.path
        self.store = self.case.store
        self.locations = LocationStore(self.path)
        with closing(sqlite3.connect(self.path)) as db, db:
            update(db, 'alice', add={'melee_kills': 10, 'kills': 10})

    def dump(self):
        with closing(sqlite3.connect(self.path)) as db:
            return tuple(db.iterdump())

    def location(self, town):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT OR REPLACE INTO character_locations VALUES (?,?,?,?)',
                       ('alice', town, 0, 0))

    def test_defer_in_range_mine_base_map_and_prison_without_changing_receipts(self):
        for town in (17, next(iter(MINE_LOCATIONS)), 6, -1, 10):
            with self.subTest(town=town):
                self.location(town)
                before = self.dump()
                self.assertEqual(self.store.flush('alice'), ())
                self.assertEqual(AchievementStore(self.path).flush('alice'), ())
                self.assertEqual(self.dump(), before)

    def test_pending_rewards_survive_travel_deliver_once_in_city_and_isolate_owner(self):
        self.location(17)
        with closing(sqlite3.connect(self.path)) as db, db:
            update(db, 'bob', add={'shop_purchase': 1})
            db.execute('INSERT OR REPLACE INTO character_locations VALUES (?,?,?,?)',
                       ('bob', 3, 0, 0))
        bob = WalletStore(self.path).ensure('bob').credits
        self.assertEqual(self.store.flush('alice'), ())
        self.assertTrue(self.store.flush('bob'))
        self.assertEqual(WalletStore(self.path).ensure('bob').credits, bob + 100)
        self.location(3)
        # A persisted city ID while a journey is active is still unavailable.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO map_journeys VALUES (?,?,?,?,?,?,?)',
                       ('alice', 0, 0, 1, 1, 1, 2))
        before = self.dump()
        self.assertEqual(self.store.flush('alice'), ())
        self.assertEqual(self.dump(), before)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM map_journeys WHERE account=?', ('alice',))
        self.assertTrue(self.store.flush('alice'))
        items = WarehouseStore(self.path).items('alice')
        self.assertEqual(sorted(i.template_id for i in items), [10, 10, 317, 317, 317])
        before = self.dump()
        self.assertEqual(AchievementStore(self.path).flush('alice'), ())
        self.assertEqual(self.dump(), before)


class NoncityConnectionTests(unittest.TestCase):
    def test_two_clients_range_reconnect_pending_awards_and_city_delivery(self):
        from test_multi_account import MultiAccountTests
        from unittest.mock import patch
        case = MultiAccountTests(); case.setUp(); self.addCleanup(case.doCleanups)
        path = case.config.database
        LocationStore(path)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('INSERT OR REPLACE INTO character_locations VALUES (?,?,?,?)',
                       ('alice', 17, *center(17)))
            update(db, 'alice', add={'melee_kills': 10, 'kills': 10})
        case.start()
        alice = case.handoff(case.begin('alice')); case.enter(alice, 'Alice')
        bob = case.handoff(case.begin('bob')); case.enter(bob, 'Bob')
        before = WalletStore(path).ensure('alice').credits
        for _ in range(3):
            time.sleep(2.1); case.ping(alice); case.ping(bob)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT delivered FROM achievement_prizes WHERE account=?',
                                        ('alice',)).fetchall(), [(0,), (0,), (0,)])
        alice.sock.close()
        deadline = time.monotonic() + 5
        while 'alice' in case.server.multi.active_accounts:
            self.assertLess(time.monotonic(), deadline); time.sleep(.05)
        alice = case.handoff(case.begin('alice')); case.enter(alice, 'Alice')
        case.ping(bob); case.ping(alice)
        with patch('tio.locations.MAP_SPEED', 100000):
            alice.send(b'\x1b' + struct.pack('<ii', *center(3)))
            alice.until(encode_current_town(3), max_packets=512)
        alice.send(b'\x50\x03')
        alice.until(b'\xb5\x03', max_packets=512)
        case.ping(alice); case.ping(bob)
        self.assertEqual(WalletStore(path).ensure('alice').credits, before + 500)
        self.assertEqual(len(WarehouseStore(path).items('alice')), 5)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT delivered FROM achievement_prizes WHERE account=?',
                                       ('alice',)).fetchall(), [(1,), (1,), (1,)])
        self.assertEqual(AchievementStore(path).flush('alice'), ())


if __name__ == '__main__':
    unittest.main()
