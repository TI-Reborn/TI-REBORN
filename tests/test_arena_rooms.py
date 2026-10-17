import unittest
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from tio.arena_rooms import ArenaRooms
from tio.protocol.arena import ArenaCreateRequest


class ArenaRoomsTests(unittest.TestCase):
    def setUp(self):
        self.rooms = ArenaRooms()
        self.request = ArenaCreateRequest(0, 1, 2, 2, 40, 1, 1, 0, 0)

    def test_duplicate_create_and_membership_are_consistent(self):
        first = self.rooms.create(1, self.request)
        self.assertEqual(first, self.rooms.create(1, self.request))
        joined = self.rooms.join(first.room_id, 2)
        self.assertEqual(joined, self.rooms.join(first.room_id, 2))
        with self.assertRaises(ValueError): self.rooms.create(2, self.request)
        with self.assertRaises(ValueError): self.rooms.create(1, replace(self.request, map_size=2))
        self.assertEqual(self.rooms.snapshot(), (joined,))

    def test_concurrent_join_cannot_overfill(self):
        room = self.rooms.create(1, self.request)
        def attempt(character):
            try: self.rooms.join(room.room_id, character); return True
            except ValueError: return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            accepted = list(pool.map(attempt, range(2, 18)))
        self.assertEqual(sum(accepted), 1)
        self.assertEqual(len(self.rooms.snapshot()[0].members), 2)

    def test_departure_releases_members_and_never_reuses_ids(self):
        room = self.rooms.create(1, self.request)
        self.rooms.join(room.room_id, 2)
        self.assertEqual(self.rooms.leave(2), (1, 2))
        self.assertEqual(self.rooms.snapshot()[0].members, (1,))
        self.rooms.join(room.room_id, 2)
        self.assertEqual(self.rooms.leave(1), (1, 2))
        self.assertEqual(self.rooms.snapshot(), ())
        self.assertGreater(self.rooms.create(2, self.request).room_id, room.room_id)
        self.assertEqual(self.rooms.leave(1), ())

    def test_unsupported_wager_and_bad_capacity_do_not_create(self):
        for request in (replace(self.request, unknown_u32_02=100), replace(self.request, players_count=0), replace(self.request, players_count=9)):
            with self.assertRaises(ValueError): self.rooms.create(1, request)
        self.assertEqual(self.rooms.snapshot(), ())
