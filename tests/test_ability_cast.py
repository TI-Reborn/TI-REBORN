import unittest
from tio.protocol.ability_cast import AbilityCast,encode_ability_cast,decode_ability_cast
from tio.protocol.binary import PacketError

class AbilityCastTests(unittest.TestCase):
    def test_native_layout_and_strict_input(self):
        wire=bytes.fromhex('81 17000000 04000000 00000000 03 07')
        expected=AbilityCast(23,4,0,3,7)
        self.assertEqual(decode_ability_cast(wire),expected)
        self.assertEqual(encode_ability_cast(expected),wire)
        for n in range(len(wire)):
            with self.assertRaises(PacketError):decode_ability_cast(wire[:n])
        with self.assertRaises(PacketError):decode_ability_cast(wire+b'\0')
