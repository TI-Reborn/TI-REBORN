import json
import unittest
from pathlib import Path
from tio.protocol.binary import PacketError
from tio.protocol.battle_move import BattleMove, encode_battle_move, decode_battle_move, encode_move_request, decode_move_request


class BattleMoveTests(unittest.TestCase):
    def test_original_request(self):
        p = Path(__file__).resolve().parents[1]/'evidence/move_request_native.json'
        for case in json.loads(p.read_text(encoding='utf-8'))['cases']:
            for wire in case['packets_hex']:
                packet = bytes.fromhex(wire)
                move = BattleMove(17, tuple(map(tuple, case['path'])))
                self.assertEqual(encode_move_request(move), packet)
                self.assertEqual(decode_move_request(packet), move)
        for packet in (b'', b'\x3c', b'\x3c\x11\0\0\0\x02\x03\x02', b'\x3d\x11\0\0\0\0'):
            with self.assertRaises(PacketError):
                decode_move_request(packet)

    def test_native_paths(self):
        p = Path(__file__).resolve().parents[1]/'evidence/battle_move_native.json'
        for case in json.loads(p.read_text(encoding='utf-8'))['cases']:
            move = BattleMove(17, tuple(map(tuple, case['path'])))
            packet = bytes.fromhex(case['packet_hex'])
            self.assertEqual(decode_battle_move(packet), move)
            self.assertEqual(encode_battle_move(move), packet)

    def test_malformed_paths(self):
        packet = encode_battle_move(BattleMove(17, ((2,3),)))
        for bad in (packet[:-1], packet+b'\0', b'\x3e'+packet[1:]):
            with self.assertRaises(PacketError):
                decode_battle_move(bad)
        for path in (((256,0),), ((0,0),)*256):
            with self.assertRaises(PacketError):
                encode_battle_move(BattleMove(17,path))
