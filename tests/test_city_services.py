import unittest
from tio.protocol.city_services import city_service_reply, PacketError


class CityServicesTests(unittest.TestCase):
    def test_confirmed_ping(self):
        self.assertEqual(city_service_reply(b'\x70'), b'\x9e')
        for packet in (b'', b'\x70\0'):
            with self.assertRaises(PacketError):
                city_service_reply(packet)

    def test_unknown_requests_are_not_fabricated(self):
        for packet in (b'\x50\3', b'\x69\0', b'\xb8\x11', b'\xc5\1'):
            self.assertIsNone(city_service_reply(packet))

    def test_arena_list_without_rooms_and_unimplemented_actions(self):
        self.assertEqual(city_service_reply(bytes.fromhex('ba01')), bytes.fromhex('ba020000'))
        with self.assertRaises(PacketError):
            city_service_reply(bytes.fromhex('ba0100'))
        for packet in ('ba030001', 'ba0401000000', 'ba050100000000', 'ba0700', 'ba0900'):
            self.assertIsNone(city_service_reply(bytes.fromhex(packet)))
