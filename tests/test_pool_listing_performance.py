"""Per-tick list reuse must preserve city isolation and fresh admission gates."""
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import test_shared_team_arena as fixture
from tio.protocol.arena import decode_room_list
from tio.protocol.wagers import decode_room_list as decode_main,encode_join


class PoolListingTests(unittest.TestCase):
    setUp=fixture.SharedTeamTests.setUp
    create=fixture.SharedTeamTests.create
    send=fixture.SharedTeamTests.send

    def ready(self):
        rooms=(self.create(0),self.create(1))
        viewers=tuple(self.hub.identity(s) for s in self.sessions[2:])
        for q in self.hub.queues.values():q.clear()
        return rooms,viewers

    def test_same_pool_builds_once_and_checks_each_viewer_city(self):
        rooms,viewers=self.ready()
        with patch.object(self.hub,'city',wraps=self.hub.city) as city,patch.object(self.hub,'battle_list_packet',wraps=self.hub.battle_list_packet) as main,patch.object(self.hub,'list_packet',wraps=self.hub.list_packet) as groups:
            self.hub.tick()
        self.assertEqual(city.call_count,2);self.assertEqual(main.call_count,1);self.assertEqual(groups.call_count,1)
        self.assertEqual(tuple(self.hub.queues[viewers[0]]),tuple(self.hub.queues[viewers[1]]))
        records=decode_main(next(p for p in self.hub.queues[viewers[0]] if p[:2]==b'\xc8\x2c'))
        self.assertEqual({r.identity for r in records},{r.identity for r in rooms})

    def test_pool_change_sends_deletion_and_rebuilds_next_tick(self):
        rooms,viewers=self.ready();rooms[1].pool='equipped'
        pools={viewers[0]:'starter',viewers[1]:'equipped'}
        def city(owner,levels=None):return SimpleNamespace(pool=pools[owner])
        with patch.object(self.hub,'city',side_effect=city):
            self.hub.tick()
            for viewer,room in zip(viewers,rooms):
                packet=next(p for p in self.hub.queues[viewer] if p[:2]==b'\xc8\x2c')
                self.assertEqual([r.identity for r in decode_main(packet)],[room.identity])
            for q in self.hub.queues.values():q.clear()
            pools[viewers[1]]='starter';self.now+=.25;self.hub.tick()
            packets=tuple(self.hub.queues[viewers[1]])
            self.assertIn(b'\xba\6'+rooms[1].identity.to_bytes(4,'little'),packets)
            groups=decode_room_list(next(p for p in packets if p[:2]==b'\xba\2'))
            self.assertEqual([r.unknown_u32_00 for r in groups],[rooms[0].identity])

    def test_ineligible_viewer_does_not_receive_another_viewers_cached_list(self):
        rooms,viewers=self.ready();original=self.hub.city
        def city(owner,levels=None):
            if owner==viewers[1]:raise ValueError('Not eligible')
            return original(owner,levels)
        with patch.object(self.hub,'city',side_effect=city):self.hub.tick()
        self.assertTrue(self.hub.queues[viewers[0]])
        self.assertFalse(self.hub.queues[viewers[1]])

    def test_unchanged_tick_suppresses_packets_but_new_room_is_visible(self):
        rooms,viewers=self.ready();self.hub.tick()
        for q in self.hub.queues.values():q.clear()
        with patch.object(self.hub,'battle_list_packet',wraps=self.hub.battle_list_packet) as main:self.hub.tick()
        self.assertEqual(main.call_count,0)
        self.assertTrue(all(not self.hub.queues[o] for o in viewers))
        self.send(1,b'\x2a\1');self.now+=.25;self.hub.tick()
        for owner in viewers:
            records=decode_main(next(p for p in self.hub.queues[owner] if p[:2]==b'\xc8\x2c'))
            self.assertEqual([r.identity for r in records],[rooms[0].identity])

    def test_cached_display_never_bypasses_join_after_travel(self):
        rooms,viewers=self.ready();self.hub.tick()
        self.sessions[2].locations=SimpleNamespace(current=lambda account:2)
        replies=self.send(2,encode_join(rooms[0].identity))
        self.assertTrue(any(p[:5]==b'\xf0\x8a\1\0\0' for p in replies))
        self.assertIsNone(self.hub.lobbies.room(viewers[0]))
