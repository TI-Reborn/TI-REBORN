"""A fresh client must retain the already deployed stackable-kit behaviour."""
import unittest
from xml.etree import ElementTree as ET

from deploy.client_item_icons_hd import copy_stack_flags


class ClientStackMetadataTests(unittest.TestCase):
    def test_copy_only_explicit_stack_flags_from_authoritative_catalogue(self):
        client = b'<items><item id="30"><value key="weight" val="50"/></item><item id="20"><value key="actionPoints" val="8"/></item></items>'
        server = b'<items><item id="30"><value key="stackable" val="1"/><value key="weight" val="99"/></item><item id="20"><value key="actionPoints" val="10"/></item></items>'
        result = copy_stack_flags(client, server, (30,))
        root = ET.fromstring(result)
        self.assertEqual(root.find("item[@id='30']/value[@key='stackable']").get('val'), '1')
        self.assertEqual(root.find("item[@id='30']/value[@key='weight']").get('val'), '50')
        self.assertEqual(root.find("item[@id='20']/value").get('val'), '8')
        self.assertEqual(copy_stack_flags(result, server, (30,)), result)

    def test_missing_or_ambiguous_authority_fails(self):
        client = b'<items><item id="30"/></items>'
        for server in (client, b'<items><item id="30"><value key="stackable" val="1"/><value key="stackable" val="0"/></item></items>'):
            with self.subTest(server=server), self.assertRaises(ValueError):
                copy_stack_flags(client, server, (30,))
