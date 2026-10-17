import json
from pathlib import Path
import unittest
from tio.protocol.battle_position import BattlePositionRequest,decode_position_request,encode_position_request
from tio.protocol.binary import PacketError

class BattlePositionTests(unittest.TestCase):
    def test_native_fixtures(self):
        path=Path(__file__).resolve().parents[1]/'evidence/battle_position_request_native.json'
        for case in json.loads(path.read_text(encoding='utf-8'))['cases']:
            if case['disabled']:continue
            packet=bytes.fromhex(case['packet_hex'])
            request=BattlePositionRequest(case['actor_id'],case['x'],case['y'])
            self.assertEqual(decode_position_request(packet),request)
            self.assertEqual(encode_position_request(request),packet)
    def test_malformed(self):
        packet=encode_position_request(BattlePositionRequest(17,2,3))
        for bad in [packet[:n] for n in range(len(packet))]+[packet+b'\0',b'\x45'+packet[1:]]:
            with self.assertRaises(PacketError):decode_position_request(bad)
