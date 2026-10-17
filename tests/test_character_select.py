import unittest
from tio.protocol.character_select import *
from tio.protocol.binary import PacketError
from tio.protocol.transport import InitialCipher,encode_initial_frame
from tio.protocol.mode1 import derive_mode1_key,encode_mode1_completion
from tio.protocol.auth2 import encode_auth2_result

class EmptyCharacterListTests(unittest.TestCase):
    def test_exact_empty_branch(self):
        self.assertEqual(encode_empty_character_list(),b'\x10\0\0')
        decode_empty_character_list(b'\x10\0\0')
        for bad in (b'',b'\x10',b'\x10\0',b'\x10\1\0',b'\x10\0\0\0',b'\x11\0\0'):
            with self.assertRaises(PacketError):decode_empty_character_list(bad)

    def test_following_auth_cipher(self):
        key=derive_mode1_key(bytes(range(8)));sender=InitialCipher('S2C',key);receiver=InitialCipher('S2C',key)
        for plain in (encode_mode1_completion(0),encode_auth2_result(0),encode_empty_character_list()):
            frame=encode_initial_frame(plain,sender)
            self.assertEqual(receiver.transform(frame[2:],encrypt=False),plain)
        self.assertEqual(sender.key,receiver.key)
