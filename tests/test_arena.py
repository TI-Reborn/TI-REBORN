import json
import unittest
from pathlib import Path
from tio.protocol.arena import decode_room_list, encode_room_list, PacketError

class ArenaTests(unittest.TestCase):
    def test_native_fixture_and_all_truncations(self):
        fixture=json.loads((Path(__file__).resolve().parents[1]/'evidence/arena_room_native.json').read_text())
        for case in fixture['cases']:
            wire=bytes.fromhex(case['packet_hex'])
            self.assertEqual(encode_room_list(decode_room_list(wire)),wire)
            for end in range(len(wire)):
                with self.assertRaises(PacketError):decode_room_list(wire[:end])
            with self.assertRaises(PacketError):decode_room_list(wire+b'\0')
        room=decode_room_list(bytes.fromhex(fixture['cases'][1]['packet_hex']))[0]
        self.assertEqual((room.category,room.name,room.unknown_u32_00,room.unknown_u32_04),(3,b'Room',101,404))

    def test_negative_count(self):
        with self.assertRaises(PacketError):decode_room_list(bytes.fromhex('ba02ffff'))

class ArenaMemberTests(unittest.TestCase):
    def test_independent_native_packets_and_truncations(self):
        from tio.protocol.arena import decode_member_list, encode_member_list
        fixture=json.loads((Path(__file__).resolve().parents[1]/'evidence/arena_members_native.json').read_text())
        for case in fixture['cases']:
            packet=bytes.fromhex(case['packet_hex'])
            decoded=decode_member_list(packet)
            self.assertEqual(encode_member_list(*decoded),packet)
            self.assertEqual(decoded[2][0].character_id,case['member_id'])
            self.assertEqual(len(decoded[2][0].pets),case['pet_count'])
            for end in range(len(packet)):
                with self.assertRaises(PacketError):decode_member_list(packet[:end])
            with self.assertRaises(PacketError):decode_member_list(packet+b'\0')

    def test_client_slot_limits(self):
        from tio.protocol.arena import ArenaMember, ArenaMemberPet, encode_member_list, decode_member_list
        member=ArenaMember(1,b'Player',0,0,0)
        with self.assertRaises(PacketError):encode_member_list(1,0,[member]*9)
        pet=ArenaMemberPet(0,0,0,(0,)*7,b'Pet')
        with self.assertRaises(PacketError):encode_member_list(1,0,[ArenaMember(1,b'P',0,0,0,(pet,)*4)])
        for count in (9,65535):
            packet=b'\xba\x0b'+bytes(5)+count.to_bytes(2,'little')
            with self.assertRaises(PacketError):decode_member_list(packet)

class ArenaRemoveTests(unittest.TestCase):
    def test_native_callbacks_and_strict_modes(self):
        from tio.protocol.arena import decode_remove_request, encode_remove_request, ArenaRemoveRequest
        for wire,char,kick in (('ba050b00000000',11,False),('ba051600000001',22,True)):
            packet=bytes.fromhex(wire)
            self.assertEqual(decode_remove_request(packet),ArenaRemoveRequest(char,kick))
            self.assertEqual(encode_remove_request(ArenaRemoveRequest(char,kick)),packet)
            for end in range(len(packet)):
                with self.assertRaises(PacketError):decode_remove_request(packet[:end])
        for wire in ('ba050100000002','ba05010000000000'):
            with self.assertRaises(PacketError):decode_remove_request(bytes.fromhex(wire))

class ArenaCreateTests(unittest.TestCase):
    def test_native_request_layout_and_truncation(self):
        from tio.protocol.arena import decode_create_request, encode_create_request
        fixture=json.loads((Path(__file__).resolve().parents[1]/'evidence/arena_create_request_native.json').read_text())
        for case in fixture['cases']:
            packet=bytes.fromhex(case['packet_hex'])
            request=decode_create_request(packet)
            self.assertEqual(len(packet),20)
            self.assertEqual((request.mode,request.map_size,request.players_count),tuple(case['arguments'][:3]))
            self.assertEqual(encode_create_request(request),packet)
            for end in range(len(packet)):
                with self.assertRaises(PacketError):decode_create_request(packet[:end])
            with self.assertRaises(PacketError):decode_create_request(packet+b'\0')

class ArenaStartTests(unittest.TestCase):
    def test_native_start_variants_require_room_mode(self):
        from tio.protocol.arena import decode_room_start
        fixture=json.loads((Path(__file__).resolve().parents[1]/'evidence/room_actions_native.json').read_text())
        cases=[case for case in fixture['cases'] if case['entry']=='0xa08ab0']
        self.assertEqual(len(cases),4)
        for case in cases:
            wire=bytes.fromhex(case['packet_hex'])
            mode=0 if case['eax']==255 else 16
            self.assertEqual(decode_room_start(wire,mode=mode),None if mode==0 else case['eax'])
            with self.assertRaises(PacketError):decode_room_start(wire,mode=16 if mode==0 else 0)
        for wire in (b'', b'\x2d', b'\x2e\x04', b'\x2e\0\0'):
            with self.assertRaises(PacketError):decode_room_start(wire,mode=16)


class BattleSettingsTests(unittest.TestCase):
    def test_original_reader_fixtures(self):
        from tio.protocol.arena import decode_battle_settings_body, encode_battle_settings_body
        fixture=json.loads((Path(__file__).resolve().parents[1]/'evidence/battle_settings_native.json').read_text())
        for case in fixture['cases']:
            body=bytes.fromhex(case['body_hex'])
            value=decode_battle_settings_body(body)
            self.assertEqual(value.mode,case['mode'])
            self.assertEqual(encode_battle_settings_body(value),body)
            for end in range(len(body)):
                with self.assertRaises(PacketError):decode_battle_settings_body(body[:end])
            with self.assertRaises(PacketError):decode_battle_settings_body(body+b'\0')
