import json
import unittest
from pathlib import Path
from tio.protocol.binary import PacketError
from tio.protocol.known_mines import KnownMine, encode_known_mines, decode_known_mines


class KnownMinesTests(unittest.TestCase):
    def test_original_client_fixtures(self):
        evidence = Path(__file__).resolve().parents[1]/'evidence/known_mines_native.json'
        for case in json.loads(evidence.read_text(encoding='utf-8'))['cases']:
            rows = tuple(KnownMine(*r) for r in case['rows'])
            packet = bytes.fromhex(case['packet_hex'])
            self.assertEqual(encode_known_mines(rows), packet)
            self.assertEqual(decode_known_mines(packet), rows)

    def test_invalid_counts_and_lengths(self):
        valid = encode_known_mines([KnownMine(2,3,901,1)])
        for bad in (valid[:-1], valid+b'\0', b'\xc8\x3e\xff\xff\xff\xff', b'\xc8\x3d'+valid[2:]):
            with self.assertRaises(PacketError):
                decode_known_mines(bad)
        with self.assertRaises(PacketError):
            encode_known_mines([KnownMine(0,0,1,0)]*4096)
