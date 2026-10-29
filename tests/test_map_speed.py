"""Journeys follow the roads at speed36: one 1D per road turn, durable resume."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from tio.locations import LocationStore, MAP_SPEED, center, stop_packet, town_packets
from tio.roads import ROADS, path_length, point_along


def moving(packet):
    """(x, y, next road point, final location) of a moving 1D."""
    _, _, x, y, _, tx, ty, target, final = struct.unpack('<BIiiiiiiB', packet)
    assert packet[0] == 0x1d and final == 0
    return (x, y), (tx, ty), target


class RoadTravelTests(unittest.TestCase):
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

    def test_speed_road_duration_resume_and_arrival_agree(self):
        road = ROADS.plan(center(3), center(8))
        packets = self.go('alice', 8)
        with closing(sqlite3.connect(self.path)) as db:
            started, arrives, saved = db.execute(
                'SELECT started,arrives,path FROM map_journeys WHERE account=?', ('alice',)).fetchone()
        self.assertEqual(MAP_SPEED, 36)
        self.assertEqual([tuple(p) for p in json.loads(saved)], list(road))
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

    def test_one_movement_per_road_turn_with_the_final_location(self):
        road = ROADS.plan(center(3), center(5))
        sent = [moving(self.go('alice', 5)[-1])]
        arrives = 1000 + path_length(road) / MAP_SPEED
        while self.now[0] + .05 < arrives:
            self.now[0] += .05
            sent.extend(moving(packet) for packet in self.store.refresh('alice', 42))
        turns = [tuple(map(round, point)) for point in road[1:]]
        destinations = [turn for _, turn, _ in sent]
        # Every turn is sent once, in road order; legs shorter than the lead
        # merge into the next one. Nothing is sent between turns.
        self.assertEqual(destinations, sorted(set(destinations), key=turns.index))
        self.assertEqual(destinations[-1], center(5))
        self.assertGreaterEqual(len(destinations), len(turns) * 3 // 4)
        self.assertEqual({target for _, _, target in sent}, {5})

    def test_turn_is_sent_before_the_client_reaches_the_corner(self):
        road = ROADS.plan(center(3), center(5))
        self.go('alice', 5)
        corner = path_length(road[:2])
        self.now[0] = 1000 + corner / MAP_SPEED - .1
        (position, turn, _), = map(moving, self.store.refresh('alice', 42))
        self.assertEqual(turn, tuple(map(round, road[2])))
        self.assertNotEqual(position, tuple(map(round, road[1])))

    def test_two_accounts_drive_independent_routes(self):
        self.go('alice', 8, 42)
        self.go('bob', 2, 77)
        self.now[0] += 3
        alice = ROADS.plan(center(3), center(8))
        bob = ROADS.plan(center(3), center(2))
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
            saved = json.loads(db.execute('SELECT path FROM map_journeys').fetchone()[0])
        self.assertEqual(tuple(saved[0]), point)
        self.assertAlmostEqual(path_length(saved), path_length(ROADS.plan(center(3), center(8))) - 4 * MAP_SPEED, delta=2)


class LayoutMigrationTests(unittest.TestCase):
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
