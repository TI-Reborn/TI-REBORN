"""Native upload lifecycle: rights, credits, parsing and durable removal."""
import sqlite3,struct,threading,unittest
from contextlib import closing
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock,patch
import test_clans as fixture
from test_clan_benefits import bmp
from tio.protocol.binary import PacketError
from tio.protocol.clan_crests import encode_upload,decode_upload
from tio.clan_benefits import crest_id,crest_content
from server import clan_service

class Session:pass
class ClanIconUploadTests(unittest.TestCase):
 setUp=fixture.ClanTests.setUp
 join=fixture.ClanTests.join

 def session(self,account='alice'):
  s=Session();s.account=account;s.database=self.path;s.probe_character_id=1;s.owned_pet_probe=True
  s.locations=SimpleNamespace(current=Mock(return_value=1),travelling=Mock(return_value=False))
  s.survival=SimpleNamespace(searching=Mock(return_value=False));s.arena=SimpleNamespace(_fields={},rooms=SimpleNamespace(snapshot=lambda:()))
  s.router=SimpleNamespace(team_arena=SimpleNamespace(busy=Mock(return_value=False),retained=Mock(return_value=False)))
  p=SimpleNamespace(lock=threading.RLock(),messages={s:deque()})
  return s,p

 def upload(self,s,p,raw):
  p.messages[s].clear()
  with patch.object(clan_service,'sync') as sync:
   self.assertTrue(clan_service.handle(p,s,raw))
   return tuple(p.messages[s]),sync.called

 def credit(self,account='alice'):
  with closing(sqlite3.connect(self.path)) as db:return db.execute('SELECT credits FROM wallets WHERE account=?',(account,)).fetchone()[0]

 def current(self):
  with closing(sqlite3.connect(self.path)) as db:return crest_id(db,self.cid)

 def test_original_wire_bounds_and_canonical_format(self):
  self.assertEqual(encode_upload(bmp()),b'\x58'+struct.pack('<H',822)+bmp())
  self.assertEqual(encode_upload(None),b'\x58\0\0')
  self.assertIsNone(decode_upload(encode_upload(None)))
  self.assertEqual(decode_upload(encode_upload(bmp())),bmp())
  for data in (b'',b'\x58',b'\x58\0',b'\x58\0\0x',b'\x58\xff\xff',encode_upload(bmp())[:-1],encode_upload(bmp())+b'x',b'\x58\x01\0x'):
   with self.assertRaises(PacketError):decode_upload(data)

 def test_install_repeat_remove_and_reconnect_keep_blob_and_charge_once(self):
  s,p=self.session();balance=self.credit();rows,synced=self.upload(s,p,encode_upload(bmp()))
  self.assertTrue(synced);self.assertTrue(any(r[:2]==b'\xc8\x39' for r in rows))
  identity=self.current();self.assertGreater(identity,0);self.assertEqual(self.credit(),balance-1000)
  with closing(sqlite3.connect(self.path)) as db:self.assertEqual(crest_content(db,identity),bmp())
  s,p=self.session();self.upload(s,p,encode_upload(bmp()));self.assertEqual(self.current(),identity);self.assertEqual(self.credit(),balance-1000)
  self.upload(s,p,encode_upload(None));self.assertEqual(self.current(),0);self.assertEqual(self.credit(),balance-1000)
  self.upload(s,p,encode_upload(None));self.assertEqual(self.credit(),balance-1000)
  with closing(sqlite3.connect(self.path)) as db:self.assertEqual(crest_content(db,identity),bmp())

 def test_member_without_rights_and_travel_or_busy_cannot_charge(self):
  for account,reason in (('bob','rights'),('alice','travel'),('alice','busy')):
   s,p=self.session(account);balance=self.credit(account)
   if reason=='travel':s.locations.travelling.return_value=True
   if reason=='busy':s.router.team_arena.busy.return_value=True
   rows,synced=self.upload(s,p,encode_upload(bmp()))
   self.assertTrue(any(r[:1]==b'\xf0' for r in rows));self.assertFalse(synced)
   self.assertEqual(self.credit(account),balance);self.assertEqual(self.current(),0)

 def test_bad_image_or_insufficient_credits_preserves_crest_and_wallet(self):
  s,p=self.session();self.upload(s,p,encode_upload(bmp()));identity=self.current()
  malformed=bytearray(encode_upload(bmp()));malformed[3+18]=17
  rows,_=self.upload(s,p,bytes(malformed));self.assertTrue(any(r[:1]==b'\xf0' for r in rows));self.assertEqual(self.current(),identity)
  with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE wallets SET credits=500 WHERE account='alice'")
  rows,_=self.upload(s,p,encode_upload(bmp(8)));self.assertTrue(any(r[:1]==b'\xf0' for r in rows))
  self.assertEqual(self.credit(),500);self.assertEqual(self.current(),identity)
