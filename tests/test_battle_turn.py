import json
from pathlib import Path
import unittest
from tio.protocol.battle_turn import encode_end_turn, decode_end_turn
from tio.protocol.binary import PacketError
from tio.protocol.battle_turn import encode_your_turn,decode_your_turn,encode_turn_now

class BattleTurnTests(unittest.TestCase):
    def test_turn_now_matches_native_wire_classifier(self):
        # 0x1B is the internal message type; C8/17 is its wire header.
        self.assertEqual(encode_turn_now(0x10000002,40),bytes.fromhex('c8170200001028000000'))

    def test_turn_duration(self):
        for seconds in (1,40,120):
            self.assertEqual(decode_your_turn(encode_your_turn(seconds)),seconds)
        with self.assertRaises(PacketError):decode_your_turn(b'\x38\x28')
        with self.assertRaises(PacketError):decode_your_turn(encode_your_turn(40)+b'\0')
    def test_original_packets(self):
        path=Path(__file__).resolve().parents[1]/'evidence/end_turn_native.json'
        for case in json.loads(path.read_text(encoding='utf-8'))['cases']:
            packet=bytes.fromhex(case['packet_hex'])
            if packet:self.assertEqual(encode_end_turn(decode_end_turn(packet)),packet)

    def test_strict_length(self):
        packet=encode_end_turn(17)
        for bad in [packet[:n] for n in range(5)]+[packet+b'\0',b'\x39'+packet[1:]]:
            with self.assertRaises(PacketError):decode_end_turn(bad)
