"""Native skin literals respect both managed lifetime and TI's font ABI."""
import struct
import unittest
from deploy.client_barracks_skin import caption_literal, native_colour


class BarracksSkinTests(unittest.TestCase):
    def test_immutable_caption_has_byte_length_and_negative_reference_count(self):
        raw = caption_literal('ЭКИПИРОВКА')
        self.assertEqual(struct.unpack('<i', raw[4:8])[0], -1)
        self.assertEqual(struct.unpack('<I', raw[8:12])[0], len('ЭКИПИРОВКА'.encode('utf-16le')))
        self.assertEqual(raw[12:-2].decode('utf-16le'), 'ЭКИПИРОВКА')

    def test_native_colour_keeps_alpha_and_swaps_red_with_blue(self):
        self.assertEqual(native_colour(0xff1a1f24), 0xff241f1a)
        self.assertEqual(native_colour(0x80e8891f), 0x801f89e8)
