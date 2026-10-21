from contextlib import closing
import sqlite3,struct,unittest
from server.ranked_party import party,wire
from tio.protocol.ranked_party import decode,invite,snapshot
import test_ranked as fixture
from test_ranked_squads import join

class RankedPartyTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.RankedServerTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.case=self.base.case;self.hub=self.base.hub;self.path=self.base.path
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE characters(account TEXT PRIMARY KEY,name BLOB,name_key TEXT)')
            db.executemany('INSERT INTO characters VALUES (?,?,?)',[(s.account,s.probe_character_name,s.account) for s in self.case.sessions])
        self.owners=[self.hub.identity(s) for s in self.case.sessions]

    def send(self,i,p):return self.case.send(i,p)
    def request(self,a=0,b=1):
        replies=self.send(a,b'\xc6\x32'+self.case.sessions[b].probe_character_name+b'\0\0\0')
        self.assertFalse(any(p[0]==0xf0 for p in replies),replies)
        self.assertIn(invite(self.case.sessions[a].probe_character_name),self.hub.queues[self.owners[b]])
    def accept(self,a=0,b=1):self.request(a,b);self.send(b,b'\xc6\x37\1')
    def ready(self,a=0,b=1):self.send(a,join((1,)));self.send(b,join((1,)));self.send(a,join((1,)))

    def test_invitation_requires_consent_and_decline_does_not_join(self):
        self.request();self.assertIsNone(party(self.hub,self.owners[1]))
        self.send(1,b'\xc6\x37\0');self.assertIsNone(party(self.hub,self.owners[1]))
        self.assertTrue(any(p[0]==0xf0 for p in self.send(1,b'\xc6\x37\1')))

    def test_group_waits_for_a_real_opponent_and_never_splits_members(self):
        self.accept();self.ready();self.hub.tick()
        self.assertEqual(set(self.hub.ranked_waiting),set(self.owners[:2]));self.assertFalse(self.hub.battles)
        self.send(2,join((1,)));battle=self.hub.battles[self.owners[0]]
        self.assertIs(battle,self.hub.battles[self.owners[1]])
        sides=battle['field'].teams;self.assertEqual(sides[self.owners[0]],sides[self.owners[1]]);self.assertNotEqual(sides[self.owners[0]],sides[self.owners[2]])
        self.assertEqual(len(battle['field']._actors),8);self.assertEqual(len(battle['bots']),5)
        self.assertFalse(self.hub.ranked_parties);self.assertFalse(self.hub.ranked_waiting)

    def test_readiness_then_leader_start_and_joint_cancel(self):
        self.accept();self.send(0,join((1,)));self.send(1,join((1,)))
        self.assertFalse(self.hub.ranked_waiting)
        self.send(0,join((1,)));self.assertEqual(len(self.hub.ranked_waiting),2)
        self.send(1,b'\xc6\x23');self.assertFalse(self.hub.ranked_waiting)
        self.assertFalse(party(self.hub,self.owners[0]).tickets)

    def test_disconnect_and_leave_cancel_entire_party_search(self):
        self.accept();self.ready();self.hub.disconnect(self.case.sessions[0])
        self.assertFalse(self.hub.ranked_waiting);remaining=party(self.hub,self.owners[1]);self.assertEqual(remaining.leader,self.owners[1])
        self.send(1,b'\xc6\x33');self.assertIsNone(party(self.hub,self.owners[1]))

    def test_allocation_bounds_and_other_accounts_cannot_change_party(self):
        self.accept();group=party(self.hub,self.owners[0]);target=wire(self.hub,group,self.owners[0],self.owners[1])
        self.assertTrue(any(p[0]==0xf0 for p in self.send(1,b'\xc6\x34'+struct.pack('<IB',target,2))))
        target=wire(self.hub,group,self.owners[1],self.owners[0]);self.send(0,b'\xc6\x34'+struct.pack('<IB',target,3));self.assertEqual(sum(group.slots.values()),4)
        self.assertTrue(any(p[0]==0xf0 for p in self.send(0,b'\xc6\x34'+struct.pack('<IB',target,4))))

    def test_self_missing_already_grouped_and_busy_invites_rejected(self):
        for name in (b'alice',b'missing'):
            self.assertTrue(any(p[0]==0xf0 for p in self.send(0,b'\xc6\x32'+name+b'\0\0\0')))
        self.accept();self.assertTrue(any(p[0]==0xf0 for p in self.send(2,b'\xc6\x32bob\0\0\0')))
        self.assertTrue(any(p[0]==0xf0 for p in self.send(0,b'\xba\3\1\1')))

    def test_late_confirmation_cannot_accept_a_different_inviter(self):
        self.request();self.send(0,b'\xc6\x33')
        self.assertTrue(any(p[0]==0xf0 for p in self.send(2,b'\xc6\x32bob\0\0\0')))
        self.send(1,b'\xc6\x37\1');self.assertIsNone(party(self.hub,self.owners[1]))

    def test_checked_native_request_shapes(self):
        self.assertEqual(decode(b'\xc6\x32bob\0\0\0'),(0x32,(b'bob','')))
        for raw in (b'\xc6\x32bob\0\1\0',b'\xc6\x37\2',b'\xc6\x33junk',b'\xc6\x34'+bytes(4)+b'\5'):
            with self.assertRaises(ValueError):decode(raw)
        self.assertEqual(snapshot(0,()),b'\xc6\x36'+bytes(10))

if __name__=='__main__':unittest.main()
