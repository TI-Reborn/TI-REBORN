import unittest
from tio.protocol.binary import PacketError
from tio.protocol.mode1 import *
from tio.protocol.transport import InitialCipher,InitialFrameReader,encode_initial_frame

class Mode1Tests(unittest.TestCase):
    def test_challenge_golden(self):
        seed=bytes(range(8))
        self.assertEqual(encode_mode1_challenge_frame(seed).hex(),'0b00090001020304050607')
        self.assertEqual(decode_mode1_challenge(encode_mode1_challenge(seed)),seed)
        self.assertEqual(derive_mode1_key(seed).hex(),'ac2b759a3b3f57b3')
        raw=encode_mode1_challenge(seed)
        for bad in [raw[:n] for n in range(len(raw))]+[raw+b'\0',b'\x0a'+raw[1:]]:
            with self.assertRaises(PacketError):decode_mode1_challenge(bad)

    def test_live_cipher_continuity(self):
        key=derive_mode1_key(bytes(range(8)))
        reader=InitialFrameReader(InitialCipher('C2S',key))
        raw=bytes.fromhex('0b00b976692b9dacb43a98')
        p=Mode1Reply(0x2c792098,0x11223344)
        packet=reader.feed(raw)[0]
        self.assertEqual(decode_mode1_reply(packet),p)
        self.assertEqual(encode_mode1_reply(p),packet)
        self.assertEqual(reader.cipher.key.hex(),'a32b75ac3b3f57b3')
        self.assertEqual(reader.feed(bytes.fromhex('0c00bfd8c9c05d120f9f2c7b')),[bytes.fromhex('0c302e32313a36330000')])
        reader.finish()
        self.assertEqual(encode_initial_frame(encode_mode1_completion(0),InitialCipher('S2C',key)).hex(),'0400a78c')

    def test_completion(self):
        for status in range(256):
            raw=bytes((11,status))
            self.assertEqual(encode_mode1_completion(status),raw)
            self.assertEqual(decode_mode1_completion(raw),status)
        for bad in (b'',b'\x0b',b'\x0b\0\0',b'\x0a\0'):
            with self.assertRaises(PacketError):decode_mode1_completion(bad)

    def test_invalid(self):
        for seed in (b'',b'0'*7,b'0'*9,None):
            with self.assertRaises(PacketError):derive_mode1_key(seed)
            with self.assertRaises(PacketError):InitialCipher('C2S',seed)
        good=encode_mode1_reply(Mode1Reply(0,0xffffffff))
        for bad in [good[:n] for n in range(len(good))]+[good+b'\0',b'\x09'+good[1:]]:
            with self.assertRaises(PacketError):decode_mode1_reply(bad)
        with self.assertRaises(PacketError):encode_mode1_reply(Mode1Reply(-1,0))
        with self.assertRaises(PacketError):encode_mode1_completion(256)
