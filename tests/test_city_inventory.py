import unittest

from tio.city_inventory import city_inventory_replies
from tio.protocol.item_list import encode_item_list


class CityInventoryTests(unittest.TestCase):
    def test_stale_owner_completes_wait_with_real_primary_inventory(self):
        own = encode_item_list(1, ())
        lookup = {1: own}.get
        for ids in ((0xffffffff,), (22,)):
            self.assertEqual(city_inventory_replies(ids, lookup), (own,))
            self.assertEqual(city_inventory_replies(ids, {}.get), ())
        self.assertEqual(city_inventory_replies((1, 1), lookup), (own,))
        mixed = city_inventory_replies((1, 22), lookup)
        self.assertEqual(mixed, (own,))

    def test_empty_request_is_silent(self):
        self.assertEqual(city_inventory_replies((), lambda owner: None), ())

