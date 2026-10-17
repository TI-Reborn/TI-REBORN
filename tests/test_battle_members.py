import json
import unittest
from pathlib import Path
from tio.protocol.battle_members import decode_battle_members,encode_battle_members,PacketError

class BattleMemberWireTests(unittest.TestCase):
    def test_independent_original_reader_fixtures(self):
        for fixture in ('battle_member_list_native.json','battle_member_nested_native.json'):
            data=json.loads((Path(__file__).resolve().parents[1]/'evidence'/fixture).read_text())
            for case in data['cases']:
                packet=bytes.fromhex(case['packet_hex']);decoded=decode_battle_members(packet)
                self.assertEqual(encode_battle_members(*decoded),packet)
                self.assertEqual(len(decoded[2]),case['count'])
                for end in range(len(packet)):
                    with self.assertRaises(PacketError):decode_battle_members(packet[:end])
                with self.assertRaises(PacketError):decode_battle_members(packet+b'\0')
                if decoded[2] and decoded[2][0].group1:
                    self.assertEqual(decoded[2][0].group1[0].unknown_u32_01,0x12345678)
                    self.assertEqual(decoded[2][0].group2[0].children,(400,500))

    def test_impossible_count(self):
        with self.assertRaises(PacketError):decode_battle_members(bytes.fromhex('250000ffffffff'))
