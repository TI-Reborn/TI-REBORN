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

    def test_native_clan_safe_deposit_arrays(self):
        packet = bytes.fromhex('c2020100000002000000000002003300ffff2c010000640000000a000000')
        self.assertEqual(decode_warehouse_transfer(packet),
                         WarehouseTransfer(2, 1, ((0xffff0033, 300), (100, 10)), ()))
        for invalid in (
            packet[:-1], packet + b'\0',
            packet[:6] + b'\x03' + packet[7:],
            packet[:10] + b'\0\0\0\0',
            packet[:10] + b'\x01\0' + packet[14:22] + b'\0\0',
        ):
            with self.subTest(invalid=invalid), self.assertRaises(PacketError):
                decode_warehouse_transfer(invalid)

    def test_native_clan_warehouse_donation_uses_personal_stock(self):
        packet = bytes.fromhex('c20200000000010000000000010051c300000f000000')
        self.assertEqual(decode_warehouse_transfer(packet),
                         WarehouseTransfer(1, None, ((50001, 15),), ()))
        for invalid in (packet[:2] + b'\x01' + packet[3:],
                        packet[:6] + b'\x02' + packet[7:]):
            with self.subTest(invalid=invalid), self.assertRaises(PacketError):
                decode_warehouse_transfer(invalid)
