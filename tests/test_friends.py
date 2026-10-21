import sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from collections import deque
from unittest.mock import patch
from server.presence import Presence
from tio import friends
from tio.protocol.presence import Player
from tio.protocol.friends import decode_list,decode_request,encode_list,Friend

class FriendsTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.path=Path(temp.name)/'state.sqlite'
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('create table characters(account text primary key,name blob,name_key text)')
            db.executemany('insert into characters values(?,?,?)',[(n,n.title().encode(),n) for n in ('alice','bob','carol')])
        self.hub=Presence();self.sessions=[]
        class Session:pass
        for i,n in enumerate(('alice','bob','carol')):
            s=Session();s.account=n;s.database=self.path;s.owned_pet_probe=True;s.probe_character_name=n.title().encode()
            self.sessions.append(s);self.hub.players[s]=(3,Player(100+i,s.probe_character_name,4));self.hub.messages[s]=deque()
        self.a,self.b,self.c=self.sessions

    def send(self,s,p):self.assertTrue(self.hub.handle(s,p))
    def listed(self,s):return decode_list(next(p for p in reversed(self.hub.messages[s]) if p[0]==0x9f))
    def invite(self):self.send(self.a,b'\xa3Bob\0');self.assertIn(b'\xa0Alice\0',self.hub.messages[self.b])

    def test_accept_refresh_reconnect_and_no_third_party_leak(self):
        self.invite();self.assertFalse(friends.members(self.path,'alice'))
        self.send(self.b,b'\xa1\1')
        self.assertEqual(self.listed(self.a),(Friend(101,b'Bob',True,4),))
        self.assertEqual(self.listed(self.b)[0].name,b'Alice');self.assertFalse(self.hub.messages[self.c])
        self.a.friends_signature=None;self.send(self.a,b'\xa6');self.assertEqual(self.listed(self.a)[0].name,b'Bob')
        self.assertTrue(friends.linked(self.path,'alice','bob'))

    def test_decline_and_unsolicited_accept_do_not_create_friendship(self):
        self.send(self.b,b'\xa1\1');self.invite();self.send(self.b,b'\xa1\0')
        self.assertFalse(friends.members(self.path,'alice'));self.assertFalse(friends.members(self.path,'bob'))

    def test_remove_mutual_idempotent_and_cannot_remove_others(self):
        self.invite();self.send(self.b,b'\xa1\1');self.send(self.c,b'\xa2Bob\0')
        self.assertTrue(friends.linked(self.path,'alice','bob'))
        self.send(self.a,b'\xa2bOB\0');self.send(self.a,b'\xa2Bob\0')
        self.assertEqual(self.listed(self.a),());self.assertEqual(self.listed(self.b),())

    def test_incoming_invite_not_overwritten_and_duplicate_not_reprompted(self):
        self.invite();self.send(self.a,b'\xa3Bob\0');self.send(self.c,b'\xa3Bob\0')
        self.assertEqual(list(self.hub.messages[self.b]).count(b'\xa0Alice\0'),1)
        self.send(self.b,b'\xa1\1');self.assertTrue(friends.linked(self.path,'alice','bob'));self.assertFalse(friends.linked(self.path,'carol','bob'))

    def test_offline_and_rename_resolve_persisted_owner(self):
        self.invite();self.send(self.b,b'\xa1\1');del self.hub.players[self.b]
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("update characters set name=?,name_key='robert' where account='bob'",(b'Robert',))
        with patch('server.public_profile.read_profile',return_value=None):self.send(self.a,b'\xa6')
        row=self.listed(self.a)[0];self.assertEqual(row.name,b'Robert');self.assertFalse(row.online)
        self.send(self.a,b'\xa2Robert\0');self.assertFalse(friends.members(self.path,'alice'))

    def test_disconnect_clears_pending_binding_and_self_missing_names_rejected(self):
        self.invite()
        from server.friends_service import disconnect
        disconnect(self.hub,self.a);del self.hub.players[self.a]
        self.send(self.b,b'\xa1\1');self.assertFalse(friends.members(self.path,'alice'))
        for packet in (b'\xa3Alice\0',b'\xa3Missing\0',b'\xa1\2',b'\xa6junk'):self.send(self.a,packet)
        self.assertFalse(friends.members(self.path,'alice'))

    def test_late_answer_after_sender_disconnect_cannot_accept_a_new_sender(self):
        self.invite()
        from server.friends_service import disconnect
        disconnect(self.hub,self.a);del self.hub.players[self.a]
        self.send(self.c,b'\xa3Bob\0');self.send(self.b,b'\xa1\1')
        self.assertFalse(friends.members(self.path,'bob'));self.assertFalse(friends.members(self.path,'carol'))

    def test_limit_atomic_and_codec_roundtrip(self):
        friends.accept(self.path,'alice','bob')
        with patch('tio.friends.LIMIT',1):
            with self.assertRaises(ValueError):friends.accept(self.path,'alice','carol')
        self.assertFalse(friends.members(self.path,'carol'))
        rows=(Friend(7,b'Bob',True,4,25,1,70),);self.assertEqual(decode_list(encode_list(rows)),rows)
        for raw in (b'\xa3\0',b'\xa3a\0junk',b'\xa1',b'\xa6\0'):
            with self.assertRaises(ValueError):decode_request(raw)

class FriendsTCPTests(unittest.TestCase):
    def test_two_authenticated_sockets_confirm_persist_and_remove(self):
        from test_multi_account import MultiAccountTests
        f=MultiAccountTests();f.setUp();self.addCleanup(f.doCleanups);f.start()
        a=f.handoff(f.begin('alice'));b=f.handoff(f.begin('bob'))
        f.enter(a,'Alice');f.enter(b,'Bob')
        a.send(b'\xa3Bob\0');self.assertEqual(b.until(b'\xa0'),b'\xa0Alice\0')
        b.send(b'\xa1\1')
        self.assertEqual(decode_list(a.until(b'\x9f'))[-1].name,b'Bob')
        self.assertEqual(decode_list(b.until(b'\x9f'))[-1].name,b'Alice')
        a.send(b'\xa6');self.assertEqual(decode_list(a.until(b'\x9f'))[-1].name,b'Bob')
        a.send(b'\xa2Bob\0');self.assertEqual(decode_list(a.until(b'\x9f')),())
        self.assertEqual(decode_list(b.until(b'\x9f')),())

if __name__=='__main__':unittest.main()
