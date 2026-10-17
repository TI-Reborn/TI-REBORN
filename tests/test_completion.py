import unittest
from tio.protocol.transport import *
from tio.protocol.login import *

class CompletionTests(unittest.TestCase):
    def test_success_golden_and_key_continuity(self):
        p=InitialCompletion(0,0,0x11223344)
        self.assertEqual(encode_initial_completion(p).hex(),'02000044332211')
        self.assertEqual(decode_initial_completion(encode_initial_completion(p)),p)
        cipher=InitialCipher('S2C')
        encode_initial_frame(encode_initial_challenge(InitialChallenge(0,0x12345678,0,0xabcdef01)),cipher)
        self.assertEqual(encode_initial_frame(encode_initial_completion(p),cipher).hex(),'090027b81d092b98b3')
        self.assertEqual(encode_initial_frame(encode_login_success(),cipher).hex(),'04009b3e')

    def test_failure_and_boundaries(self):
        for status in (1,255):
            p=InitialCompletion(status,255)
            self.assertEqual(decode_initial_completion(encode_initial_completion(p)),p)
        for value in (0,0xffffffff):
            p=InitialCompletion(0,255,value)
            self.assertEqual(decode_initial_completion(encode_initial_completion(p)),p)
        for p in (InitialCompletion(0,0),InitialCompletion(256,0),InitialCompletion(0,-1,0),InitialCompletion(0,0,2**32),InitialCompletion(1,0,0)):
            with self.assertRaises(PacketError):encode_initial_completion(p)

    def test_invalid_wire(self):
        for good in (bytes.fromhex('02000044332211'),bytes.fromhex('020100')):
            for bad in [good[:n] for n in range(len(good))]+[good+b'\0',b'\x03'+good[1:]]:
                with self.assertRaises(PacketError):decode_initial_completion(bad)

class BasicLoginTests(unittest.TestCase):
    def test_live_golden(self):
        p=BasicLoginRequest(b'probe_user',b'probe_password',transform_auth_value(0x11223344))
        golden=bytes.fromhex('0370726f62655f757365720070726f62655f70617373776f72640030c8c437')
        self.assertEqual(encode_basic_login_request(p),golden)
        self.assertEqual(decode_basic_login_request(golden),p)
        self.assertEqual(encode_login_success(),bytes.fromhex('0400'))
        decode_login_success(b'\x04\x00')

    def test_boundaries_and_invalid(self):
        for n in (0,255):
            p=BasicLoginRequest(b'a'*n,b'b'*n,0xffffffff)
            self.assertEqual(decode_basic_login_request(encode_basic_login_request(p)),p)
        for p in (BasicLoginRequest(b'a\0',b'',0),BasicLoginRequest(b'a'*256,b'',0),BasicLoginRequest(b'',b'',-1)):
            with self.assertRaises(PacketError): encode_basic_login_request(p)
        good=encode_basic_login_request(BasicLoginRequest(b'a',b'b',1))
        for bad in [good[:n] for n in range(len(good))]+[good+b'\0',b'\x0a'+good[1:],b'\x03'+b'x'*256+b'\0\0\0\0\0\0']:
            with self.assertRaises(PacketError):decode_basic_login_request(bad)
        for bad in (b'',b'\x04',b'\x04\x01',b'\x04\x00\x00'):
            with self.assertRaises(PacketError):decode_login_success(bad)
