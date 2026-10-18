"""Authoritative icon IDs in existing native rosters, without changing layout."""
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import patch
import sqlite3,unittest
import test_presence as presence_fixture
import test_training_arena as training
from test_training_group_list import listed
from test_clan_benefits import bmp
from tio.protocol.binary import Reader
from tio.protocol.assault import encode_request,CREATE_ROOM,JOIN_ROOM,REQUEST_ROOMS
from tio.clan_benefits import set_crest,validate_crest
from tio.db_transaction import transaction
from tio.alliances import schema as alliance_schema

def roster(packet):
 r=Reader(packet);r.read(2 if packet[:1]==b'\xc7' else 1);rows={}
 for _ in range(r.u8()):
  identity=r.u32();name=bytearray()
  while (c:=r.u8()):name.append(c)
  level=r.u8();crest=r.u32();alliance=r.u32();status=r.u8();rank=r.u32();dealer=r.u8()
  rows[bytes(name)]=(identity,crest,alliance)
 r.finish();return rows

class PresenceCrestTests(unittest.TestCase):
 setUp=presence_fixture.PresenceTests.setUp

 def sync(self,session,crest,alliance):
  session.database='unused';session.probe_character_name=b'Alice';session.locations=SimpleNamespace(current=lambda a:3)
  session.arena=SimpleNamespace(_fields={});session.presence_next_sync=0
  with patch('server.public_profile.read_profile',return_value=SimpleNamespace(level=4,clan_crest_id=crest,alliance_crest_id=alliance)),patch('server.world_runtime.heartbeat',return_value=()),patch('server.avatar_service.sync'):
   self.hub.sync(session)

 def test_existing_player_icon_changes_and_removal_refresh_both_rosters(self):
  a,b,c=self.sessions
  for crest,alliance in ((401,707),(402,708),(0,0)):
   self.sync(a,crest,alliance)
   for peer in (a,b):
    packets=self.hub.snapshot(peer)
    for raw in (packets[1],packets[3]):
     identity,clan,ally=roster(raw)[b'Alice'];self.assertEqual((clan,ally),(crest,alliance))
     self.assertEqual(identity,1 if peer is a else 100)
   self.assertEqual(roster(self.hub.queues[c][1])[b'Alice'][1:],(crest,alliance))

 def test_new_player_gets_icon_on_first_presence_snapshot(self):
  a,b,c=self.sessions;self.hub.players.pop(a);self.sync(a,401,707)
  self.assertEqual(roster(self.hub.queues[b][1])[b'Alice'][1:],(401,707))

class TrainingCrestTests(unittest.TestCase):
 setUp=training.TrainingArenaTests.setUp
 send=training.TrainingArenaTests.send

 def install(self):
  from tio.wallets import WalletStore
  for account in ('a0','b0','c0'):WalletStore(self.path).ensure(account)
  with transaction(self.path) as db:
   set_crest(db,'c0',bmp(9),'unused-first')
   first=set_crest(db,'a0',bmp(1),'first')['crest_id']
   second=set_crest(db,'b0',bmp(2),'second')['crest_id']
   alliance_schema(db)
   aid=db.execute("INSERT INTO alliances(name,name_key,leading_clan,created) VALUES (?,?,?,?)",(b'Alliance','alliance',self.fixture.cids[0],self.fixture.now)).lastrowid
   db.executemany('INSERT INTO alliance_members VALUES (?,?,?)',[(cid,aid,self.fixture.now) for cid in self.fixture.cids[:2]])
   image=bmp(8);ally=db.execute('INSERT INTO clan_crest_blobs(clan_id,digest,bmp) VALUES (?,?,?)',(-aid,validate_crest(image),image)).lastrowid
   db.execute('INSERT INTO alliance_crests VALUES (?,?)',(aid,ally))
  self.assertNotEqual(first,self.fixture.cids[0]);self.assertNotEqual(ally,aid)
  return first,second,ally

 def room_crests(self,packet):
  r=Reader(packet);self.assertEqual(r.read(2),b'\xc8\x24');r.u32();rows=[]
  for _ in range(r.u32()):
   r.u32();name=r.read(r.u16()).decode();r.u8();crest=r.u32();r.u8()
   for _ in range(r.u32()):
    r.u8();r.u32();r.u32();r.read(r.u16())
    for _ in range(5):r.u32()
   r.u8();rows.append((name,crest))
  r.u8();r.finish();return rows

 def test_creator_list_and_mixed_clan_members_use_blob_ids(self):
  first,second,ally=self.install();self.send(0,encode_request(CREATE_ROOM));group=self.hub.training_group(self.sessions[0])
  self.send(4,encode_request(JOIN_ROOM,group['id']))
  rows=listed(self.hub._training_list(19));self.assertEqual(rows[0][2:4],(first,ally));self.assertEqual(rows[0][5],2)
  self.assertEqual(self.room_crests(self.hub.training_room_packet(group,self.owners[0])),[('a0',first),('b0',second)])

 def test_changed_and_removed_icons_push_to_observers_without_rejoining(self):
  first,second,ally=self.install();self.send(0,encode_request(CREATE_ROOM));group=self.hub.training_group(self.sessions[0])
  self.hub.tick_training_events(force=True)
  for q in self.hub.queues.values():q.clear()
  with transaction(self.path) as db:set_crest(db,'a0',None,'remove')
  self.hub.tick_training_events(force=True)
  own=[p for p in self.hub.queues[self.owners[0]] if p[:2]==b'\xc8\x24']
  self.assertEqual(self.room_crests(own[-1]),[('a0',0)])
  rows=[listed(p) for p in self.hub.queues[self.owners[7]] if p[:2]==b'\xc8\x26']
  self.assertEqual(rows[-1][0][2:4],(0,ally))
  for q in self.hub.queues.values():q.clear()
  self.hub.tick_training_events(force=True)
  self.assertFalse(any(p[:2] in (b'\xc8\x24',b'\xc8\x26') for q in self.hub.queues.values() for p in q))

 def test_no_clan_keeps_present_zero_fields_and_selectable_rows(self):
  account=self.sessions[0].account
  with closing(sqlite3.connect(self.path)) as db,db:db.execute('DELETE FROM clan_members WHERE account=?',(account,))
  self.send(0,encode_request(CREATE_ROOM));rows=listed(self.hub._training_list(19));self.assertEqual(rows[0][2:4],(0,0))
