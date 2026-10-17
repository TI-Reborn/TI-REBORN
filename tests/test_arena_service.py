import unittest
from dataclasses import replace
from tio.arena_service import ArenaService
from tio.protocol.arena import ArenaCreateRequest, encode_create_request, decode_battle_settings_body
from tio.protocol.battle_members import decode_battle_members


class ArenaServiceTests(unittest.TestCase):
    def test_authoritative_turn_deadline(self):
        now=[100.0]
        service=ArenaService(clock=lambda:now[0])
        request=ArenaCreateRequest(0,1,2,2,40,1,1,0,0)
        service.create(17,b'Owner',encode_create_request(request))
        from tio.protocol.battle_ground import BattleGround,encode_battle_ground
        packets=(encode_battle_ground(BattleGround(0,1,1,b'\0',(),b'\0')),b'\x41')
        service.start_loading(17,b'\x2e',lambda room:packets)
        service.member_loaded(17,b'\x36')
        service.begin_turn(17,(101,),40)
        now[0]=139.99
        self.assertEqual(service.expire_turns(),())
        now[0]=140
        with self.assertRaises(ValueError):service.end_turn(17,b'\x3a\0\0\0\0')
        self.assertEqual(service.expire_turns(),((17,b'\x39'),))
        self.assertEqual(service.expire_turns(),())
        service.begin_turn(17,(101,),1)
        service.end_turn(17,b'\x3a\0\0\0\0')
        now[0]=200
        self.assertEqual(service.expire_turns(),())
    def test_loading_authorization_ack_and_cleanup(self):
        service=ArenaService()
        request=ArenaCreateRequest(0,1,2,2,40,1,1,0,0)
        service.create(17,b'Owner',encode_create_request(request))
        from tio.protocol.battle_ground import BattleGround,encode_battle_ground
        packets=(encode_battle_ground(BattleGround(0,1,1,b'\0',(),b'\0')),b'\x41')
        calls=[]
        def prepare(room):calls.append(room.room_id);return packets
        with self.assertRaises(ValueError):service.start_loading(99,b'\x2e',prepare)
        with self.assertRaises(ValueError):service.member_loaded(17,b'\x36')
        with self.assertRaises(ValueError):service.start_loading(17,b'\x2e\0',prepare)
        self.assertEqual(calls,[])
        self.assertEqual(service.start_loading(17,b'\x2e',prepare),packets)
        self.assertEqual(service.start_loading(17,b'\x2e',prepare),())
        self.assertEqual(len(calls),1)
        with self.assertRaises(ValueError):service.set_ready(17,b'\x2c\x01')
        self.assertEqual(service.member_loaded(17,b'\x36'),(b'\x37\x11\0\0\0',))
        self.assertEqual(service.member_loaded(17,b'\x36'),())
        self.assertEqual(service.begin_turn(17,(101,),40),b'\x38\x28\0\0\0')
        with self.assertRaises(ValueError):service.begin_turn(17,(101,),40)
        with self.assertRaises(ValueError):service.end_turn(99,b'\x3a\0\0\0\0')
        with self.assertRaises(ValueError):service.end_turn(17,b'\x3a\x66\0\0\0')
        self.assertEqual(service.end_turn(17,b'\x3a\x65\0\0\0'),b'\x39')
        with self.assertRaises(ValueError):service.end_turn(17,b'\x3a\0\0\0\0')
        service.disconnect(17)
        with self.assertRaises(ValueError):service.member_loaded(17,b'\x36')

    def test_failed_scene_preparation_allows_retry(self):
        service=ArenaService()
        request=ArenaCreateRequest(0,1,2,2,40,1,1,0,0)
        service.create(17,b'Owner',encode_create_request(request))
        for prepare in (lambda room:(),lambda room:(_ for _ in ()).throw(ValueError('resource missing'))):
            with self.assertRaises(ValueError):service.start_loading(17,b'\x2e',prepare)
            self.assertEqual(service._loading,{})
    def test_leave_clears_state_and_allows_new_creation(self):
        service=ArenaService()
        request=ArenaCreateRequest(0,1,2,2,40,1,1,0,0)
        first,_=service.create(17,b'Owner',encode_create_request(request))
        for invalid in (b'\x2a',b'\x2a\0',b'\x2a\x01\0'):
            with self.assertRaises(ValueError): service.leave(17,invalid)
            self.assertEqual(service.rooms.snapshot(),(first,))
        self.assertEqual(service.leave(17,b'\x2a\x01'),bytes.fromhex('f01800000000000000'))
        self.assertEqual(service.rooms.snapshot(),())
        self.assertEqual(service.leave(17,b'\x2a\x01'),bytes.fromhex('f01800000000000000'))
        second,_=service.create(17,b'Owner',encode_create_request(request))
        self.assertGreater(second.room_id,first.room_id)

    def test_ready_toggle_updates_only_authenticated_member_and_preserves_roster(self):
        service=ArenaService()
        request=ArenaCreateRequest(0,1,2,2,40,1,1,0,0)
        service.create(17,b'Owner',encode_create_request(request))
        for value in (1,1,0):
            mode,flag,members=decode_battle_members(service.set_ready(17,bytes((0x2c,value))))
            self.assertEqual((flag,members[0].ready,members[0].online),(1,value,1))
            _,replies=service.create(17,b'Owner',encode_create_request(request))
            self.assertEqual(decode_battle_members(replies[1])[2][0].ready,value)
        for packet in (b'\x2c',b'\x2c\x02',b'\x2c\x01\0'):
            with self.assertRaises(ValueError):service.set_ready(17,packet)
        with self.assertRaises(ValueError):service.set_ready(99,b'\x2c\x01')
        service.disconnect(17)
        with self.assertRaises(ValueError):service.set_ready(17,b'\x2c\x01')

    def test_create_replies_use_authenticated_identity_and_selection(self):
        service = ArenaService()
        request = ArenaCreateRequest(0, 3, 2, 2, 80, 3, 3, 0, 0)
        room, replies = service.create(17, b'Owner', encode_create_request(request))
        self.assertEqual(room.owner_id, 17)
        self.assertEqual(replies[0][0], 0x6c)
        settings = decode_battle_settings_body(replies[0][1:])
        self.assertEqual((settings.owner_name, settings.mode, settings.map_size, settings.players_count, settings.soldiers_count), (b'Owner', 0, 3, 2, 3))
        mode, flag, members = decode_battle_members(replies[1])
        self.assertEqual((mode, flag, members[0].character_id, members[0].name), (0, 0, 17, b'Owner'))
        self.assertEqual((members[0].ready, members[0].online), (0, 1))
        self.assertEqual(service.create(17, b'Owner', encode_create_request(request)), (room, replies))
        service.disconnect(17)
        self.assertEqual(service.rooms.snapshot(), ())

    def test_invalid_packets_and_unsupported_wagers_do_not_mutate(self):
        service = ArenaService()
        request = ArenaCreateRequest(0, 1, 2, 2, 40, 1, 1, 0, 0)
        packet = encode_create_request(request)
        for bad in (packet[:-1], packet+b'\0', encode_create_request(replace(request, unknown_u32_02=100)), encode_create_request(replace(request, mode=16))):
            with self.assertRaises(ValueError): service.create(1, b'Owner', bad)
            self.assertEqual(service.rooms.snapshot(), ())
        with self.assertRaises(ValueError): service.create(1, b'Bad\0Name', packet)
        self.assertEqual(service.rooms.snapshot(), ())
