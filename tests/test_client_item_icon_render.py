"""Resource names must stay unique in TI's basename-only texture cache."""
import unittest

from deploy.client_item_icon_render import image_path, payload, validate_ids


class ItemIconRenderTests(unittest.TestCase):
    def test_hd_basename_differs_from_native_inventory_image(self):
        self.assertEqual(image_path(17),'items\\hd\\tio_ih_17_512.png')
        self.assertNotEqual(image_path(17).split('\\')[-1],'tio_ii_17.png')

    def test_duplicate_or_invalid_ids_fail(self):
        for values in ((),(17,17),(0,),(65536,),(True,)):
            with self.subTest(values=values),self.assertRaises(ValueError):
                validate_ids(values)

    def test_catalog_order_is_deterministic(self):
        self.assertEqual(validate_ids((30,17,9)),(9,17,30))

    def test_largest_catalog_does_not_overwrite_backpack_native_entry(self):
        raw = payload(0x8a0000, 0x89ff00, tuple(range(1, 161)))
        self.assertEqual(raw[0x9200:0x9206], bytes.fromhex('5589e583ec30'))
        self.assertEqual(raw[0x9000:0x9010], bytes(16))
        for index in range(160):
            name = image_path(index+1).encode('utf-16le')
            start = 0x5000+index*96+12
            self.assertEqual(raw[start:start+len(name)], name)


if __name__=='__main__':unittest.main()
