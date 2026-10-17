import unittest
from dataclasses import replace
from tio.protocol.town_info import *


class TownInfoTests(unittest.TestCase):
    def test_visiting_locations_keeps_their_map_markers_enabled(self):
        from tio.locations import TOWNS,town_packets
        for town in TOWNS:
            info=decode_town_info(town_packets(town)[0])
            self.assertEqual(info.town_id,town)
            self.assertEqual(info.final_bool,1)

    def test_live_fixture_and_truncations(self):
        data = encode_town_info(diagnostic_town_info())
        self.assertEqual(data.hex(), 'c82d0300000001030000000000000000000000803f000000000000000000000000000000000000')
        self.assertEqual(decode_town_info(data), diagnostic_town_info())
        for n in range(len(data)):
            with self.assertRaises(PacketError):
                decode_town_info(data[:n])
        for invalid in (data + b'\0', b'\x3c' + data[1:], data[:31] + b'\1' + data[32:], data[:-1] + b'\2'):
            with self.assertRaises(PacketError):
                decode_town_info(invalid)

    def test_unknown_bits_preserved(self):
        p = replace(diagnostic_town_info(), unknown_float_bits=(0x7fc01234, 0x80000000, 0xff800000),
                    unknown_words=(0xffff, 1234, 0), unknown_bytes=(255, 3, 2, 1))
        self.assertEqual(decode_town_info(encode_town_info(p)), p)
