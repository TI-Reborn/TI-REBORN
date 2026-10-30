"""Straight journeys at speed36, durable resume and coordinate-only rollback."""
from contextlib import closing
import math
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from tio.locations import LocationStore, MAP_SPEED, center, stop_packet, town_packets
from tio.roads import path_length, point_along


def moving(packet):
    """(x, y, next road point, final location) of a moving 1D."""
    _, _, x, y, _, tx, ty, target, final = struct.unpack('<BIiiiiiiB', packet)
    assert packet[0] == 0x1d and final == 0
    return (x, y), (tx, ty), target


class StraightTravelTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'map.sqlite3'
        self.now = [1000.0]
        self.store = LocationStore(self.path, clock=lambda: self.now[0])
        with closing(sqlite3.connect(self.path)) as db, db:
            for account in ('alice', 'bob'):
                LocationStore._save(db, account, 3, *center(3))

    def go(self, account, town, character_id=42):
        return self.store.travel(account, struct.pack('<Bii', 0x1b, *center(town)), character_id)

    def test_new_journey_keeps_the_legacy_schema_and_moves_straight(self):
        import math
        self.go('alice', 8)
        with closing(sqlite3.connect(self.path)) as db:
            columns = [r[1] for r in db.execute('PRAGMA table_info(map_journeys)')]
            route = db.execute('SELECT x,y,tx,ty,started,arrives FROM map_journeys').fetchone()
        self.assertEqual(columns, ['account','x','y','tx','ty','started','arrives'])
        self.assertAlmostEqual(route[5]-route[4], math.dist(center(3),center(8))/MAP_SPEED)

    def test_reopening_does_not_complete_a_new_journey(self):
        self.go('alice', 8)
        self.now[0] += 1
        reopened = LocationStore(self.path, clock=lambda: self.now[0])
        self.assertTrue(reopened.travelling('alice'))
        self.assertEqual(reopened.position('alice'),self.store.position('alice'))
        reopened.resume('alice',42)
        self.assertEqual(reopened.refresh('alice',42),())

    def test_speed_road_duration_resume_and_arrival_agree(self):
        road = (center(3), center(8))
        packets = self.go('alice', 8)
        with closing(sqlite3.connect(self.path)) as db:
            started, arrives = db.execute(
                'SELECT started,arrives FROM map_journeys WHERE account=?', ('alice',)).fetchone()
        self.assertEqual(MAP_SPEED, 36)
        self.assertAlmostEqual(arrives - started, path_length(road) / MAP_SPEED)
        self.assertEqual(packets[0][0], 0xf0)
        self.assertEqual(moving(packets[-1])[0], center(3))
        self.now[0] += 5
        resumed = LocationStore(self.path, clock=lambda: self.now[0])
        expected = tuple(round(v) for v in point_along(road, 5 * MAP_SPEED))
        self.assertEqual(resumed.position('alice'), expected)
        self.assertEqual(moving(resumed.resume('alice', 42)[-1])[0], expected)
        self.now[0] = arrives
        self.assertEqual(resumed.refresh('alice', 42), (stop_packet(42, *center(8)), *town_packets(8, self.path, clock=lambda: self.now[0])))
        self.assertEqual(resumed.position('alice'), center(8))
        self.assertEqual(resumed.current('alice'), 8)
        self.assertFalse(resumed.travelling('alice'))

    def test_no_corrections_between_departure_and_arrival(self):
        packets = self.go('alice', 5)
        self.assertEqual(moving(packets[-1])[1],center(5))
        for seconds in (0.1,1,3):
            self.now[0] = 1000 + seconds
            self.assertEqual(self.store.refresh('alice',42),())

    def test_two_accounts_drive_independent_routes(self):
        self.go('alice', 8, 42)
        self.go('bob', 2, 77)
        self.now[0] += 3
        alice = (center(3), center(8))
        bob = (center(3), center(2))
        self.assertEqual(self.store.position('alice'), tuple(round(v) for v in point_along(alice, 3 * MAP_SPEED)))
        self.assertEqual(self.store.position('bob'), tuple(round(v) for v in point_along(bob, 3 * MAP_SPEED)))
        for packet in self.store.refresh('bob', 77):
            self.assertEqual(struct.unpack_from('<I', packet, 1)[0], 77)
            self.assertEqual(moving(packet)[2], 2)
        self.now[0] = 1000 + path_length(bob) / MAP_SPEED
        self.assertEqual(self.store.refresh('bob', 77)[0], stop_packet(77, *center(2)))
        self.assertTrue(self.store.travelling('alice'))
        self.assertEqual(self.store.current('bob'), 2)

    def test_same_town_click_opens_it_without_a_journey(self):
        packets = self.go('alice', 3)
        self.assertEqual(packets, (stop_packet(42, *center(3)), *town_packets(3, self.path, clock=lambda: self.now[0])))
        self.assertFalse(self.store.travelling('alice'))

    def test_stop_on_the_road_continues_along_it(self):
        self.go('alice', 8)
        self.now[0] += 4
        point = self.store.position('alice')
        with closing(sqlite3.connect(self.path)) as db, db:
            LocationStore._save(db, 'alice', None, *point)
            db.execute('DELETE FROM map_journeys WHERE account=?', ('alice',))
        self.go('alice', 8)
        with closing(sqlite3.connect(self.path)) as db:
            saved = db.execute('SELECT x,y,tx,ty FROM map_journeys').fetchone()
        self.assertEqual(saved[:2],point)
        self.assertEqual(saved[2:],center(8))



class LayoutMigrationTests(unittest.TestCase):
    def test_coordinate_rollback_keeps_new_player_progress_and_legacy_inserts(self):
        from tio.world_layout import restore_legacy_layout
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'rollback.db'
            store = LocationStore(path,clock=lambda:1000)
            with closing(sqlite3.connect(path)) as db,db:
                store._save(db,'alice',3,*center(3))
                db.execute('CREATE TABLE wallets(account TEXT PRIMARY KEY,credits INTEGER)')
                db.execute("INSERT INTO wallets VALUES ('alice',200)")
                restore_legacy_layout(db)
                self.assertEqual(db.execute('SELECT credits FROM wallets').fetchone()[0],200)
                self.assertEqual(db.execute('SELECT x,y FROM character_locations').fetchone(),(-154,-318))
                db.execute('INSERT INTO map_journeys VALUES (?,?,?,?,?,?,?)',
                           ('alice',-154,-318,-368,-425,1000,1020))
                self.assertEqual(db.execute('SELECT count(*) FROM map_journeys').fetchone()[0],1)

    def test_saved_towns_and_old_journeys_move_with_the_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'legacy.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE character_locations (account TEXT PRIMARY KEY,town_id INTEGER NOT NULL,x REAL,y REAL)')
                db.execute('CREATE TABLE map_journeys (account TEXT PRIMARY KEY,x REAL NOT NULL,y REAL NOT NULL,tx INTEGER NOT NULL,ty INTEGER NOT NULL,started REAL NOT NULL,arrives REAL NOT NULL)')
                db.execute('INSERT INTO character_locations VALUES (?,?,?,?)', ('alice', 3, -154, -318))
                db.execute('INSERT INTO character_locations VALUES (?,?,?,?)', ('bob', -1, -154, -318))
                db.execute('INSERT INTO character_locations VALUES (?,?,?,?)', ('carol', -1, 10, 10))
                # Bob left old Reservation for old Denver's centre.
                db.execute('INSERT INTO map_journeys VALUES (?,?,?,?,?,?,?)', ('bob', -154, -318, -368, -425, 990, 1030))
            store = LocationStore(path, clock=lambda: 1000)
            self.assertEqual(store.position('alice'), center(3))
            self.assertEqual(store.current('alice'), 3)
            self.assertEqual(store.position('carol'), (10, 10))
            self.assertEqual(store.position('bob'), center(2))
            self.assertEqual(store.refresh('bob', 77), (stop_packet(77, *center(2)), *town_packets(2, path, clock=lambda: 1000)))
            self.assertEqual(store.current('bob'), 2)
            LocationStore(path, clock=lambda: 1000)
            self.assertEqual(store.position('alice'), center(3))


if __name__ == '__main__':
    unittest.main()
