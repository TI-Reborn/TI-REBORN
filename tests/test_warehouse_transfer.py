import unittest
from tio.protocol.binary import PacketError
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer,decode_warehouse_transfer


class WarehouseTransferTests(unittest.TestCase):
    def test_native_arrays_remain_distinct(self):
        request=WarehouseTransfer(0,17,((1001,2),(1002,1)),((2002,4),))
        packet=encode_warehouse_transfer(request)
        self.assertEqual(packet.hex(),'6b00110000000200e903000002000000ea030000010000000100d207000004000000')
        self.assertEqual(decode_warehouse_transfer(packet),request)
        for first,second in (((),()),(((1,2),),()),((),((1,2),))):
            r=WarehouseTransfer(3,99,first,second)
            self.assertEqual(decode_warehouse_transfer(encode_warehouse_transfer(r)),r)

    def test_malformed_requests(self):
        packet=encode_warehouse_transfer(WarehouseTransfer(0,17,((1001,1),),((2002,3),)))
        for n in range(len(packet)):
            with self.assertRaises(PacketError):decode_warehouse_transfer(packet[:n])
        for invalid in (packet+b'\0',b'\x6a'+packet[1:],packet[:6]+b'\xff\xff'+packet[8:]):
            with self.assertRaises(PacketError):decode_warehouse_transfer(invalid)
