"""The client item catalogue is parsed once; derived rules stay caller-owned."""
import unittest
from unittest.mock import patch

from tio import item_catalog
from tio.equipment import armor_rules
from tio.protocol.item_list import ItemRecord, encode_item_list
from tio.rental import rental_tax_units


class ItemCatalogCacheTests(unittest.TestCase):
    def test_repeated_rule_builders_do_not_reparse_the_xml(self):
        item_catalog.items_root()
        from tio.armor import ArmorCatalog
        from tio.enhancement import EnhancementRules
        with patch('xml.etree.ElementTree.parse', side_effect=AssertionError('reparsed')):
            for _ in range(3):
                EnhancementRules(); ArmorCatalog(); armor_rules()
                rental_tax_units(encode_item_list(1, ()))

    def test_armor_rules_copies_are_independent(self):
        first = armor_rules(); first[next(iter(first))]['slot'] = 999; first.clear()
        self.assertTrue(armor_rules())
        self.assertNotIn(999, {rule['slot'] for rule in armor_rules().values()})

    def test_rental_tax_counts_full_body_armor_as_three(self):
        def rented(identity, template):
            return ItemRecord(identity, template, bytes(2), 1, 1, 4, (1,)*3, bytes((0, 0, 0, 1)), 3600, bytes(3))
        self.assertEqual(rental_tax_units(encode_item_list(1, (rented(1, 254),))), 3)
        self.assertEqual(rental_tax_units(encode_item_list(1, (rented(1, 301), rented(2, 254)))), 4)


if __name__ == '__main__':
    unittest.main()
