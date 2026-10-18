"""Shared native list contents across the complete group membership lifecycle."""
import unittest
import test_training_arena as training
from tio.protocol.assault import encode_request,CREATE_ROOM,JOIN_ROOM,REQUEST_ROOMS,DISBAND_ROOM
from tio.protocol.binary import Reader
from tio.locations import LocationStore,center
import sqlite3

def listed(packet):
 r=Reader(packet);assert r.read(2)==b'\xc8\x26';rows=[]
 for _ in range(r.u32()):
  identity=r.u32();name=r.read(r.u16()).decode('utf-8')
  # The original GUI invokes both mandatory getters, including no-clan rows.
  assert r.u8()==1;clan=r.u32();assert r.u8()==1;alliance=r.u32()
  rows.append((identity,name,clan,alliance,r.u8(),r.u8(),r.u8()))
 r.finish();return rows

class GroupListTests(unittest.TestCase):
 setUp=training.TrainingArenaTests.setUp
 send=training.TrainingArenaTests.send

 def clear(self):
  for queue in self.hub.queues.values():queue.clear()

 def updates(self,index):
  return [listed(p) for p in self.hub.queues[self.owners[index]] if p[:2]==b'\xc8\x26']

 def rejected(self,index,identity):
  self.clear()
  packets=self.send(index,encode_request(JOIN_ROOM,identity))
  self.assertTrue(any(p[:1]==b'\xf0' for p in packets))
  self.assertIsNone(self.hub.training_group(self.sessions[index]))

 def test_two_selectable_groups_have_correct_creator_ids_and_zero_crests(self):
  self.send(0,encode_request(CREATE_ROOM));first=self.hub.training_group(self.sessions[0])['id']
  self.send(1,encode_request(CREATE_ROOM));second=self.hub.training_group(self.sessions[1])['id']
  self.clear()
  packets=self.send(7,encode_request(REQUEST_ROOMS))
  rows=listed(next(p for p in packets if p[:2]==b'\xc8\x26'))
  self.assertEqual(rows,[(first,self.sessions[0].account,0,0,4,1,0),(second,self.sessions[1].account,0,0,4,1,0)])
  self.send(7,encode_request(JOIN_ROOM,second))
  self.assertEqual(self.hub.training_group(self.sessions[7])['id'],second)
  self.assertEqual(len(self.hub.training_groups[first]['members']),1)

 def test_observer_receives_creation_join_leave_disband_and_empty_refresh(self):
  self.clear();self.send(0,encode_request(CREATE_ROOM));identity=self.hub.training_group(self.sessions[0])['id']
  self.assertEqual(self.updates(7)[-1][0][5],1)
  self.clear();self.send(1,encode_request(JOIN_ROOM,identity));self.assertEqual(self.updates(7)[-1][0][5],2)
  self.clear();self.send(1,encode_request(DISBAND_ROOM));self.assertEqual(self.updates(7)[-1][0][5],1)
  self.clear();self.send(0,encode_request(DISBAND_ROOM));self.assertEqual(self.updates(7)[-1],[])
  self.rejected(2,identity)

 def test_other_base_does_not_see_or_join_the_group(self):
  with sqlite3.connect(self.path) as db:LocationStore._save(db,self.sessions[7].account,20,*center(20))
  self.clear();self.send(0,encode_request(CREATE_ROOM));identity=self.hub.training_group(self.sessions[0])['id']
  self.assertFalse(self.updates(7))
  packets=self.send(7,encode_request(REQUEST_ROOMS))
  self.assertEqual(listed(next(p for p in packets if p[:2]==b'\xc8\x26')),[])
  self.rejected(7,identity)

 def test_full_group_is_listed_but_fifth_player_cannot_join(self):
  self.send(0,encode_request(CREATE_ROOM));identity=self.hub.training_group(self.sessions[0])['id']
  for i in (1,2,3):self.send(i,encode_request(JOIN_ROOM,identity))
  self.assertEqual(self.updates(7)[-1][0][4:],(4,4,0))
  self.rejected(4,identity)
