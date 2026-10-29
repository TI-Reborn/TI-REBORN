"""Global-map routes follow the road network instead of straight lines."""
import math
import unittest

from tio.roads import ROADS, RoadNetwork, leg_index, path_length, point_along


def square():
    # A--B on top, A--C--D--B underneath: the top road is the short one.
    return RoadNetwork({'A': (0, 0), 'B': (10, 0), 'C': (0, 10), 'D': (10, 12)},
                       [('A', 'B', ()), ('A', 'C', ()), ('C', 'D', ()), ('D', 'B', ())])


class PlanTests(unittest.TestCase):
    def test_route_between_nodes_takes_the_shortest_road(self):
        self.assertEqual(square().plan((0, 0), (10, 0)), ((0, 0), (10, 0)))
        self.assertEqual(square().plan((0, 10), (10, 0)), ((0, 10), (0, 0), (10, 0)))

    def test_route_follows_intermediate_road_points(self):
        roads = RoadNetwork({'A': (0, 0), 'B': (10, 0)}, [('A', 'B', ((5, 5),))])
        self.assertEqual(roads.plan((0, 0), (10, 0)), ((0, 0), (5, 5), (10, 0)))
        self.assertEqual(roads.plan((10, 0), (0, 0)), ((10, 0), (5, 5), (0, 0)))

    def test_off_road_points_join_the_nearest_road_point(self):
        path = square().plan((4, -3), (10, 13))
        self.assertEqual(path, ((4, -3), (4, 0), (10, 0), (10, 12), (10, 13)))

    def test_start_in_the_middle_of_a_road_drives_the_shorter_way(self):
        self.assertEqual(square().plan((0, 8), (10, 0)), ((0, 8), (0, 0), (10, 0)))
        self.assertEqual(square().plan((0, 8), (10, 12)), ((0, 8), (0, 10), (10, 12)))

    def test_points_on_the_same_road_stay_on_it(self):
        self.assertEqual(square().plan((2, 0), (7, 0)), ((2, 0), (7, 0)))

    def test_same_point_is_a_single_point_route(self):
        self.assertEqual(square().plan((3, 0), (3, 0)), ((3, 0),))

    def test_disconnected_roads_are_rejected(self):
        roads = RoadNetwork({'A': (0, 0), 'B': (10, 0), 'C': (0, 50), 'D': (10, 50)},
                            [('A', 'B', ()), ('C', 'D', ())])
        with self.assertRaises(ValueError):
            roads.plan((0, 0), (10, 50))

    def test_unknown_nodes_and_degenerate_roads_are_rejected(self):
        with self.assertRaises(ValueError):
            RoadNetwork({'A': (0, 0)}, [('A', 'B', ())])
        with self.assertRaises(ValueError):
            RoadNetwork({'A': (0, 0), 'B': (0, 0)}, [('A', 'B', ())])


class PathTests(unittest.TestCase):
    path = ((0, 0), (3, 4), (3, 10))

    def test_length_and_points_along_the_path(self):
        self.assertEqual(path_length(self.path), 11)
        self.assertEqual(point_along(self.path, 0), (0, 0))
        self.assertEqual(point_along(self.path, 2.5), (1.5, 2))
        self.assertEqual(point_along(self.path, 8), (3, 7))
        self.assertEqual(point_along(self.path, 99), (3, 10))

    def test_leg_index_names_the_segment_being_driven(self):
        self.assertEqual([leg_index(self.path, d) for d in (0, 4.9, 5, 5.1, 11, 20)], [0, 0, 1, 1, 1, 1])
        self.assertEqual(leg_index(((1, 1),), 3), 0)


class WorldRoadsTests(unittest.TestCase):
    def test_every_public_location_has_a_connected_parking_point(self):
        from tio.locations import TOWNS, center, town_at
        for town in TOWNS:
            with self.subTest(town=town):
                anchor = ROADS.anchor(town)
                self.assertIsNotNone(anchor)
                self.assertEqual(center(town), anchor)
                self.assertEqual(town_at(*anchor), town)
        reservation = ROADS.anchor(3)
        for town in TOWNS:
            self.assertGreater(len(ROADS.plan(reservation, ROADS.anchor(town))), 0)

    def test_roads_are_much_shorter_than_a_detour_but_longer_than_a_straight_line(self):
        start, goal = ROADS.anchor(3), ROADS.anchor(8)
        road = path_length(ROADS.plan(start, goal))
        self.assertGreater(road, math.dist(start, goal))
        self.assertLess(road, 2 * math.dist(start, goal))


if __name__ == '__main__':
    unittest.main()
