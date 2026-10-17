"""Actual three TCP peers, native cipher/frames and changed BA02/BA06 city lists."""
import socket,unittest
import test_shared_team_arena as fixture
from tio.protocol.arena import ArenaCreateRequest,encode_create_request,decode_room_list
from tio.protocol.wagers import encode_join
from tio.protocol.transport import InitialCipher,InitialFrameReader,encode_initial_frame
RESULTS=[]

class NativeLiveProjectionTests(unittest.TestCase):
    def setup_wire(self,peers=3):
        fixture.SharedTeamTests.setUp(self);self.links=[]
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
        try:
            for i in range(peers):
                client=socket.create_connection(listener.getsockname(),timeout=3);server,_=listener.accept();server.settimeout(3)
                self.addCleanup(server.close);self.addCleanup(client.close)
                self.links.append((client,server,InitialCipher('C2S'),InitialFrameReader(InitialCipher('C2S')),InitialCipher('S2C'),InitialFrameReader(InitialCipher('S2C'))))
                self.send(i,b'\xba\x01')
        finally:listener.close()
        self.hub.tick()
        for i in range(peers):self.flush(i)

    def owner(self,index):return self.hub.identity(self.sessions[index])

    def flush(self,index):
        client,server,_,_,cipher,reader=self.links[index];count=len(self.hub.queues.get(self.owner(index),()))
        self.hub.drain(self.sessions[index],server,cipher);packets=[]
        while len(packets)<count:packets.extend(reader.feed(client.recv(65536)))
        return tuple(packets)

    def send(self,index,packet):
        client,server,cipher,reader,_,_=self.links[index];frame=encode_initial_frame(packet,cipher)
        client.sendall(frame[:1]);self.assertEqual(reader.feed(server.recv(1)),[])
        client.sendall(frame[1:]);requests=[]
        while not requests:requests.extend(reader.feed(server.recv(65536)))
        self.assertEqual(requests,[packet]);self.assertTrue(self.hub.handle(self.sessions[index],packet));return self.flush(index)

    def projected(self,index=2):
        self.hub.tick();return self.flush(index)

    def row(self,packets,identity):
        lists=[p for p in packets if p[:2]==b'\xba\x02'];self.assertEqual(len(lists),1)
        return next(r for r in decode_room_list(lists[0]) if r.unknown_u32_00==identity)

    def lifecycle(self,kind,mode):
        self.setup_wire()
        if kind=='ordinary':self.send(0,bytes((0xba,3,mode,1)));room=self.hub.lobbies.room(self.owner(0))
        else:
            self.send(0,encode_create_request(ArenaCreateRequest(mode,2,8 if mode==4 else 2,2,40,1,1,0,100)))
            room=self.hub.wager_lobbies.room(self.owner(0))
        create=self.projected();row=self.row(create,room.identity);self.assertEqual((row.unknown_u8_1d,row.unknown_u8_1c),(1,room.capacity))
        self.send(1,encode_join(room.identity));join=self.projected();self.assertEqual(self.row(join,room.identity).unknown_u8_1d,2)
        self.assertFalse(any(p[:2]==b'\xba\x06' for p in join))
        self.send(1,b'\x2a\x01');leave=self.projected();self.assertEqual(self.row(leave,room.identity).unknown_u8_1d,1)
        self.assertEqual(self.row(leave,room.identity).name,b'alice')
        self.assertFalse(any(p[:2]==b'\xba\x06' for p in leave))
        unchanged=self.projected();self.assertEqual(unchanged,())
        self.send(0,b'\x2a\x01');close=self.projected()
        deleted=b'\xba\x06'+room.identity.to_bytes(4,'little');self.assertIn(deleted,close)
        listing=next(p for p in close if p[:2]==b'\xba\x02');self.assertLess(close.index(deleted),close.index(listing));self.assertEqual(decode_room_list(listing),())
        self.assertEqual(self.projected(),())
        RESULTS.append(dict(kind=kind,mode=mode,room_id=room.identity,capacity=room.capacity,three_real_TCP_peers=True,
            create_packets_hex=[p.hex() for p in create],join_packets_hex=[p.hex() for p in join],leave_packets_hex=[p.hex() for p in leave],close_packets_hex=[p.hex() for p in close],unchanged_packets_hex=[]))

    def test_ordinary_team_live_create_join_leave_close(self):self.lifecycle('ordinary',1)
    def test_ordinary_wall_live_create_join_leave_close(self):self.lifecycle('ordinary',4)
    def test_wager_team_live_create_join_leave_close(self):self.lifecycle('wager',1)
    def test_wager_wall_live_create_join_leave_close(self):self.lifecycle('wager',4)

    def test_search_status_update_and_cancel_in_same_open_list(self):
        self.setup_wire();self.send(0,b'\xba\x03\x01\x01');room=self.hub.lobbies.room(self.owner(0));self.projected()
        self.send(0,b'\x2e');search=self.projected();self.assertEqual(self.row(search,room.identity).unknown_u8_1e,2)
        self.assertEqual(self.row(search,room.identity).unknown_u8_1d,1)
        self.send(0,b'\x2a\x01');closed=self.projected();self.assertIn(b'\xba\x06'+room.identity.to_bytes(4,'little'),closed)

    def test_initial_BA01_snapshot_tracks_deletions_before_first_tick(self):
        self.setup_wire();self.send(0,b'\xba\x03\x01\x01');room=self.hub.lobbies.room(self.owner(0))
        initial=self.send(2,b'\xba\x01');self.row(initial,room.identity)
        self.assertIn(room.identity,self.hub.arena_listing_cache[self.owner(2)][1])
        self.send(0,b'\x2a\x01');packets=self.projected();self.assertIn(b'\xba\x06'+room.identity.to_bytes(4,'little'),packets)

    def test_active_wager_BA01_path_tracks_the_same_snapshot(self):
        self.setup_wire();self.send(0,encode_create_request(ArenaCreateRequest(1,2,2,2,40,1,1,0,100)))
        room=self.hub.wager_lobbies.room(self.owner(0));packet=self.send(0,b'\xba\x01')
        self.row(packet,room.identity);self.assertEqual(self.hub.arena_listing_cache[self.owner(0)][0],next(p for p in packet if p[:2]==b'\xba\x02'))

    def test_busy_and_offline_recipients_are_untouched_then_resume(self):
        self.setup_wire();self.send(0,b'\xba\x03\x01\x01');room=self.hub.lobbies.room(self.owner(0));self.flush(0)
        before=self.hub.arena_listing_cache[self.owner(0)]
        self.hub.offline[self.owner(1)]=100;offline=self.hub.arena_listing_cache[self.owner(1)]
        self.projected();self.assertEqual(self.flush(0),());self.assertEqual(self.flush(1),())
        self.assertEqual(self.hub.arena_listing_cache[self.owner(0)],before);self.assertEqual(self.hub.arena_listing_cache[self.owner(1)],offline)
        self.hub.offline.pop(self.owner(1));packets=self.projected(1);self.row(packets,room.identity)

    def test_actual_battle_recipients_receive_no_BA02_or_BA06(self):
        self.setup_wire()
        for index in (0,1):self.send(index,b'\xba\x03\x01\x01');self.send(index,b'\x2e')
        self.assertTrue(self.hub.in_battle(self.sessions[0]));self.assertTrue(self.hub.in_battle(self.sessions[1]))
        for index in range(3):self.flush(index)
        self.hub.tick()
        for index in (0,1):self.assertFalse(any(p[:2] in (b'\xba\x02',b'\xba\x06') for p in self.flush(index)))

    def test_city_pool_change_deletes_previous_rows_and_adds_current_only(self):
        self.setup_wire(4);self.send(0,b'\xba\x03\x01\x01');starter=self.hub.lobbies.room(self.owner(0));self.projected(2)
        class Locations:
            def __init__(self,town):self.town=town
            def current(self,account):return self.town
        self.sessions[2].locations=Locations(2)
        moved=self.projected(2);self.assertIn(b'\xba\x06'+starter.identity.to_bytes(4,'little'),moved)
        self.assertEqual(decode_room_list(next(p for p in moved if p[:2]==b'\xba\x02')),())
        self.assertEqual(decode_room_list(self.hub.list_packet(self.owner(2))),())
        self.assertEqual(len(decode_room_list(self.hub.list_packet(self.owner(3)))),1)

    def test_disconnect_clears_cache_without_changing_C82C_contract(self):
        self.setup_wire();owner=self.owner(2);self.assertIn(owner,self.hub.arena_listing_cache)
        self.assertIsInstance(self.hub.wager_listing_cache[owner],bytes)
        self.hub.disconnect(self.sessions[2]);self.assertNotIn(owner,self.hub.arena_listing_cache)

    def test_retained_battle_disconnect_also_clears_BA_cache(self):
        self.setup_wire()
        for index in (0,1):self.send(index,b'\xba\x03\x01\x01');self.send(index,b'\x2e')
        owner=self.owner(0);self.assertTrue(self.hub.in_battle(self.sessions[0]));self.assertIn(owner,self.hub.arena_listing_cache)
        self.hub.disconnect(self.sessions[0]);self.assertNotIn(owner,self.hub.arena_listing_cache)
        self.assertIn(owner,self.hub.offline);self.assertIn(owner,self.hub.players)

    def test_failed_wager_BA01_preserves_error_and_prior_cache(self):
        self.setup_wire();self.send(0,encode_create_request(ArenaCreateRequest(1,2,2,2,40,1,1,0,100)))
        prior=self.hub.arena_listing_cache[self.owner(0)]
        class Locations:
            def current(self,account):return 0
        self.sessions[0].locations=Locations()
        packet=self.send(0,b'\xba\x01');self.assertFalse(any(p[:2]==b'\xba\x02' for p in packet))
        self.assertTrue(packet);self.assertEqual(self.hub.arena_listing_cache[self.owner(0)],prior)

    def test_unchanged_initial_empty_lists_are_not_sent_each_tick(self):
        self.setup_wire()
        for _ in range(3):
            self.hub.tick()
            for index in range(3):self.assertEqual(self.flush(index),())
