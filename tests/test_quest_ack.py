import unittest
from tio.protocol.quest_ack import encode_ack,decode_ack
from tio.protocol.binary import PacketError


class QuestAckTests(unittest.TestCase):
    def test_native_cardinal_slot(self):
        self.assertEqual(encode_ack(1000),bytes.fromhex('b810e8030000'))
        self.assertEqual(decode_ack(encode_ack(1018)),1018)

    def test_strict_identity_and_length(self):
        for packet in (b'\xb8\x10',encode_ack(1000)[:-1],encode_ack(1000)+b'\0',
                       b'\xb8\x10'+bytes(4),bytes.fromhex('b810e803000001000000')):
            with self.assertRaises(PacketError):decode_ack(packet)

