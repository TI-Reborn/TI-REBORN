"""Native requests on actual account/clan stores; no hosted account fixtures."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from types import SimpleNamespace
import unittest

from server.presence import Presence
from server.clan_service import handle,sync
from server.public_profile import read_profile
from tio.db_transaction import connect
from tio.mine_claims import MineClaimsStore,MineClaimRejected
from tio.protocol.binary import Reader
from tio.protocol.presence import Player
from tio.protocol.public_profile import encode_profile


class AllianceServiceTests(unittest.TestCase):
    def setUp(self):
        from tests.test_alliances import AllianceTests
        self.fixture=AllianceTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.path=self.fixture.path;self.hub=Presence();self.sessions={}
        class Session:pass
        for i,a in enumerate(('alice','bob','carol','dave','member')):
            s=Session();s.account=a;s.database=self.path;s.owned_pet_probe=True;s.probe_character_id=1
            s.probe_character_name=a.title().encode();s.alliances_store=self.fixture.store
            s.arena=SimpleNamespace(_fields={},rooms=SimpleNamespace(snapshot=lambda:()))
            s.survival=SimpleNamespace(searching=lambda _:False)
            s.locations=SimpleNamespace(current=lambda _:3)
            s.router=SimpleNamespace(team_arena=SimpleNamespace(busy=lambda _:False,in_battle=lambda _:False))
            self.sessions[a]=s
            self.hub.players[s]=(3,Player(100+i,s.probe_character_name))
            self.hub.queues[s]=deque();self.hub.messages[s]=deque()

    def send(self,a,body):
        self.assertTrue(handle(self.hub,self.sessions[a],b'\xaf'+body))

    def clear(self):
        for queue in self.hub.messages.values():queue.clear()

    def create(self):self.send('alice',b'\x01Alliance One\0')

    def join(self):
        self.send('alice',b'\x02bETA\0');self.send('bob',b'\x04\1')

    def replies(self,a,prefix):return tuple(p for p in self.hub.messages[self.sessions[a]] if p.startswith(prefix))

    def test_af_routes_create_invitation_to_actual_other_clan_leader_and_accept_once(self):
        self.create();self.clear();self.send('alice',b'\x02bETA\0')
        self.assertEqual(self.replies('bob',b'\xaf\3'),(b'\xaf\3Alice\0Alliance One\0',))
        self.assertFalse(self.replies('carol',b'\xaf\3'));self.assertFalse(self.replies('member',b'\xaf\3'))
        self.send('bob',b'\x04\1');self.assertEqual(len(self.fixture.store.info('alice')['clans']),2)
        self.assertEqual(self.fixture.funds('bob'),(475000,95000))
        before=self.fixture.rows();self.send('bob',b'\x04\1');self.assertEqual(before,self.fixture.rows())
        self.assertTrue(self.replies('bob',b'\xf0'))

    def test_two_authenticated_sessions_of_same_account_accept_pay_once(self):
        self.create();self.send('alice',b'\x02Beta\0')
        other=type(self.sessions['bob'])();other.__dict__.update(self.sessions['bob'].__dict__)
        self.hub.players[other]=(3,Player(200,b'Bob'));self.hub.messages[other]=deque();self.hub.queues[other]=deque()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(tuple(pool.map(lambda s:handle(self.hub,s,b'\xaf\x04\1'),(self.sessions['bob'],other))),(True,True))
        self.assertEqual(self.fixture.funds('bob'),(475000,95000))
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM alliance_ledger WHERE operation='join'").fetchone()[0],1)

    def test_all_operations_transfer_leave_and_dissolve_with_shared_sync(self):
        self.create();self.join();self.send('alice',b'\x08')
        self.assertEqual(self.fixture.funds('alice'),(350000,70000))
        self.send('alice',b'\x09'+self.fixture.ids['bob'].to_bytes(4,'little'))
        self.assertEqual(self.fixture.store.info('alice')['leader'],'bob')
        self.send('alice',b'\x0a');self.assertIsNone(self.fixture.store.info('alice'))
        funds=self.fixture.funds('bob');self.send('bob',b'\x0c')
        self.assertEqual(self.fixture.store.info('bob')['state'],'dissolving')
        self.send('bob',b'\x0c');self.assertEqual(self.fixture.store.info('bob')['state'],'dissolving')
        self.assertEqual(self.fixture.funds('bob'),funds)
        self.assertTrue(self.replies('bob',b'\xaf\x0d'))

    def test_unknown_decision_and_malformed_or_busy_requests_never_mutate_economy(self):
        self.create();self.send('alice',b'\x02Beta\0');before=self.fixture.rows()
        for payload in (b'\x04\2',b'\x04\3',b'\x08extra',b'\x01Bad\0extra',b'\x09\1'):
            self.send('bob',payload);self.assertEqual(before,self.fixture.rows())
        bob=self.sessions['bob'];bob.router.team_arena.busy=lambda _:True
        self.send('bob',b'\x04\1');self.assertEqual(before,self.fixture.rows())
        bob.router.team_arena.busy=lambda _:False;bob.locations.current=lambda _:None
        self.send('bob',b'\x04\1');self.assertEqual(before,self.fixture.rows())

    def test_signature_observes_derived_head_revision_roster_and_invitation_expiry(self):
        self.create();self.send('alice',b'\x02Beta\0');bob=self.sessions['bob'];self.clear()
        sync(self.hub,bob);self.assertFalse(self.replies('bob',b'\xaf\3'))
        self.fixture.store.upgrade('alice');sync(self.hub,bob)
        self.assertEqual(len(self.replies('bob',b'\xaf\3')),1)
        self.fixture.clans.transfer_leader('alice',b'Member');sync(self.hub,bob)
        self.assertIsNone(bob.alliances_invitation)
        sync(self.hub,self.sessions['member']);self.assertIn(b'Member\0',self.replies('member',b'\xaf\x0d')[-1])

    def test_public_profile_active_alliance_and_native_fields_are_read_only(self):
        self.create();self.join();before=self.fixture.rows()
        profile=read_profile(self.path,account='bob')
        self.assertEqual((profile.alliance_name,profile.alliance_id),(b'Alliance One',self.fixture.store.info('bob')['id']))
        packet=encode_profile(100,profile.name,profile.level,'',clan_name=profile.clan_name,
            clan_crest_id=profile.clan_crest_id,alliance_name=profile.alliance_name,alliance_crest_id=profile.alliance_crest_id)
        r=Reader(packet);self.assertEqual(r.read(2),b'\xa7\0');r.u32()
        self.assertEqual(self.string(r),b'Bob');r.u8();r.u32()
        self.assertEqual(self.string(r),b'Beta');self.assertEqual(r.u32(),0)
        self.assertEqual(self.string(r),b'Alliance One');self.assertEqual(r.u32(),0)
        self.assertEqual(before,self.fixture.rows())
        self.fixture.store.dissolve('alice');self.assertEqual(read_profile(self.path,account='bob').alliance_id,0)
        # Roster alliance denotes a crest asset, never our alliance identity.
        self.assertEqual(self.hub.players[self.sessions['bob']][1].alliance,0)

    def test_native_leading_clan_identity_crest_and_rating_count_are_not_storage_id(self):
        self.send('bob',b'\x01Beta Alliance\0')
        header=self.fixture.store.info('bob');self.assertNotEqual(header['id'],header['leading_clan'])
        r=Reader(self.replies('bob',b'\xaf\x0d')[-1]);r.read(2)
        self.assertEqual(r.u32(),header['leading_clan']);self.assertEqual(self.string(r),b'Beta Alliance')
        self.assertEqual(r.u8(),1);self.assertEqual(r.u32(),0);self.assertEqual(r.u32(),90000)
        r.u8();self.assertEqual(r.u16(),1);self.assertEqual(r.u32(),self.fixture.ids['bob'])
        self.assertEqual(self.string(r),b'Beta');r.u8();self.assertEqual(r.u32(),0)
        self.assertEqual(r.u16(),1);self.assertEqual(r.u32(),90000)
        self.clear();self.assertTrue(self.hub.handle(self.sessions['bob'],b'\xaf\x0e'))
        r=Reader(self.replies('bob',b'\xaf\x0f')[-1]);r.read(2);self.assertEqual(r.u32(),1)
        self.assertEqual(r.u32(),header['leading_clan']);self.string(r);r.u8();self.assertEqual(r.u32(),0)
        self.assertEqual(r.u32(),90000);self.assertEqual(r.u8(),1);self.assertEqual(self.string(r),b'Beta');r.finish()

    def test_native_ratings_queries_while_busy_are_read_only_and_echo_actual_page_selector(self):
        self.create();self.join();bob=self.sessions['bob'];bob.router.team_arena.busy=lambda _:True
        before=self.fixture.rows();self.clear()
        self.assertTrue(self.hub.handle(bob,b'\x82\0\0'))
        r=Reader(self.replies('bob',b'\x83')[-1]);self.assertEqual(r.read(3),b'\x83\0\0')
        self.assertEqual(r.u32(),4)
        fields=[]
        for _ in range(4):
            cid=r.u32();name=self.string(r);leader=self.string(r);members=r.u16();capacity=r.u16();lvl=r.u8()
            numeric=tuple(r.u32() for _ in range(6));fields.append((cid,name,leader,members,capacity,lvl,numeric))
        r.finish();self.assertEqual(fields[0][6],(0,100000,0,0,0,0))
        self.assertEqual(fields[-1][1],b'Alpha');self.assertEqual(fields[-1][6],(0,90000,0,0,0,0))
        for page,selector in ((1,0),(2,0),(0,1),(1,1),(2,1)):
            self.assertTrue(self.hub.handle(bob,bytes((0x82,page,selector))))
            self.assertEqual(self.replies('bob',b'\x83')[-1],bytes((0x83,page,selector))+bytes(4))
        self.assertTrue(self.hub.handle(bob,b'\xaf\x0e'));self.assertTrue(self.replies('bob',b'\xaf\x0f'))
        self.assertEqual(before,self.fixture.rows())

    def test_native_alliance_chat7_uses_current_membership_across_locations_and_clears_after_dissolve(self):
        from tio.protocol.chat import encode_message
        self.create();self.join();self.clear()
        self.hub.players[self.sessions['bob']]=(None,self.hub.players[self.sessions['bob']][1])
        self.hub.chat(self.sessions['alice'],b'\x21\7'+ 'Только союзникам'.encode('utf-16-le')+b'\0\0')
        reply=encode_message(7,b'Alice','Только союзникам')
        for a in ('alice','bob','member'):self.assertEqual(tuple(self.hub.messages[self.sessions[a]]),(reply,))
        for a in ('carol','dave'):self.assertFalse(self.hub.messages[self.sessions[a]])
        self.fixture.store.leave('bob');self.clear();self.hub.chat(self.sessions['alice'],b'\x21\7x\0\0\0')
        self.assertFalse(self.hub.messages[self.sessions['bob']])
        self.fixture.store.dissolve('alice');self.clear();self.hub.chat(self.sessions['alice'],b'\x21\7x\0\0\0')
        self.assertTrue(self.replies('alice',b'\xf0'));self.assertFalse(self.hub.messages[self.sessions['member']])
        self.clear();self.hub.chat(self.sessions['alice'],b'\x21\5x\0\0\0')
        self.assertTrue(self.replies('alice',b'\xf0'));self.assertFalse(self.hub.messages[self.sessions['member']])

    @staticmethod
    def string(r):
        out=bytearray()
        while (c:=r.u8()):out.append(c)
        return bytes(out)

    def test_allied_mine_admission_preserves_owner_and_rechecks_active_membership(self):
        claims=MineClaimsStore(self.path);claim=claims.admin_set_claim(13,self.fixture.ids['alice'],
            expected_revision=0,actor='local fixture',reason='only temporary test database')
        with self.assertRaises(MineClaimRejected):claims.authorize_defender('bob',claim)
        self.create();self.join()
        self.assertEqual(claims.authorize_defender('bob',claim),self.fixture.ids['alice'])
        self.assertEqual(claims.freeze(13),claim)
        with self.assertRaises(MineClaimRejected):claims.authorize_defender('carol',claim)
        self.fixture.store.dissolve('alice')
        with self.assertRaises(MineClaimRejected):claims.authorize_defender('bob',claim)
        self.fixture.store.restore('alice');self.fixture.store.leave('bob')
        with self.assertRaises(MineClaimRejected):claims.authorize_defender('bob',claim)
        self.assertEqual(claims.authorize_defender('member',claim),self.fixture.ids['alice'])

    def test_admitted_allied_pair_keeps_frozen_tax_recipients_after_alliance_leave(self):
        from tio.crystal_market import CrystalMarket
        claims=MineClaimsStore(self.path);claim=claims.admin_set_claim(13,self.fixture.ids['alice'],
            expected_revision=0,actor='local fixture',reason='temporary allied mine admission')
        self.create();self.join();self.assertEqual(claims.authorize_defender('bob',claim),claim['owner_clan'])
        market=CrystalMarket(self.path);self.fixture.store.leave('bob')
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            first=market.settle_mine(db,'frozen-allied-pair',gross=100,role=1,extractor='alice',
                claim=claim,miner='alice',defender='bob')
            replay=market.settle_mine(db,'frozen-allied-pair',gross=100,role=1,extractor='alice',
                claim=claim,miner='alice',defender='bob')
            self.assertEqual(first,replay)
            self.assertEqual(tuple(db.execute('SELECT account,amount FROM crystal_wallets ORDER BY account')),
                (('alice',50),('bob',40)))
            self.assertEqual(db.execute('SELECT amount FROM clan_crystals WHERE clan_id=?',(claim['owner_clan'],)).fetchone(),(10,))
            self.assertIsNone(db.execute('SELECT amount FROM clan_crystals WHERE clan_id=?',(self.fixture.ids['bob'],)).fetchone())


if __name__=='__main__':unittest.main()
