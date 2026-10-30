"""Geometry and parking points of straight global-map travel."""
import unittest
from tio.roads import path_length, point_along
from tio.locations import TOWNS, center, town_at


class PathTests(unittest.TestCase):
    path = ((0, 0), (3, 4), (3, 10))

    def test_length_and_points_along_the_path(self):
        self.assertEqual(path_length(self.path), 11)
        self.assertEqual(point_along(self.path, 0), (0, 0))
        self.assertEqual(point_along(self.path, 2.5), (1.5, 2))
        self.assertEqual(point_along(self.path, 8), (3, 7))
        self.assertEqual(point_along(self.path, 99), (3, 10))

class ParkingTests(unittest.TestCase):
    def test_every_public_location_parks_inside_its_clickable_bounds(self):
        for town in TOWNS:
            with self.subTest(town=town):
                self.assertEqual(town_at(*center(town)),town)


if __name__ == '__main__':
    unittest.main()
