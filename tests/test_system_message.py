import unittest
from tio.protocol.system_message import *


class CurrentTownTests(unittest.TestCase):
    def test_open_town_view_has_no_arguments(self):
        self.assertEqual(encode_open_town_view(), bytes.fromhex('f07500000000000000'))

    def test_original_client_fixture(self):
        raw = bytes.fromhex('f062000000010000000100000003000000')
        self.assertEqual(encode_current_town(3), raw)
        self.assertEqual(decode_current_town(raw), 3)
        for n in range(len(raw)):
            with self.assertRaises(PacketError):
                decode_current_town(raw[:n])
        for data in (raw+b'\0', raw[:5]+b'\2'+raw[6:], raw[:9]+b'\0'+raw[10:]):
            with self.assertRaises(PacketError):
                decode_current_town(data)
        for value in (0, -1, 256, True):
            with self.assertRaises(PacketError):
                encode_current_town(value)
