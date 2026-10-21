"""Model the native merge table while exercising shared server list delivery."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_shared_wager_arena as wager
from tio.protocol.arena import ArenaCreateRequest,encode_create_request
from tio.protocol.wagers import decode_room_list,encode_room_list,encode_room_removed,encode_room_list_clear,WagerRoomRecord
from tio.protocol.binary import PacketError


class WagerListRemovalTests(unittest.TestCase):
    def setUp(self):
        self.f=wager.SharedWagerTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.hub=self.f.hub;self.viewer=self.hub.identity(self.f.sessions[3]);self.rows={}

    def apply(self,packets):
        for p in packets:
            if p==b'\x28':self.rows.clear()
            elif p[:1]==b'\x26':self.rows.pop(int.from_bytes(p[1:5],'little'),None)
            elif p[:2]==b'\xc8\x2c':self.rows.update((r.identity,r) for r in decode_room_list(p))

    def observe(self):
        self.hub.tick();packets=tuple(self.hub.queues[self.viewer]);self.hub.queues[self.viewer].clear();self.apply(packets);return packets

    def create(self,index=0):
        r=ArenaCreateRequest(0,2,2,2,40,1,1,0,1)
        self.f.send(index,encode_create_request(r))
        owner=self.hub.identity(self.f.sessions[index]);return self.hub.wager_lobbies.room(owner)

    def test_closed_group_disappears_without_reopening_browser(self):
        room=self.create();self.observe();self.assertIn(room.identity,self.rows)
        self.f.send(0,b'\x2a\1');packets=self.observe()
        self.assertNotIn(room.identity,self.rows);self.assertIn(encode_room_removed(room.identity),packets)
        self.assertLess(packets.index(encode_room_removed(room.identity)),next(i for i,p in enumerate(packets) if p[:2]==b'\xc8\x2c'))

    def test_disconnect_closes_creator_group_and_removes_it_for_observers(self):
        room=self.create();self.observe();self.hub.disconnect(self.f.sessions[0]);self.observe()
        self.assertNotIn(room.identity,self.rows)

    def test_start_and_completed_wager_do_not_leave_old_lobby_row(self):
        room=self.create();self.observe()
        from tio.protocol.wagers import encode_join
        self.f.send(1,encode_join(room.identity));self.f.send(1,b'\x2c\1');self.f.send(0,b'\x2e')
        self.observe();self.assertNotIn(room.identity,self.rows)
        self.f.now=5;self.hub.tick();self.observe()
        for i in (0,1):self.f.send(i,b'\x36')
        self.f.send(0,b'\x2a\1');self.hub.tick();self.observe()
        self.assertNotIn(room.identity,self.rows)

    def test_initial_or_explicit_refresh_clears_unknown_stale_client_rows(self):
        self.rows[999999]='stale';self.observe();self.assertNotIn(999999,self.rows)
        room=self.create();self.observe();self.rows[999999]='stale'
        packets=self.f.send(3,b'\xba\1');self.apply(packets)
        self.assertIn(b'\x28',packets);self.assertEqual(set(self.rows),{room.identity})

    def test_leave_one_active_room_visible_and_suppress_unchanged_updates(self):
        a,b=self.create(0),self.create(1);self.observe()
        self.f.send(0,b'\x2a\1');self.observe();self.assertEqual(set(self.rows),{b.identity})
        self.assertFalse(any(p==b'\x28' or p[:1]==b'\x26' or p[:2]==b'\xc8\x2c' for p in self.observe()))

    def test_pool_switch_removes_previous_pool_entries(self):
        room=self.create();self.observe()
        original=self.hub.city
        def city(owner,levels=None):
            if owner==self.viewer:return SimpleNamespace(pool='another-pool')
            return original(owner,levels)
        with patch.object(self.hub,'city',side_effect=city):self.observe()
        self.assertNotIn(room.identity,self.rows)

    def test_no_city_list_cleanup_packets_are_sent_to_battle_participants(self):
        owners,b=self.f.launch()
        for owner in owners:self.hub.queues[owner].clear()
        self.hub.tick()
        for owner in owners:self.assertFalse(any(p==b'\x28' or p[:1]==b'\x26' for p in self.hub.queues[owner]))

    def test_removal_codec_rejects_invalid_ids_and_has_original_native_shape(self):
        self.assertEqual(encode_room_removed(73),b'\x26I\0\0\0');self.assertEqual(encode_room_list_clear(),b'\x28')
        for identity in (0,-1,0xffffffff,2**32,True):
            with self.assertRaises(PacketError):encode_room_removed(identity)

if __name__=='__main__':unittest.main()
