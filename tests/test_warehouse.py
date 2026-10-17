import unittest
from tio.protocol.binary import PacketError
from tio.protocol.warehouse import WarehouseItem, encode_warehouse_list, decode_warehouse_list


class WarehouseProtocolTests(unittest.TestCase):
    def test_native_wire_example(self):
        item=WarehouseItem(1001,301,1,280,300,300)
        packet=encode_warehouse_list(0,1,0,(item,))
        self.assertEqual(packet.hex(),'6a000000000100000001000000e90300002d0100000100000018012c012c010000000000000000')
        self.assertEqual(decode_warehouse_list(packet),(0,1,0,(item,)))

    def test_empty_and_multiple_segments(self):
        items=(WarehouseItem(1,301,1,300,300,300),WarehouseItem(2,326,2,20,30,40,1,2,True))
        for records in ((),items):
            self.assertEqual(decode_warehouse_list(encode_warehouse_list(1,2,1,records)),(1,2,1,records))

    def test_invalid_payloads(self):
        packet=encode_warehouse_list(0,1,0,(WarehouseItem(1,301,1,300,300,300),))
        for n in range(len(packet)):
            with self.assertRaises(PacketError):decode_warehouse_list(packet[:n])
        for invalid in (packet+b'\0',b'\x69'+packet[1:],packet[:-1]+b'\x01'):
            with self.assertRaises(PacketError):decode_warehouse_list(invalid)
        invalid=bytearray(packet);invalid[33]=2
        with self.assertRaises(PacketError):decode_warehouse_list(invalid)
