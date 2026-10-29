"""The dashed journey route travels in 1D packets that old clients ignore."""
import math
import struct
import unittest

from tio.locations import Journey, center, movement_packet
from tio.protocol.map_route import (DASH, GAP, HEADER, MAX_DASHES, dash_word, dashes, image_point,
                                    route_words)
from tio.roads import ROADS


def decode(word):
    """The patched client's decoding (deploy/client_global_map_roads.route_draw_code)."""
    x0, y0 = word & 0x7ff, word >> 11 & 0x3ff
    dx = (word << 6 & 0xffffffff) >> 27
    dy = (word << 1 & 0xffffffff) >> 27
    dx, dy = dx - 32 if dx > 15 else dx, dy - 32 if dy > 15 else dy
    return x0, y0, x0 + dx, y0 + dy


class DashTests(unittest.TestCase):
    def test_world_corners_map_to_the_baked_image(self):
        self.assertEqual(image_point((-512, -512)), (0, 0))
        self.assertEqual(image_point((512, 512)), (1819, 865))

    def test_dashes_follow_the_route_in_image_pixels(self):
        path = ROADS.plan(center(3), center(5))
        cut = dashes(path)
        self.assertGreater(len(cut), 20)
        start = tuple(map(round, image_point(path[0])))
        self.assertLessEqual(math.dist(cut[0][:2], start), 1)
        for x0, y0, x1, y1 in cut:
            self.assertLessEqual(math.dist((x0, y0), (x1, y1)), DASH + 1.5)
        gaps = [math.dist(a[2:], b[:2]) for a, b in zip(cut, cut[1:])]
        self.assertLessEqual(max(gaps), GAP + 2)

    def test_every_route_between_locations_fits_the_client_buffer(self):
        towns = [town for town in (2, 3, 4, 5, 6, 7, 8, 9, 11, 13, 16, 18, 20, 22)]
        for a in towns:
            for b in towns:
                if a != b:
                    self.assertLessEqual(len(dashes(ROADS.plan(center(a), center(b)))), MAX_DASHES)

    def test_words_round_trip_through_the_client_decoding(self):
        for dash in ((0, 0, 9, 0), (1818, 864, 1809, 858), (700, 300, 694, 309), (5, 5, 5, -4)):
            word = dash_word(*dash)
            self.assertTrue(0 < word < HEADER)
            self.assertEqual(decode(word), dash)
        with self.assertRaises(ValueError):
            dash_word(10, 10, 30, 10)
        with self.assertRaises(ValueError):
            dash_word(10, 10, 10, 10)

    def test_header_counts_the_dashes(self):
        path = ROADS.plan(center(3), center(8))
        words = route_words(path)
        self.assertEqual(words[0], HEADER | len(words) - 1)
        self.assertEqual([decode(word) for word in words[1:]], dashes(path))


class AnnouncementTests(unittest.TestCase):
    def test_route_burst_repeats_the_same_movement_with_one_word_each(self):
        path = ROADS.plan(center(3), center(8))
        journey = Journey(path, 1000, 1030)
        burst = journey.announce(42, 1003)
        plain = journey.movement(42, 1003)
        self.assertEqual(len(burst), len(route_words(path)))
        for packet, word in zip(burst, route_words(path)):
            # Everything the original reader uses is identical; only the
            # discarded first Z field carries the word.
            self.assertEqual(packet[:13] + packet[17:], plain[:13] + plain[17:])
            self.assertEqual(struct.unpack_from('<I', packet, 13)[0], word)
        self.assertEqual(struct.unpack_from('<i', plain, 25)[0], 8)

    def test_plain_movement_keeps_both_z_fields_for_old_meaning(self):
        packet = movement_packet(7, 1, 2, destination=(3, 4))
        self.assertEqual(struct.unpack('<BIiiIiiiB', packet), (0x1d, 7, 1, 2, 0, 3, 4, 0, 0))


if __name__ == '__main__':
    unittest.main()
