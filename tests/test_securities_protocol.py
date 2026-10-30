import struct
import unittest

from tio.protocol import securities as wire
from tio.protocol.binary import PacketError


class SecuritiesProtocolTests(unittest.TestCase):
    def test_parameterless_queries_sent_on_enter_world_and_by_the_window(self):
        for packet, action in ((b'\xc1\x01', wire.Action.BOND_CONFIG), (b'\xc1\x05', wire.Action.PYRAMID_CONFIG),
                               (b'\xc1\x0c', wire.Action.BOND_HISTORY), (b'\xc1\x0a', wire.Action.PYRAMID_HISTORY)):
            self.assertEqual(wire.decode_request(packet), wire.Request(action))

    def test_trade_requests_keep_reference_and_count(self):
        self.assertEqual(wire.decode_request(b'\xc1\x09' + struct.pack('<I', 4)),
                         wire.Request(wire.Action.BOND_PURCHASE, count=4))
        self.assertEqual(wire.decode_request(b'\xc1\x03' + struct.pack('<II', 0, 2)),
                         wire.Request(wire.Action.BOND_REDEMPTION, count=2, reference=0))
        self.assertEqual(wire.decode_request(b'\xc1\x07' + struct.pack('<II', 104, 3)),
                         wire.Request(wire.Action.STOCK_PURCHASE, count=3, reference=104))
        self.assertEqual(wire.decode_request(b'\xc1\x08' + struct.pack('<II', 104, 1)),
                         wire.Request(wire.Action.STOCK_SALE, count=1, reference=104))

    def test_truncated_trailing_and_administrative_requests_are_rejected(self):
        for packet in (b'\xc1\x09\x01', b'\xc1\x01\x00', b'\xc1\x07' + bytes(9), b'\xc1\x04', b'\xc1\x10' + bytes(8),
                       b'\xc1', b'\xb7\x01'):
            with self.assertRaises(PacketError):
                wire.decode_request(packet)

    def test_bond_config_matches_reader_6ff9ec(self):
        config = wire.BondConfig(1000, 2000, 3000, 4000, redemption_credits=155, price_credits=150)
        self.assertEqual(wire.encode_bond_config(config),
                         b'\xc1\x02\x01' + struct.pack('<qqqqII', 1000, 2000, 3000, 4000, 155, 150))
        self.assertEqual(wire.encode_bond_config(None), b'\xc1\x02\x00')

    def test_pyramid_config_matches_reader_6ffcd8(self):
        config = wire.PyramidConfig(pyramid_id=104, selling_price=104, buying_price=104)
        self.assertEqual(wire.encode_pyramid_config(config),
                         b'\xc1\x06\x01' + struct.pack('<6I', 0, 104, 104, 0, 104, 0))
        self.assertEqual(wire.encode_pyramid_config(None), b'\xc1\x06\x00')

    def test_histories_match_readers_6ffdb0_and_6ffe40(self):
        self.assertEqual(wire.encode_bond_history(((10, 150), (20, 155))),
                         b'\xc1\x0d' + struct.pack('<hqIqI', 2, 10, 150, 20, 155))
        self.assertEqual(wire.encode_pyramid_history((wire.PyramidPoint(30, (1, 2, 3, 4)),)),
                         b'\xc1\x0b' + struct.pack('<hq4i', 1, 30, 1, 2, 3, 4))
        self.assertEqual(wire.encode_bond_history(()), b'\xc1\x0d\x00\x00')

    def test_values_outside_the_native_field_types_are_rejected(self):
        with self.assertRaises(PacketError):
            wire.encode_pyramid_history((wire.PyramidPoint(1, (2**31, 0, 0, 0)),))
        with self.assertRaises(PacketError):
            wire.encode_bond_history(((1, 2),) * 0x8000)
        with self.assertRaises(PacketError):
            wire.encode_bond_config(wire.BondConfig(2**63, 0, 0, 0, redemption_credits=1, price_credits=1))


if __name__ == '__main__':
    unittest.main()
