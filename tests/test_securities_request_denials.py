"""Native settings clicks must receive an intentional player-facing denial."""
import unittest

from tio.protocol.securities import decode_request


class SecuritiesRequestDenialTests(unittest.TestCase):
    def test_bond_settings_cannot_change_shared_bank_configuration(self):
        with self.assertRaisesRegex(ValueError, 'Настройки векселей задаются сервером'):
            decode_request(b'\xc1\x04' + bytes(40))

    def test_normal_bond_and_stock_queries_remain_available(self):
        self.assertEqual(decode_request(b'\xc1\x01').action.value, 1)
        self.assertEqual(decode_request(b'\xc1\x05').action.value, 5)
