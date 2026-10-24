"""SC catalogues use eligible world locations, not the old city-only list."""
from contextlib import closing
import sqlite3
import struct
import unittest

import test_credits_only as fixture
import test_city_inventory_wait as network_fixture
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.city_catalogs import decode_item_shop
from tio.protocol.shop_purchase import ShopPurchase


class SCShopLocationTests(unittest.TestCase):
    setUp = fixture.CreditsOnlyTests.setUp

    def locate(self, town: int) -> None:
        with closing(sqlite3.connect(self.path)) as database, database:
            database.execute('UPDATE character_locations SET town_id=? WHERE account=?',
                             (town, 'alice'))

    def test_catalogue_opens_in_every_city_mine_and_base(self):
        for town in (2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22):
            with self.subTest(town=town):
                self.locate(town)
                reply, = self.sc.handle('alice', fixture.sc(4))
                self.assertEqual(reply[:2], b'\xb4\x05')
                self.assertGreater(struct.unpack_from('<I', reply, 2)[0], 0)

    def test_catalogues_and_empty_cart_do_not_write_state(self):
        self.locate(13)
        with closing(sqlite3.connect(self.path)) as database:
            before = tuple(database.iterdump())
        self.sc.handle('alice', fixture.sc(4))
        self.sc.handle('alice', fixture.sc(7))
        with closing(sqlite3.connect(self.path)) as database:
            self.assertEqual(tuple(database.iterdump()), before)

    def test_ordinary_shop_opens_in_the_same_locations(self):
        for town in (2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22):
            with self.subTest(town=town):
                self.locate(town)
                category, offers = decode_item_shop(self.shop.catalog('alice', 0))
                self.assertEqual(category, 0)
                self.assertTrue(offers)
                self.assertTrue(all(int(self.shop.completion.values[o.item_id].get(
                    'level_required', '1')) <= self.shop.completion.towns[town]
                                    for o in offers))

    def test_mine_and_training_base_keep_their_level_bands(self):
        for town, maximum in ((3, 3), (13, 6), (14, 10), (15, 15), (16, 20),
                              (19, 6), (20, 10), (21, 15), (22, 20)):
            self.locate(town)
            self.assertEqual(self.shop.completion.towns[town], maximum)
            with closing(sqlite3.connect(self.path)) as database:
                database.execute('BEGIN')
                offers = self.sc._visible(database, 'alice').values()
                self.assertTrue(all(int(self.sc.completion.values[o.item_id].get(
                    'level_required', '1')) <= maximum for o in offers))

    def test_ordinary_purchase_in_base_uses_its_native_offer_and_credits(self):
        self.locate(19)
        _, offers = decode_item_shop(self.shop.catalog('alice', 0))
        offer = next(o for o in offers if o.item_id == 301)
        result = self.shop.purchase('alice', ShopPurchase(1, 0, offer.unknown_u32_01, 1),
                                    identity='base-order')
        self.assertEqual(result.charged_credits, offer.unknown_u32_03)
        self.assertEqual(result.assets.gold, 0)

    def test_mine_purchase_charges_credits_once_and_keeps_other_account(self):
        self.locate(13)
        offer = next(o for o in self.sc.offers.values()
                     if o.item_id == 248 and o.enhancement == 0)
        request = fixture.sc(6, offer.lot_id, 1, 1)
        replies = self.sc.handle('alice', request, identity='mine-order')
        self.assertEqual(decode_asset_count(replies[1]).credits, 100000-offer.credits)
        self.sc.handle('alice', request, identity='mine-order')
        with closing(sqlite3.connect(self.path)) as database:
            self.assertEqual(database.execute('SELECT credits FROM wallets WHERE account=?',
                                             ('alice',)).fetchone(), (100000-offer.credits,))
            self.assertEqual(database.execute('SELECT credits FROM wallets WHERE account=?',
                                             ('bob',)).fetchone(), (100000,))

    def test_travel_with_a_stale_city_row_rejects_the_shop(self):
        with closing(sqlite3.connect(self.path)) as database, database:
            database.execute('CREATE TABLE map_journeys(account TEXT PRIMARY KEY)')
            database.execute('INSERT INTO map_journeys VALUES (?)', ('alice',))
        with self.assertRaises(ValueError):
            self.sc.handle('alice', fixture.sc(4))
        with self.assertRaises(ValueError):
            self.shop.catalog('alice', 0)

    def test_battle_lease_blocks_sc_mutations(self):
        with closing(sqlite3.connect(self.path)) as database, database:
            database.execute('CREATE TABLE battle_checkpoint_members(account TEXT)')
            database.execute('INSERT INTO battle_checkpoint_members VALUES (?)', ('alice',))
        with self.assertRaises(ValueError):
            self.sc.handle('alice', fixture.sc(9, next(iter(self.sc.offers))))

    def test_prison_shooting_range_world_and_unknown_stay_rejected(self):
        for town in (-1, 0, 10, 17, 65535):
            self.locate(town)
            with self.subTest(town=town), self.assertRaises(ValueError):
                self.sc.handle('alice', fixture.sc(4))


class ShopLocationTCPTests(unittest.TestCase):
    setUp = network_fixture.CityInventoryWaitTCPTests.setUp
    collect = network_fixture.CityInventoryWaitTCPTests.collect

    def test_two_accounts_open_both_shops_in_mine_and_reservation(self):
        for peer in self.peers.values():
            peer.send(b'\x73\x00')
            rows = self.collect(peer)
            normal = next(packet for packet in rows if packet[:1] == b'\x74')
            self.assertTrue(decode_item_shop(normal)[1])
            peer.send(fixture.sc(4))
            rows = self.collect(peer)
            sc = next(packet for packet in rows if packet[:2] == b'\xb4\x05')
            self.assertGreater(struct.unpack_from('<I', sc, 2)[0], 0)
            self.assertFalse(any(packet[:1] == b'\xf0' for packet in rows))


if __name__ == '__main__':
    unittest.main()
