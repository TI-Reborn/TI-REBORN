import json
import unittest
from pathlib import Path
from tio.protocol.battle_soldier import (
    BattleSoldier, decode_battle_soldier, encode_battle_soldier, PacketError,
)


class BattleSoldierTests(unittest.TestCase):
    def test_equipment_matches_original_slot_dispatch(self):
        case=json.loads((Path(__file__).resolve().parents[1]/
                         'evidence/battle_equipment_native.json').read_text())
        actor=decode_battle_soldier(b'\x3b'+bytes.fromhex(case['body_hex']),human_equipment=True)
        self.assertEqual(actor.equipment_templates,
                         {e['slot_mask']:e['template_id'] for e in case['equipment_calls']})
        self.assertEqual(len(actor.equipment_templates),11)

    def test_original_read_fixtures_and_truncations(self):
        cases=json.loads((Path(__file__).resolve().parents[1]/
                          'evidence/battle_soldier_native_variants.json').read_text())
        for case in cases:
            packet=b'\x3b'+bytes.fromhex(case['body_hex'])
            human=case['profile']['human']
            soldier=decode_battle_soldier(packet,human_equipment=human)
            self.assertEqual(encode_battle_soldier(soldier),packet)
            self.assertEqual(soldier.soldier_id,1)
            for end in range(len(packet)):
                with self.assertRaises(PacketError):
                    decode_battle_soldier(packet[:end],human_equipment=human)
            with self.assertRaises(PacketError):
                decode_battle_soldier(packet+b'\0',human_equipment=human)
            fields=dict(soldier.fields)
            del fields['0x8c519b']
            with self.assertRaises(PacketError):
                encode_battle_soldier(BattleSoldier(human,fields))
            fields=dict(soldier.fields,unexpected=1)
            with self.assertRaises(PacketError):
                encode_battle_soldier(BattleSoldier(human,fields))

    def test_marker_replay_matches_native_model(self):
        cases=json.loads((Path(__file__).resolve().parents[1]/
                          'evidence/battle_soldier_replay.json').read_text())['cases']
        self.assertEqual(len(cases),6)
        for case in cases:
            soldier=decode_battle_soldier(bytes.fromhex(case['packet_hex']),
                                         human_equipment=case['profile']['human'])
            self.assertEqual(soldier.owner_id,case['model']['owner_id'])
            self.assertEqual(soldier.level,5)
            self.assertEqual(soldier.position,(31,47))
        for invalid in (None,0,1,'human'):
            with self.assertRaises(PacketError):
                decode_battle_soldier(b'\x3b',human_equipment=invalid)
