import json
import unittest
from pathlib import Path
from tio.protocol.battle_loaded import (
    validate_battle_loaded, encode_member_loaded, decode_member_loaded, PacketError,
    encode_battle_load_end,
)


class BattleLoadedTests(unittest.TestCase):
    def test_native_packets_and_malformed_frames(self):
        evidence=json.loads((Path(__file__).resolve().parents[1]/
                             'evidence/battle_loaded_native.json').read_text())
        for case in evidence['completion']:
            if case.get('load_end_packet'):
                self.assertEqual(encode_battle_load_end().hex(),case['load_end_packet'])
                self.assertEqual(case['state_after'],3 if case['pending'] else 4)
            for _,wire in case['transport_calls']:
                validate_battle_loaded(bytes.fromhex(wire))
        for case in evidence['members']:
            packet=bytes.fromhex(case['packet_hex'])
            self.assertEqual(encode_member_loaded(decode_member_loaded(packet)),packet)
            for end in range(len(packet)):
                with self.assertRaises(PacketError):decode_member_loaded(packet[:end])
            with self.assertRaises(PacketError):decode_member_loaded(packet+b'\0')
        for packet in (b'',b'\x35',b'\x36\0'):
            with self.assertRaises(PacketError):validate_battle_loaded(packet)
