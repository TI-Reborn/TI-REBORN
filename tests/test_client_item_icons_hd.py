"""The presentation release changes image references, never gameplay values."""
import unittest
from xml.etree import ElementTree as ET

from deploy.client_item_icons_hd import replace_item_images


class ItemIconCatalogTests(unittest.TestCase):
    def setUp(self):
        self.source = b'<items><item id="3" name="Ammo"><value key="image" val="old.tga"/><value key="weight" val="7"/></item><item id="9" name="Bandage"><value key="heal" val="20"/></item></items>'

    def test_changes_only_the_requested_images(self):
        result = ET.fromstring(replace_item_images(self.source, {3:'tio_ii_3.png',9:'tio_ii_9.png'}))
        self.assertEqual(result[0].find("value[@key='weight']").get('val'),'7')
        self.assertEqual(result[1].find("value[@key='heal']").get('val'),'20')
        self.assertEqual([node.find("value[@key='image']").get('val') for node in result],['tio_ii_3.png','tio_ii_9.png'])

    def test_unknown_item_fails(self):
        with self.assertRaises(ValueError):
            replace_item_images(self.source,{999:'tio_ii_999.png'})

    def test_duplicate_catalog_id_fails(self):
        with self.assertRaises(ValueError):
            replace_item_images(b'<items><item id="3"/><item id="3"/></items>',{3:'tio_ii_3.png'})

    def test_ambiguous_image_fields_fail(self):
        with self.assertRaises(ValueError):
            replace_item_images(b'<items><item id="3"><value key="image" val="a"/><value key="image" val="b"/></item></items>',{3:'tio_ii_3.png'})

    def test_long_or_traversing_image_name_fails(self):
        for name in ('../other.png','x'*32+'.png','wrong.tga'):
            with self.subTest(name=name),self.assertRaises(ValueError):
                replace_item_images(self.source,{3:name})

    def test_repeat_preserves_semantics(self):
        first=replace_item_images(self.source,{3:'tio_ii_3.png'})
        self.assertEqual(replace_item_images(first,{3:'tio_ii_3.png'}),first)


if __name__=='__main__':
    unittest.main()
