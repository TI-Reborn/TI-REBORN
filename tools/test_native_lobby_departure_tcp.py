"""Two-account Team/Wall departure over actual localhost TCP/native framing."""
import json,os,socket,unittest
from pathlib import Path
import test_shared_team_arena as fixture
from server.team_arena import TeamArena
from tio.protocol.arena import ArenaCreateRequest,encode_create_request
from tio.protocol.wagers import encode_join,encode_kick
from tio.protocol.battle_members import decode_battle_members
from tio.protocol.system_message import encode_leave_room
from tio.protocol.transport import InitialCipher,InitialFrameReader,encode_initial_frame
RESULTS=[]

class NativeDepartureTcpTests(unittest.TestCase):
    def setup_room(self,kind,mode):
        fixture.SharedTeamTests.setUp(self);self.links=[]
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
        try:
            for i in range(2):
                client=socket.create_connection(listener.getsockname(),timeout=3);server,_=listener.accept()
                server.settimeout(3);self.addCleanup(server.close);self.addCleanup(client.close)
                self.links.append((client,server,InitialCipher('C2S'),InitialFrameReader(InitialCipher('C2S')),InitialCipher('S2C'),InitialFrameReader(InitialCipher('S2C'))))
        finally:listener.close()
        if kind=='ordinary':
            self.send(0,bytes((0xba,3,mode,1)));room=self.hub.lobbies.room(self.owner(0))
        else:
            self.send(0,encode_create_request(ArenaCreateRequest(mode,2,8 if mode==4 else 2,2,40,1,1,0,100)))
            room=self.hub.wager_lobbies.room(self.owner(0))
        self.send(1,encode_join(room.identity));joined=self.flush(0)
        record=decode_battle_members(next(p for p in joined if p[:1]==b'\x25'))
        assert tuple(r.character_id for r in record[2])==(1,self.owner(1))
        self.initial_member_packet=next(p for p in joined if p[:1]==b'\x25')
        self.room=room;self.kind=kind;self.mode=mode

    def owner(self,index):return self.hub.identity(self.sessions[index])

    def flush(self,index):
        client,server,_,_,cipher,reader=self.links[index];count=len(self.hub.queues[self.owner(index)])
        self.hub.drain(self.sessions[index],server,cipher);packets=[]
        while len(packets)<count:packets.extend(reader.feed(client.recv(65536)))
        return tuple(packets)

    def send(self,index,packet):
        client,server,cipher,reader,_,_=self.links[index]
        frame=encode_initial_frame(packet,cipher)
        # Exercise actual split frame reception, preserving native key evolution.
        client.sendall(frame[:1]);assert reader.feed(server.recv(1))==[]
        client.sendall(frame[1:]);requests=[]
        while not requests:requests.extend(reader.feed(server.recv(65536)))
        self.assertEqual(requests,[packet]);self.assertTrue(self.hub.handle(self.sessions[index],packet))
        return self.flush(index)

    def departure(self,kind,mode,action):
        self.setup_room(kind,mode);other=self.owner(1)
        if action=='leave':removed=self.send(1,b'\x2a\x01');survivor=self.flush(0)
        elif action=='kick':survivor=self.send(0,encode_kick(other));removed=self.flush(1)
        elif action=='disconnect':self.hub.disconnect(self.sessions[1]);removed=();survivor=self.flush(0)
        elif action=='close':removed=self.send(0,b'\x2a\x01');survivor=self.flush(1)
        else:raise AssertionError(action)
        if action=='close':
            self.assertIn(encode_leave_room(),removed);self.assertIn(encode_leave_room(),survivor)
            self.assertFalse(any(p[:1]==b'\x27' for p in survivor));native=()
        else:
            packet=b'\x27'+other.to_bytes(4,'little');self.assertIn(packet,survivor)
            update=next(p for p in survivor if p[:1]==b'\x25')
            self.assertLess(survivor.index(packet),survivor.index(update))
            self.assertEqual(tuple(r.character_id for r in decode_battle_members(update)[2]),(1,))
            if action!='disconnect':self.assertIn(encode_leave_room(),removed)
            native=(packet,update)
            self.assertIsNone((self.hub.lobbies if kind=='ordinary' else self.hub.wager_lobbies).room(other))
        RESULTS.append(dict(kind=kind,mode=mode,action=action,initial_ids=[1,other],initial_member_packet_hex=self.initial_member_packet.hex(),survivor_packets_hex=[p.hex() for p in survivor],native_sequence_hex=[p.hex() for p in native],two_real_tcp_clients=True,account_fixtures=2))

    def test_ordinary_team_leave(self):self.departure('ordinary',1,'leave')
    def test_ordinary_team_kick(self):self.departure('ordinary',1,'kick')
    def test_ordinary_team_disconnect(self):self.departure('ordinary',1,'disconnect')
    def test_ordinary_team_close(self):self.departure('ordinary',1,'close')
    def test_ordinary_wall_leave(self):self.departure('ordinary',4,'leave')
    def test_ordinary_wall_kick(self):self.departure('ordinary',4,'kick')
    def test_ordinary_wall_disconnect(self):self.departure('ordinary',4,'disconnect')
    def test_ordinary_wall_close(self):self.departure('ordinary',4,'close')
    def test_wager_team_leave(self):self.departure('wager',1,'leave')
    def test_wager_team_kick(self):self.departure('wager',1,'kick')
    def test_wager_team_disconnect(self):self.departure('wager',1,'disconnect')
    def test_wager_team_close(self):self.departure('wager',1,'close')
    def test_wager_wall_leave(self):self.departure('wager',4,'leave')
    def test_wager_wall_kick(self):self.departure('wager',4,'kick')
    def test_wager_wall_disconnect(self):self.departure('wager',4,'disconnect')
    def test_wager_wall_close(self):self.departure('wager',4,'close')

    def test_other_wager_mode_keeps_merge_only_previous_protocol(self):
        self.setup_room('wager',0);self.send(1,b'\x2a\x01');survivor=self.flush(0)
        self.assertFalse(any(p[:1]==b'\x27' for p in survivor))
        self.assertTrue(any(p[:1]==b'\x25' for p in survivor))

    def test_invalid_non_captain_kick_keeps_authoritative_membership(self):
        self.setup_room('ordinary',1);self.send(1,encode_kick(self.owner(0)))
        self.assertEqual(self.room.members,[self.owner(0),self.owner(1)])
        self.assertEqual(self.flush(0),())

def write_results():
    target=os.environ.get('TIO_DEPARTURE_TEST_REPORT')
    if target:Path(target).write_text(json.dumps(dict(cases=RESULTS),indent=2)+'\n')
unittest.addModuleCleanup(write_results)
if __name__=='__main__':unittest.main()
