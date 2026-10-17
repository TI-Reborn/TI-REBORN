import json
import unittest
from pathlib import Path
from tio.protocol.action_points import encode_action_points
from tio.protocol.binary import PacketError


class ActionPointsTests(unittest.TestCase):
    def test_original_serializer(self):
        p=Path(__file__).resolve().parents[1]/'evidence/action_points_native.json'
        for case in json.loads(p.read_text(encoding='utf-8'))['cases']:
            self.assertEqual(encode_action_points(17,case['points']).hex(),case['packet_hex'])
        for points in (-1,256,1.5):
            with self.assertRaises(PacketError):encode_action_points(17,points)
