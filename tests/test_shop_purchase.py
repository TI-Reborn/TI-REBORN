import unittest
from tio.protocol.shop_purchase import *
from tio.protocol.binary import PacketError

class ShopPurchaseTests(unittest.TestCase):
    def test_wire(self):
        request=ShopPurchase(1,0,2,3)
        wire=bytes.fromhex('7501000000000200000003000000')
        self.assertEqual(encode_shop_purchase(request),wire)
        self.assertEqual(decode_shop_purchase(wire),request)
        for end in range(len(wire)):
            with self.assertRaises(PacketError):decode_shop_purchase(wire[:end])
        with self.assertRaises(PacketError):decode_shop_purchase(wire+b'\0')
    def test_bad_width_and_preserve_zero_quantity(self):
        with self.assertRaises(PacketError):encode_shop_purchase(ShopPurchase(1,256,2,1))
        # Wire decoder retains invalid gameplay values for the transaction layer.
        request=ShopPurchase(0,0,0,0)
        self.assertEqual(decode_shop_purchase(encode_shop_purchase(request)),request)
