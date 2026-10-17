import unittest
from tio.protocol.binary import PacketError
from tio.protocol.auth2 import *
from tio.protocol.mode1 import derive_mode1_key,encode_mode1_completion
from tio.protocol.transport import InitialCipher,encode_initial_frame

class Auth2Tests(unittest.TestCase):
    def test_live_request(self):
        p=Auth2Request(b'0.21:63',b'')
        raw=bytes.fromhex('0c302e32313a36330000')
        self.assertEqual(encode_auth2_request(p),raw)
        self.assertEqual(decode_auth2_request(raw),p)

    def test_strings_and_invalid(self):
        for p in (Auth2Request(b'',b''),Auth2Request(b'a'*255,b'b'*255),Auth2Request(b'\xff',b'echo')):
            self.assertEqual(decode_auth2_request(encode_auth2_request(p)),p)
        raw=encode_auth2_request(Auth2Request(b'abc',b'echo'))
        for bad in [raw[:n] for n in range(len(raw))]+[raw+b'\0',b'\x0d'+raw[1:],b'\x0c'+b'a'*256+b'\0\0']:
            with self.assertRaises(PacketError):decode_auth2_request(bad)
        for p in (Auth2Request(b'a\0',b''),Auth2Request(b'',b'b'*256),Auth2Request('text',b'')):
            with self.assertRaises(PacketError):encode_auth2_request(p)

    def test_status(self):
        for status in range(256):
            self.assertEqual(decode_auth2_result(encode_auth2_result(status)),status)
        for bad in (b'',b'\x0d',b'\x0d\0\0',b'\x0c\0'):
            with self.assertRaises(PacketError):decode_auth2_result(bad)
        for status in (-1,256,True):
            with self.assertRaises(PacketError):encode_auth2_result(status)

    def test_live_result_cipher(self):
        cipher=InitialCipher('S2C',derive_mode1_key(bytes(range(8))))
        encode_initial_frame(encode_mode1_completion(0),cipher)
        self.assertEqual(encode_initial_frame(encode_auth2_result(0),cipher).hex(),'04002653')
