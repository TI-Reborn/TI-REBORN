import unittest
from tio.protocol.character_create import *

class CreateTests(unittest.TestCase):
    def test_layout(self):
        p=CharacterCreateRequest(b'Probe',0x1234,(1,2,3,4))
        wire=bytes.fromhex('1150726f626500341201020304')
        self.assertEqual(encode_character_create(p),wire)
        self.assertEqual(decode_character_create(wire),p)
        for n in range(len(wire)):
            with self.assertRaises(PacketError):decode_character_create(wire[:n])
        with self.assertRaises(PacketError):decode_character_create(wire+b'\0')
    def test_result(self):
        for status in (0,1,2,3,4,255):
            self.assertEqual(decode_character_create_result(encode_character_create_result(status)),status)
        with self.assertRaises(PacketError):decode_character_create_result(b'\x12')
        with self.assertRaises(PacketError):decode_character_create_result(b'\x12\0\0')
    def test_reject_bad_fields(self):
        for p in (CharacterCreateRequest(b'a\0',0,(0,)*4),CharacterCreateRequest(b'a',65536,(0,)*4),CharacterCreateRequest(b'a',0,(256,)*4),CharacterCreateRequest(b'a',0,(0,)*3)):
            with self.assertRaises(PacketError):encode_character_create(p)
