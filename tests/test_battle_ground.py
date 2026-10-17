import json
import unittest
from dataclasses import replace
from pathlib import Path
from tio.protocol.battle_ground import (
    BattleGround, GroundEntry, encode_battle_ground, decode_battle_ground, PacketError,
)


class BattleGroundTests(unittest.TestCase):
    def test_scene_reader_layers(self):
        fixture=json.loads((Path(__file__).resolve().parents[1]/
                            'evidence/battle_ground_scene_native.json').read_text())
        for case in fixture['cases']:
            packet=bytes.fromhex(case['packet_hex'])
            if case.get('zero_width_enters_cell_loop'):
                with self.assertRaises(PacketError):decode_battle_ground(packet)
            else:
                ground=decode_battle_ground(packet)
                self.assertEqual(list(ground.first_layer),case['first_layer'])
                self.assertEqual(list(ground.second_layer),case['second_layer'])

    def test_original_reader_evidence_and_truncations(self):
        fixture = json.loads((Path(__file__).resolve().parents[1]/
                              'evidence/battle_ground_native.json').read_text())
        for case in fixture['cases']:
            packet = bytes.fromhex(case['packet_hex'])
            if case['width']==0 or case['height']==0:
                # silver accepts this structural probe, but ti.exe's byte loops
                # underflow: it is not a safe complete-client packet.
                with self.assertRaises(PacketError):
                    decode_battle_ground(packet)
                continue
            ground = decode_battle_ground(packet)
            self.assertEqual((ground.width, ground.height), (case['width'], case['height']))
            self.assertEqual(list(ground.second_layer), case['grid'])
            self.assertEqual([entry.name.hex() for entry in ground.entries], case['strings'])
            self.assertEqual(encode_battle_ground(ground), packet)
            for end in range(len(packet)):
                with self.assertRaises(PacketError):
                    decode_battle_ground(packet[:end])
            with self.assertRaises(PacketError):
                decode_battle_ground(packet+b'\0')

    def test_invalid_dimensions_entries_and_frame(self):
        ground = BattleGround(0, 1, 1, b'\0', (), b'\1')
        for invalid in (replace(ground, first_layer=b''), replace(ground, width=256),
                        BattleGround(0,0,0,b'',(),b''),
                        replace(ground, entries=(GroundEntry(b'a\0b', 0, 0),)),
                        replace(ground, entries=(GroundEntry(b'a'*65530, 0, 0),))):
            with self.assertRaises(PacketError):
                encode_battle_ground(invalid)
        for packet in (b'\x34'+bytes(5), b'\x35\0\xff\xff',
                       b'\x35\0\0\0\xff\xff', bytes(65534)):
            with self.assertRaises(PacketError):
                decode_battle_ground(packet)
