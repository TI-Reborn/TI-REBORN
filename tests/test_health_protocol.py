import unittest
from tio.protocol.health import encode_health
from tio.protocol.binary import PacketError

class HealthProtocolTests(unittest.TestCase):
    def test_native_packet_and_bounds(self):
        self.assertEqual(encode_health(17,85),bytes.fromhex('4e 11000000 01000000 04000000 55000000 00'))
        for health in (-1,65536,True,12.5):
            with self.assertRaises(PacketError):encode_health(17,health)
