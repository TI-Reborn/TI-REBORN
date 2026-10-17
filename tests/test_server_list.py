import unittest
from tio.protocol.binary import PacketError
from tio.protocol.server_list import *

class ServerListTests(unittest.TestCase):
    def test_empty_golden(self):
        p=ServerList(0,())
        self.assertEqual(encode_server_list(p),bytes.fromhex('06000000'))
        self.assertEqual(decode_server_list(bytes.fromhex('06000000')),p)

    def test_record_layout(self):
        e=ServerEntry(7,bytes((127,0,0,1)),12345,25,100,3)
        p=ServerList(255,(e,),b'probe')
        golden=bytes.fromhex('0601ff077f0000013930190064000370726f626500')
        self.assertEqual(encode_server_list(p),golden)
        self.assertEqual(decode_server_list(golden),p)
        for entries in ((e,e),(e,)*255):
            p=ServerList(0,entries,b'x'*255)
            self.assertEqual(decode_server_list(encode_server_list(p)),p)

    def test_truncation_and_trailing(self):
        good=encode_server_list(ServerList(0,(ServerEntry(1,b'1234',0,0,0,0),),b'abc'))
        for bad in [good[:n] for n in range(len(good))]+[good+b'\0',b'\x07'+good[1:],bytes.fromhex('060100')+b'0'*10]:
            with self.assertRaises(PacketError):decode_server_list(bad)

    def test_invalid_fields(self):
        good=ServerEntry(0,b'1234',0,0,0,0)
        bad=[ServerList(256,()),ServerList(0,(good,)*256),ServerList(0,(),b'a\0'),ServerList(0,(),b'a'*256)]
        bad += [ServerList(0,(e,)) for e in (ServerEntry(-1,b'1234',0,0,0,0),ServerEntry(0,b'123',0,0,0,0),ServerEntry(0,b'1234',65536,0,0,0))]
        for p in bad:
            with self.assertRaises(PacketError):encode_server_list(p)
        with self.assertRaises(PacketError):decode_server_list(b'\x06\0\0'+b'x'*256+b'\0')

    def test_request_live_golden(self):
        golden=bytes.fromhex('050026030000313031323700')
        p=ServerListRequest(0,0x326,b'10127')
        self.assertEqual(decode_server_list_request(golden),p)
        self.assertEqual(encode_server_list_request(p),golden)
        for bad in [golden[:n] for n in range(len(golden))]+[golden+b'\0',b'\x06'+golden[1:]]:
            with self.assertRaises(PacketError):decode_server_list_request(bad)
