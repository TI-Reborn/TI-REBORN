import unittest
from tio.protocol.abilities import AbilityEntry,encode_abilities,decode_abilities
from tio.protocol.binary import PacketError
from tio.protocol.abilities import encode_ability_request,decode_ability_request


class AbilityProtocolTests(unittest.TestCase):
    def test_learning_request_native_bytes_and_strict_length(self):
        for opcode in (0x8f,0x90):
            wire=bytes([opcode])+bytes.fromhex('0400000017000000')
            self.assertEqual(encode_ability_request(4,23,opcode=opcode),wire)
            self.assertEqual(decode_ability_request(wire),(4,23,opcode))
            for n in range(len(wire)):
                with self.assertRaises(PacketError):decode_ability_request(wire[:n])
            with self.assertRaises(PacketError):decode_ability_request(wire+b'\0')
        with self.assertRaises(PacketError):decode_ability_request(bytes.fromhex('810400000017000000'))

    def test_known_layouts(self):
        learned=bytes.fromhex('80 04000000 0100 1a000000 02 01 64000000')
        learning=bytes.fromhex('8e 04000000 0100 17000000 01 c8000000')
        for wire,expected in [(learned,AbilityEntry(26,2,100,1)),(learning,AbilityEntry(23,1,200))]:
            owner,entries,is_learning=decode_abilities(wire)
            self.assertEqual((owner,entries),(4,(expected,)))
            self.assertEqual(encode_abilities(owner,entries,for_learning=is_learning),wire)
            for n in range(len(wire)):
                with self.assertRaises(PacketError):decode_abilities(wire[:n])
            with self.assertRaises(PacketError):decode_abilities(wire+b'\0')

    def test_profiles_cannot_mix(self):
        with self.assertRaises(PacketError):encode_abilities(1,(AbilityEntry(1,1,0),))
        with self.assertRaises(PacketError):encode_abilities(1,(AbilityEntry(1,1,0,1),),for_learning=True)
