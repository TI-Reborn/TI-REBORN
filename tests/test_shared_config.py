import unittest
from tio.protocol.binary import PacketError
from tio.protocol.shared_config import *


class SharedConfigTests(unittest.TestCase):
    def test_data_layout(self):
        value = SharedConfigData(b'items', 0x12345678, b'abc')
        packet = bytes.fromhex('b9036974656d73007856341203000000616263')
        self.assertEqual(encode_shared_config_data(value), packet)
        self.assertEqual(decode_shared_config_data(packet), value)
        for size in range(len(packet)):
            with self.assertRaises(PacketError): decode_shared_config_data(packet[:size])
        with self.assertRaises(PacketError): decode_shared_config_data(packet+b'\0')

    def test_data_buffer_limit(self):
        value = SharedConfigData(b'items', 1, b'x'*50000)
        self.assertEqual(decode_shared_config_data(encode_shared_config_data(value)), value)
        with self.assertRaises(PacketError): encode_shared_config_data(SharedConfigData(b'items', 1, b'x'*50001))
        with self.assertRaises(PacketError): decode_shared_config_data(b'\xb9\3items\0'+(1).to_bytes(4,'little')+(50001).to_bytes(4,'little'))

    def test_known_layout(self):
        entries = (SharedConfigEntry(b'items', 0x12345678),)
        packet = bytes.fromhex('b901016974656d730078563412')
        self.assertEqual(encode_shared_config_set(entries), packet)
        self.assertEqual(decode_shared_config_set(packet), entries)
        self.assertEqual(decode_shared_config_set(b'\xb9\1\0'), ())

    def test_truncations_and_tail(self):
        packet = encode_shared_config_set((SharedConfigEntry(b'items', 7),))
        for size in range(len(packet)):
            with self.assertRaises(PacketError): decode_shared_config_set(packet[:size])
        with self.assertRaises(PacketError): decode_shared_config_set(packet+b'\0')

    def test_limits(self):
        for name in (b'a\0b', b'a'*256):
            with self.assertRaises(PacketError): encode_shared_config_set((SharedConfigEntry(name, 0),))
        with self.assertRaises(PacketError): encode_shared_config_set([SharedConfigEntry(b'', 0)]*256)
        with self.assertRaises(PacketError): encode_shared_config_set((SharedConfigEntry(b'items', -1),))
