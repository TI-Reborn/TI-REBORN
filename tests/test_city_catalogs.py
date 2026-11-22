import dataclasses
import json
import unittest
from pathlib import Path
from xml.etree import ElementTree
from tio.city_catalogs import CityCatalogs
from tio.shop_completion import _shop_level_limits
from tio.protocol.binary import PacketError
from tio.protocol.city_services import city_service_reply
from tio.protocol.city_catalogs import *


class CityCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalogs = CityCatalogs(Path(__file__).resolve().parents[1]/'config/city_catalogs.json')

    def test_requests_and_repeatable_catalogs(self):
        packet = city_service_reply(b'\x73\0', self.catalogs)
        category, items = decode_item_shop(packet)
        self.assertEqual(category, 0)
        ids=[item.item_id for item in items]
        self.assertEqual(ids[:2], [301, 3])
        self.assertIn(326, ids)  # Former Premium goods are in the credit catalog.
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue({3,9,210,211,212,302,304,312}.issubset(ids))
        self.assertFalse({0,1,2,300,65500}.intersection(ids))
        self.assertEqual(city_service_reply(b'\x73\0', self.catalogs), packet)
        self.assertEqual(decode_item_shop(city_service_reply(b'\x73\xff', self.catalogs)), (255, ()))
        self.assertEqual(len(decode_pet_shop(city_service_reply(b'\x61', self.catalogs))), 5)
        self.assertEqual(decode_service_shop(city_service_reply(b'\xb1\x02', self.catalogs)), ())
        self.assertIsNone(city_service_reply(b'\x69\0', self.catalogs))  # warehouse, not shop
        # No fabricated transaction results for hiring or purchases.
        for request in (b'\x63\1\0\0\0', b'\xb1\x04', b'\x50\3'):
            self.assertIsNone(city_service_reply(request, self.catalogs))

    def test_malformed_requests(self):
        for request in (b'\x61\0', b'\x73', b'\x73\0\0'):
            with self.assertRaises(PacketError):
                city_service_reply(request, self.catalogs)

    def test_shop_menu_matches_server_availability_in_enabled_locations(self):
        root = Path(__file__).resolve().parents[1]
        zones = root / 'evidence/zones_diagnostic.xml'
        policy = json.loads((root / 'config/shop_completion.json').read_text(encoding='utf-8'))
        available = _shop_level_limits({int(k): v for k, v in policy['town_max_level'].items()})
        for town in ElementTree.parse(zones).getroot():
            fields = {v.get('key'): v.get('val') for v in town}
            if fields['enabled'] != '1':
                continue
            identity = int(town.get('id'))
            with self.subTest(town=identity):
                self.assertEqual(fields.get('shop', 'true') == 'true', identity in available)

    def test_roundtrips_unknown_bits_and_optional_branches(self):
        base = self.catalogs.candidates[0]
        for optional in (None, bytes(range(6))):
            candidate = dataclasses.replace(base, name='Наёмник'.encode('cp1251'),
                optional_bytes=optional, stat_float_bits=(0x80000000, 0x7fc12345)*8)
            self.assertEqual(decode_pet_shop(encode_pet_shop((candidate,))), (candidate,))
        offers = (ServiceOffer(4, 2, (ServiceOption(1, 2**64-1, 2**32-1), ServiceOption(3, 0, 0))),)
        self.assertEqual(decode_service_shop(encode_service_shop(offers)), offers)

    def test_truncation_and_trailing_bytes(self):
        for packet, decoder in ((self.catalogs.pet_shop(), decode_pet_shop),
                                (self.catalogs.item_shop(0), decode_item_shop),
                                (encode_service_shop((ServiceOffer(1, 1, (ServiceOption(1, 1, 1),)),)), decode_service_shop)):
            for length in range(len(packet)):
                with self.assertRaises(PacketError):
                    decoder(packet[:length])
            with self.assertRaises(PacketError):
                decoder(packet + b'\0')

    def test_invalid_candidate_and_counts(self):
        base = self.catalogs.candidates[0]
        for changes in ({'name': b'bad\0name'}, {'name': b'x'*256},
                        {'optional_bytes': b'123'}, {'stat_float_bits': (0,)*15}):
            with self.assertRaises(PacketError):
                encode_pet_shop((dataclasses.replace(base, **changes),))
        with self.assertRaises(PacketError):
            encode_item_shop(256, ())
        with self.assertRaises(PacketError):
            encode_service_shop((ServiceOffer(1, 1, ()),))
