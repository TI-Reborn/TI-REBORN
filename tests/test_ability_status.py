import unittest
from tio.protocol.ability_status import AbilityStatus,encode_ability_status,decode_ability_status
from tio.protocol.binary import PacketError


class AbilityStatusTests(unittest.TestCase):
    def test_native_packet_and_strict_input(self):
        entries=(AbilityStatus(23,1,3,3),)
        packet=bytes.fromhex('7f01110000000100000017000000010300000003000000')
        self.assertEqual(encode_ability_status(17,entries),packet)
        self.assertEqual(decode_ability_status(packet),(17,entries))
        for invalid in (packet[:-1],packet+b'\0',b'\x7f\x02'+packet[2:],packet[:6]+b'\x00\x01\0\0'):
            with self.assertRaises(PacketError):decode_ability_status(invalid)
        with self.assertRaises(PacketError):encode_ability_status(17,entries*256)
        with self.assertRaises(PacketError):encode_ability_status(17,[AbilityStatus(23,1,2,3)])
