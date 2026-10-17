import unittest
from tio.protocol.pet_state import encode_pet_state_request,decode_pet_state_request
from tio.protocol.binary import PacketError


class PetStateTests(unittest.TestCase):
    def test_native_shape_and_reject_malformed(self):
        packet=bytes.fromhex('670400000000000000')
        self.assertEqual(encode_pet_state_request(4,0),packet)
        self.assertEqual(decode_pet_state_request(packet),(4,0))
        for p in (packet[:-1],packet+b'\0',b'\x68'+packet[1:],bytes.fromhex('670400000000010000')):
            with self.assertRaises(PacketError):decode_pet_state_request(p)
