"""Several sessions must share a bounded public-list refresh cadence."""
import unittest

import test_pool_listing_performance as fixture
from tio.protocol.wagers import decode_room_list


class CityListingCadenceTests(unittest.TestCase):
    setUp = fixture.PoolListingTests.setUp
    create = fixture.PoolListingTests.create
    send = fixture.PoolListingTests.send
    ready = fixture.PoolListingTests.ready
    def test_sessions_share_one_quarter_second_publication_deadline(self):
        rooms, viewers = self.ready()
        now = [100.0]
        self.hub.clock = lambda: now[0]
        self.hub.tick()
        for q in self.hub.queues.values():
            q.clear()
        self.send(1, b'\x2a\1')
        for _ in range(10):
            self.hub.tick()
        self.assertTrue(all(not self.hub.queues[o] for o in viewers))
        now[0] += .25
        self.hub.tick()
        for owner in viewers:
            packet = next(p for p in self.hub.queues[owner] if p.startswith(b'\xc8\x2c'))
            self.assertEqual([r.identity for r in decode_room_list(packet)], [rooms[0].identity])
