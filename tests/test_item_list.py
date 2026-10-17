import unittest
from tio.protocol.item_list import *
from tio.protocol.binary import PacketError

class ItemListTests(unittest.TestCase):
    def test_captured_request(self):
        self.assertEqual(decode_item_list_request(bytes.fromhex('2f010001000000')),(1,))
        self.assertEqual(decode_item_list_request(bytes.fromhex('2f02000100000002000000')),(1,2))
        for packet in (bytes.fromhex('c82f010001000000'),b'\x2f\1',bytes.fromhex('2f020001000000')):
            with self.assertRaises(PacketError):decode_item_list_request(packet)
    def test_empty_result_strict(self):
        packet=encode_empty_item_list(1)
        self.assertEqual(packet,bytes.fromhex('30010000000000000000'))
        self.assertEqual(decode_empty_item_list(packet),(1,0))
        for bad in (packet[:-1],packet+b'\0',packet[:6]+b'\1\0\0\0'):
            with self.assertRaises(PacketError):decode_empty_item_list(bad)


class NonemptyItemTests(unittest.TestCase):
    def test_records_and_truncation(self):
        from tio.protocol.item_list import ItemRecord,encode_item_list,decode_item_list
        for optional in (None,0,0xffffffff):
            item=ItemRecord(1001,301,b'\1\2',4,5,6,(7,8,9),b'1234',optional,b'abc')
            packet=encode_item_list(1,(item,item))
            self.assertEqual(decode_item_list(packet),(1,(item,item),0))
            for length in range(len(packet)):
                with self.assertRaises(PacketError):decode_item_list(packet[:length])
            with self.assertRaises(PacketError):decode_item_list(packet+b'\0')
