import json
from pathlib import Path
import unittest

from tio.protocol.binary import PacketError
from tio.protocol.item_action import ItemAction, decode_item_action, encode_item_action, item_target_option


class ItemActionTests(unittest.TestCase):
    def test_original_target_conversion(self):
        path = Path(__file__).resolve().parents[1] / 'evidence/item_target_native.json'
        for case in json.loads(path.read_text(encoding='utf-8'))['cases']:
            with self.subTest(case=case):
                self.assertEqual(item_target_option(case['target_mask']), case['option'])
                action = ItemAction(17, 1001, case['option'])
                self.assertEqual(action.target_mask, None if case['option'] == 255 else case['target_mask'])
        for option in (19, 254, -1, 256):
            with self.assertRaises(PacketError):
                _ = ItemAction(17, 1001, option).target_mask

    def test_original_writer_fixtures(self):
        evidence = Path(__file__).resolve().parents[1] / 'evidence/equip_request_native.json'
        for case in json.loads(evidence.read_text(encoding='utf-8'))['writer_cases']:
            with self.subTest(case=case):
                packet = bytes.fromhex(case['packet_hex'])
                expected = ItemAction(case['pet_id'], case['instance_id'], case['option'])
                self.assertEqual(decode_item_action(packet), expected)
                self.assertEqual(encode_item_action(expected), packet)

    def test_rejects_malformed_packets(self):
        packet = bytes.fromhex('3311000000e9030000ff')
        for bad in [packet[:n] for n in range(len(packet))] + [packet+b'\0', b'\x32'+packet[1:]]:
            with self.subTest(packet=bad.hex()):
                with self.assertRaises(PacketError):
                    decode_item_action(bad)
