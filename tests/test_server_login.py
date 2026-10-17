import unittest
from tio.protocol.binary import PacketError
from tio.protocol.server_login import *

class ServerLoginTests(unittest.TestCase):
    def test_request_layout(self):
        p=ServerLoginRequest(1,bytes.fromhex('0123456789abcdef'))
        golden=bytes.fromhex('07010123456789abcdef')
        self.assertEqual(encode_server_login_request(p),golden)
        self.assertEqual(decode_server_login_request(golden),p)
        live=bytes.fromhex('070118a28a0735000000')
        self.assertEqual(encode_server_login_request(decode_server_login_request(live)),live)
        for bad in [golden[:n] for n in range(len(golden))]+[golden+b'\0',b'\x08'+golden[1:]]:
            with self.assertRaises(PacketError):decode_server_login_request(bad)
        for p in (ServerLoginRequest(-1,b'0'*8),ServerLoginRequest(256,b'0'*8),ServerLoginRequest(1,b'0'*7)):
            with self.assertRaises(PacketError):encode_server_login_request(p)

    def test_result_status_and_invalid(self):
        for status in range(256):
            raw=bytes((8,status))
            self.assertEqual(encode_server_login_result(status),raw)
            self.assertEqual(decode_server_login_result(raw),status)
        for bad in (b'',b'\x08',b'\x08\0\0',b'\x07\0'):
            with self.assertRaises(PacketError):decode_server_login_result(bad)
        for status in (-1,256,True):
            with self.assertRaises(PacketError):encode_server_login_result(status)
