from collections import deque
from types import SimpleNamespace
import unittest

from server.tactical_marks import TacticalMarks,MARK_RATE_LIMIT
from tio.battle_state import BattleActor,BattleField
from tio.battle_snapshot import dumps,loads
from tio.protocol.binary import PacketError
from tio.protocol.tactical_marks import (TacticalMark,PLACE,REMOVE,NATIVE_TTL_SECONDS,
    decode_tactical_mark,encode_tactical_mark,
    decode_tactical_mark_notification,encode_tactical_mark_notification)
from tio.protocol.transport import InitialCipher,InitialFrameReader,encode_initial_frame


class MarkHub(TacticalMarks):
    def __init__(self,*,teams=True):
        self.now=1_000
        self.journal=SimpleNamespace(wall=lambda:self.now)
        self.players={owner:SimpleNamespace(probe_character_id=7) for owner in (10,20,30,40)}
        self.offline={};self.returning={};self.queues={owner:deque() for owner in self.players}
        actors=tuple(BattleActor(i,owner,i,1,15,100,100) for i,owner in enumerate(self.players,1))
        field=BattleField(16,16,actors,step_cost=1,teams={10:0,20:0,30:1,40:1} if teams else {})
        self.battle=dict(field=field,humans=set(self.players),finished=False)
        self.battles={owner:self.battle for owner in self.players}

    def put(self,owner,*packets):self.queues[owner].extend(packets)

    def clear(self):
        for queue in self.queues.values():queue.clear()

    def request(self,owner,x=5,y=6,kind=PLACE):
        character=self.players[owner].probe_character_id if kind==PLACE else 0
        return self.handle_tactical_mark(owner,encode_tactical_mark(TacticalMark(kind,character,x,y)))


class TacticalMarkTests(unittest.TestCase):
    def setUp(self):self.hub=MarkHub()

    def test_exact_native_packet_round_trip_and_rejects_malformed(self):
        value=TacticalMark(PLACE,0x12345678,2,255)
        wire=b'\xb2\x06\x01\x78\x56\x34\x12\x02\xff'
        self.assertEqual(encode_tactical_mark(value),wire)
        self.assertEqual(decode_tactical_mark(wire),value)
        for packet in (wire[:-1],wire+b'\0',b'\xb2\x07'+wire[2:],b'\xb2\x06\x02'+wire[3:]):
            with self.assertRaises(PacketError):decode_tactical_mark(packet)

    def test_authoritative_author_and_team_only_delivery_with_local_ids(self):
        self.hub.request(10)
        self.assertEqual(decode_tactical_mark_notification(self.hub.queues[10][0]),TacticalMark(PLACE,7,5,6))
        self.assertEqual(decode_tactical_mark_notification(self.hub.queues[20][0]),TacticalMark(PLACE,10,5,6))
        self.assertFalse(self.hub.queues[30]);self.assertFalse(self.hub.queues[40])
        self.assertEqual(self.hub.battle['tactical_marks'][10]['expires_at_wall'],1_000+NATIVE_TTL_SECONDS)

    def test_survival_mark_does_not_reach_any_opponent(self):
        self.hub=MarkHub(teams=False)
        self.hub.request(10)
        self.assertEqual(len(self.hub.queues[10]),1)
        self.assertTrue(all(not queue for owner,queue in self.hub.queues.items() if owner!=10))

    def test_spoofed_author_outside_tile_or_unrelated_player_has_no_effect(self):
        forged=encode_tactical_mark(TacticalMark(PLACE,20,5,6))
        with self.assertRaises(ValueError):self.hub.handle_tactical_mark(10,forged)
        with self.assertRaises(ValueError):self.hub.request(10,x=16)
        with self.assertRaises(ValueError):self.hub.handle_tactical_mark(99,forged)
        self.assertNotIn('tactical_marks',self.hub.battle)
        self.assertTrue(all(not queue for queue in self.hub.queues.values()))

    def test_returning_offline_finished_and_faulted_sender_cannot_mark(self):
        for state in ('returning','offline','finished','faulted'):
            with self.subTest(state=state):
                hub=MarkHub()
                if state in ('returning','offline'):getattr(hub,state)[10]=1_200
                else:hub.battle[state]=True
                with self.assertRaises(ValueError):hub.request(10)
                self.assertNotIn('tactical_marks',hub.battle)

    def test_replacement_is_one_per_author_and_keeps_ap_unchanged(self):
        before=dict(self.hub.battle['field']._actors)
        self.hub.request(10)
        self.hub.now+=1
        self.hub.request(10,x=9,y=10)
        self.assertEqual(len(self.hub.battle['tactical_marks']),1)
        mark=self.hub.battle['tactical_marks'][10]
        self.assertEqual((mark['x'],mark['y'],mark['expires_at_wall']),(9,10,1_201))
        self.assertEqual(self.hub.battle['field']._actors,before)

    def test_remove_is_authenticated_and_cannot_remove_ally_mark(self):
        self.hub.request(10)
        self.hub.request(20,x=7,y=8)
        self.hub.clear()
        with self.assertRaises(ValueError):self.hub.request(10,x=7,y=8,kind=REMOVE)
        self.assertEqual(set(self.hub.battle['tactical_marks']),{10,20})
        self.hub.request(10,kind=REMOVE)
        self.assertEqual(set(self.hub.battle['tactical_marks']),{20})
        self.assertEqual(decode_tactical_mark_notification(self.hub.queues[20][-1]),TacticalMark(REMOVE,10,5,6))
        self.assertFalse(self.hub.queues[30])
        self.hub.clear()
        self.assertTrue(self.hub.request(10,kind=REMOVE))
        self.assertTrue(all(not queue for queue in self.hub.queues.values()))

    def test_ambiguous_native_coordinate_overlap_is_rejected_only_for_allies(self):
        self.hub.request(10)
        with self.assertRaises(ValueError):self.hub.request(20)
        self.hub.request(30)
        self.assertEqual(set(self.hub.battle['tactical_marks']),{10,30})

    def test_rate_limit_is_bounded_per_author_and_not_extended_by_reconnect(self):
        for index in range(MARK_RATE_LIMIT):self.hub.request(10,x=index)
        state=dict(self.hub.battle['tactical_marks'][10])
        with self.assertRaises(ValueError):self.hub.request(10,x=15)
        self.assertEqual(self.hub.battle['tactical_marks'][10],state)
        self.hub.now+=5
        self.hub.request(10,x=15)
        self.assertEqual(len(self.hub.battle['tactical_mark_rate'][10]),1)

    def test_current_allies_receive_snapshot_and_original_deadline_removal(self):
        self.hub.request(10)
        self.hub.now+=150
        self.assertEqual(tuple(map(decode_tactical_mark_notification,self.hub.tactical_mark_packets(self.hub.battle,20))),
                         (TacticalMark(PLACE,10,5,6),))
        self.assertFalse(self.hub.tactical_mark_packets(self.hub.battle,30))
        self.hub.clear()
        self.hub.now=1_200
        self.assertEqual(self.hub.expire_tactical_marks(self.hub.battle),())
        self.hub.now+=.001
        self.hub.returning[20]=1_230
        self.assertEqual(self.hub.expire_tactical_marks(self.hub.battle),(10,))
        self.assertEqual(decode_tactical_mark_notification(self.hub.queues[20][-1]).kind,REMOVE)
        self.assertFalse(self.hub.tactical_mark_packets(self.hub.battle,20))

    def test_disconnected_left_or_other_battle_ally_receives_nothing(self):
        for state in ('offline','left','other_battle'):
            with self.subTest(state=state):
                hub=MarkHub()
                if state=='offline':hub.offline[20]=1_100
                elif state=='left':hub.battles.pop(20)
                else:hub.battles[20]=dict(hub.battle)
                hub.request(10)
                self.assertFalse(hub.queues[20])

    def test_departed_author_removes_mark_only_from_current_team(self):
        self.hub.request(10)
        self.hub.clear()
        self.hub.battles.pop(10)
        self.assertEqual(self.hub.expire_tactical_marks(self.hub.battle),(10,))
        self.assertEqual(decode_tactical_mark_notification(self.hub.queues[20][-1]).kind,REMOVE)
        self.assertFalse(self.hub.queues[30]);self.assertFalse(self.hub.queues[10])

    def test_mark_checkpoint_preserves_wall_expiry_and_rate_without_new_classes(self):
        self.hub.request(10)
        saved={key:self.hub.battle[key] for key in ('tactical_marks','tactical_mark_rate')}
        checkpoint=dumps(saved,clock=lambda:500,wall=lambda:self.hub.now)
        self.hub.now+=50
        restored,_=loads(checkpoint,clock=lambda:5,wall=lambda:self.hub.now)
        self.hub.battle.update(restored)
        self.assertEqual(self.hub.battle['tactical_marks'][10]['expires_at_wall'],1_200)
        self.assertEqual(self.hub.battle['tactical_mark_rate'][10],[1_000])
        self.assertTrue(self.hub.tactical_mark_packets(self.hub.battle,20))
        self.hub.now=1_201
        self.assertFalse(self.hub.tactical_mark_packets(self.hub.battle,20))

    def test_duplex_native_frames_support_split_coalesced_marks_without_opcode_sizes(self):
        value=TacticalMark(PLACE,7,2,3)
        for direction,encoder,decoder,other in (
            ('C2S',encode_tactical_mark,decode_tactical_mark,decode_tactical_mark_notification),
            ('S2C',encode_tactical_mark_notification,decode_tactical_mark_notification,decode_tactical_mark)):
            with self.subTest(direction=direction):
                packet=encoder(value)
                with self.assertRaises(PacketError):other(packet)
                cipher=InitialCipher(direction)
                wire=encode_initial_frame(packet,cipher)+encode_initial_frame(packet,cipher)
                reader=InitialFrameReader(InitialCipher(direction))
                self.assertEqual(reader.feed(wire[:3]),[])
                received=reader.feed(wire[3:])
                reader.finish()
                self.assertEqual(tuple(map(decoder,received)),(value,value))


if __name__=='__main__':unittest.main()
