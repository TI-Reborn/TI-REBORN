import unittest
from tio.battle_state import BattleActor, BattleField
from tio.arena_service import ArenaService
from tio.protocol.arena import ArenaCreateRequest, encode_create_request
from tio.protocol.battle_ground import BattleGround, encode_battle_ground
from tio.protocol.battle_move import BattleMove, encode_move_request, decode_battle_move


class BattleStateTests(unittest.TestCase):
    def test_round_robin_end_timeout_and_disconnect(self):
        from dataclasses import replace
        now=[0.0];service=ArenaService(clock=lambda:now[0]);field=self.field()
        room,_=service.create(17,b'Owner',encode_create_request(ArenaCreateRequest(0,1,2,2,40,1,1,0,0)))
        # Two-member server fixture; join transport is not under test here.
        service.rooms.join(room.room_id,99)
        service._records[99]=replace(service._records[17],character_id=99,name=b'Guest',unknown_bytes=b'\0\0\0\0\x01\x01')
        ground=encode_battle_ground(BattleGround(0,8,8,bytes(64),(),bytes(64)))
        service.start_loading(17,b'\x2e',lambda r:(ground,b'\x41'))
        service.configure_field(17,field)
        service.member_loaded(17,b'\x36');service.member_loaded(99,b'\x36')
        with self.assertRaises(ValueError):service.advance_turn(room.room_id,2)
        service.begin_turn_packets(17,(101,),2)
        service.move(17,encode_move_request(BattleMove(101,((3,2),))))
        service.end_turn(17,b'\x3a\x65\0\0\0')
        replies=service.advance_turn(room.room_id,2)
        self.assertEqual([owner for owner,_ in replies],[99,99])
        with self.assertRaises(ValueError):service.move(17,encode_move_request(BattleMove(101,((4,2),))))
        with self.assertRaises(ValueError):service.advance_turn(room.room_id,2)
        service.move(99,encode_move_request(BattleMove(102,((5,3),))))
        now[0]=2.0
        self.assertEqual(service.expire_turns(),((99,b'\x39'),))
        self.assertEqual(service.expire_turns(),())
        replies=service.advance_turn(room.room_id,2)
        self.assertEqual([owner for owner,_ in replies],[17,17])
        self.assertEqual(field.actor(101),BattleActor(101,17,3,2,4))
        self.assertEqual(field.actor(102).action_points,0)
        service.disconnect(17)
        self.assertFalse(service._last_turn)
        with self.assertRaises(ValueError):service.advance_turn(room.room_id,2)

    def test_first_turn_guest_disconnect_allows_owner_turn(self):
        from dataclasses import replace
        service=ArenaService();field=self.field()
        room,_=service.create(17,b'Owner',encode_create_request(ArenaCreateRequest(0,1,2,2,40,1,1,0,0)))
        service.rooms.join(room.room_id,99)
        service._records[99]=replace(service._records[17],character_id=99,name=b'Guest',unknown_bytes=b'\0\0\0\0\x01\x01')
        ground=encode_battle_ground(BattleGround(0,8,8,bytes(64),(),bytes(64)))
        service.start_loading(17,b'\x2e',lambda r:(ground,b'\x41'))
        service.configure_field(17,field)
        service.member_loaded(17,b'\x36');service.member_loaded(99,b'\x36')
        service.begin_turn_packets(99,(102,),40)
        self.assertEqual(service.disconnect_packets(99),((17,b'\x43\x66\0\0\0'),))
        self.assertEqual(service.disconnect_packets(99),())
        self.assertEqual(field.actor_ids(99),())
        self.assertFalse(service._turns)
        self.assertEqual(service._last_turn[room.room_id],99)
        replies=service.advance_turn(room.room_id,40)
        self.assertEqual([owner for owner,_ in replies],[17,17])
        with self.assertRaises(ValueError):service.move(99,encode_move_request(BattleMove(102,((5,3),))))
        service.move(17,encode_move_request(BattleMove(101,((3,2),(4,2),(5,2)))))
        self.assertEqual(field.actor(101).x,5)

    def test_remove_owner_releases_all_cells_and_budgets(self):
        field=BattleField(8,8,[BattleActor(101,17,2,2,4),
                              BattleActor(102,99,3,2,4),BattleActor(103,99,4,2,4)],step_cost=1)
        self.assertEqual(field.remove_owner(99),(102,103))
        self.assertEqual(field.remove_owner(99),())
        field.move(17,BattleMove(101,((3,2),(4,2))))
        self.assertEqual(field.actor(101).action_points,2)
        self.assertEqual(set(field._turn_points),{101})
        with self.assertRaises(ValueError):field.prepare_turn(99,(102,))

    def test_removal_packet_strict_body(self):
        from tio.protocol.battle_remove import encode_battle_remove,decode_battle_remove
        from tio.protocol.binary import PacketError
        packet=encode_battle_remove(0x12345678)
        self.assertEqual(packet,b'\x43\x78\x56\x34\x12')
        self.assertEqual(decode_battle_remove(packet),0x12345678)
        for invalid in (packet[:-1],packet+b'\0',b'\x42'+packet[1:]):
            with self.assertRaises(PacketError):decode_battle_remove(invalid)

    def test_new_turn_refills_only_owned_selection(self):
        field=self.field()
        field.move(17,BattleMove(101,((3,2),)))
        before=field.actor(101)
        for ids in ((101,102),(101,404)):
            with self.assertRaises(ValueError):field.prepare_turn(17,ids)
            self.assertEqual(field.actor(101),before)
        field.prepare_turn(17,(101,))
        self.assertEqual(field.actor(101),BattleActor(101,17,3,2,4))
        self.assertEqual(field.actor(102),BattleActor(102,99,5,2,4))

    def test_second_turn_packets_and_authorization(self):
        from tio.protocol.action_points import encode_action_points
        service=ArenaService();field=self.field()
        service.create(17,b'Owner',encode_create_request(ArenaCreateRequest(0,1,2,2,40,1,1,0,0)))
        ground=encode_battle_ground(BattleGround(0,8,8,bytes(64),(),bytes(64)))
        service.start_loading(17,b'\x2e',lambda room:(ground,b'\x41'))
        service.configure_field(17,field);service.member_loaded(17,b'\x36')
        expected=(encode_action_points(101,4),b'\x38\x28\0\0\0')
        self.assertEqual(service.begin_turn_packets(17,(101,),40),expected)
        service.move(17,encode_move_request(BattleMove(101,((3,2),))))
        with self.assertRaises(ValueError):service.begin_turn_packets(17,(101,),40)
        self.assertEqual(field.actor(101).action_points,3)
        service.end_turn(17,b'\x3a\x65\0\0\0')
        with self.assertRaises(ValueError):service.begin_turn_packets(17,(101,102),40)
        self.assertEqual(field.actor(101).action_points,0)
        self.assertFalse(service._turns)
        self.assertEqual(service.begin_turn_packets(17,(101,),40),expected)
        self.assertEqual((field.actor(101).x,field.actor(101).action_points),(3,4))

    def field(self):
        return BattleField(8,8,[BattleActor(101,17,2,2,4),BattleActor(102,99,5,2,4)],
                           blocked={(3,3)},step_cost=1)

    def test_success_and_budget(self):
        field=self.field()
        reply=field.move(17,BattleMove(101,((2,2),(3,2),(4,2))))
        self.assertEqual(decode_battle_move(reply).path,((3,2),(4,2)))
        self.assertEqual(field.actor(101),BattleActor(101,17,4,2,2))
        with self.assertRaises(ValueError):field.move(17,BattleMove(101,((4,1),(3,1),(2,1))))
        self.assertEqual(field.actor(101).action_points,2)

    def test_rejections_are_atomic(self):
        field=self.field();before=field.actor(101)
        for owner,actor,path in [(99,101,((3,2),)),(17,102,((5,3),)),(17,404,((3,2),)),
                                 (17,101,()),(17,101,((3,2),(5,2))),
                                 (17,101,((3,2),(3,3))), (17,101,((3,2),(4,2),(5,2))),
                                 (17,101,((2,3),(3,4))), (17,101,((1,2),(0,2),(-1,2)))]:
            with self.subTest(path=path,owner=owner,actor=actor):
                with self.assertRaises(ValueError):field.move(owner,BattleMove(actor,path))
                self.assertEqual(field.actor(101),before)

    def test_turn_and_disconnect(self):
        now=[0.0];service=ArenaService(clock=lambda:now[0]);field=self.field()
        service.create(17,b'Owner',encode_create_request(ArenaCreateRequest(0,1,2,2,40,1,1,0,0)))
        ground=encode_battle_ground(BattleGround(0,8,8,bytes(64),(),bytes(64)))
        service.start_loading(17,b'\x2e',lambda room:(ground,b'\x41'))
        service.configure_field(17,field)
        request=encode_move_request(BattleMove(101,((3,2),)))
        with self.assertRaises(ValueError):service.move(17,request)
        service.member_loaded(17,b'\x36');service.begin_turn(17,(101,),2)
        with self.assertRaises(ValueError):service.move(99,request)
        service.move(17,request)
        self.assertEqual(field.actor(101).x,3)
        now[0]=2.0
        with self.assertRaises(ValueError):service.move(17,encode_move_request(BattleMove(101,((4,2),))))
        self.assertEqual(field.actor(101).x,3)
        service.disconnect(17)
        self.assertEqual(service._fields,{})
