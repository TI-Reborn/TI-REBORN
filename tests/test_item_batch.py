import json
import unittest
from pathlib import Path
from tio.protocol.item_batch import decode_item_batch,encode_item_batch,PacketError

class ItemBatchTests(unittest.TestCase):
    def test_original_packets_and_invalid_lengths(self):
        fixture=json.loads((Path(__file__).resolve().parents[1]/'evidence/item_batch_native.json').read_text())
        for case in fixture['cases']:
            packet=bytes.fromhex(case['packet_hex'])
            batch=decode_item_batch(packet)
            self.assertEqual(batch.first,tuple(map(tuple,case['first'])))
            self.assertEqual(batch.second,tuple(map(tuple,case['second'])))
            self.assertEqual((batch.mode,batch.identity),(case['mode'],case['identity']))
            self.assertEqual(encode_item_batch(batch),packet)
            for end in range(len(packet)):
                with self.assertRaises(PacketError):decode_item_batch(packet[:end])
            with self.assertRaises(PacketError):decode_item_batch(packet+b'\0')
