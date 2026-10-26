"""Each session receives the item art of the interface its launcher chose."""
import json
from pathlib import Path
import socket
import threading
import time
import unittest
import zlib
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET

from server.tls import bridge_preface, read_bridge_preface
from tio.item_presentation import NEW, ORIGINAL, apply_item_images, items_xml, original_images
from tio.protocol.shared_config import decode_shared_config_data, decode_shared_config_set
from tio.protocol.transport import InitialCipher, InitialFrameReader, encode_initial_frame
from tools.loopback_exchange import LoopbackExchange

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = b'''<?xml version='1.0' encoding='utf-8'?>
<items>
  <item id="40" name="Rifle">
    <value key="image" val="tio_ii_40.png" />
    <value key="weight" val="4" />
  </item>
  <item id="41" name="Knife">
    <value key="image" val="tio_ii_41.png" />
  </item>
</items>
'''


def images(raw: bytes) -> dict[int, str | None]:
    root = ET.fromstring(raw)
    return {int(n.get('id')): (n.find("value[@key='image']").get('val')
                               if n.find("value[@key='image']") is not None else None) for n in root}


class ApplyItemImagesTests(unittest.TestCase):
    def test_previous_image_is_restored(self):
        self.assertEqual(images(apply_item_images(CATALOGUE, {40: 'rifle.tga'}))[40], 'rifle.tga')

    def test_none_removes_an_image_the_new_art_added(self):
        self.assertIsNone(images(apply_item_images(CATALOGUE, {41: None}))[41])

    def test_rules_and_other_items_are_unchanged(self):
        result = apply_item_images(CATALOGUE, {40: 'rifle.tga'})
        self.assertIn(b'<value key="weight" val="4" />', result)
        self.assertEqual(images(result)[41], 'tio_ii_41.png')

    def test_unknown_item_is_rejected(self):
        with self.assertRaises(ValueError):
            apply_item_images(CATALOGUE, {99: 'x.png'})

    def test_unsafe_image_name_is_rejected(self):
        for name in ('../x.png', 'a\\b.png', '', 'x' * 40):
            with self.assertRaises(ValueError):
                apply_item_images(CATALOGUE, {40: name})


class PublishedCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.new = items_xml(NEW)
        self.original = items_xml(ORIGINAL)

    def test_new_interface_is_the_server_catalogue(self):
        self.assertEqual(self.new, (ROOT / 'evidence/items_diagnostic.xml').read_bytes())

    def test_original_interface_differs_only_in_selected_images(self):
        selected = original_images()
        before, after = images(self.new), images(self.original)
        self.assertEqual(before.keys(), after.keys())
        for identity in before:
            self.assertEqual(after[identity], selected.get(identity, before[identity]), identity)

    def test_original_interface_keeps_every_rule_value(self):
        def rules(raw):
            return {(n.get('id'), v.get('key'), v.get('val')) for n in ET.fromstring(raw)
                    for v in n.iter('value') if v.get('key') != 'image'}
        self.assertEqual(rules(self.new), rules(self.original))

    def test_published_art_covers_every_restored_item(self):
        selected = original_images()
        self.assertEqual(len(selected), 101)
        published = images(self.new)
        self.assertTrue(all(published[i] == f'tio_ii_{i}.png' for i in selected))

    def test_unknown_interface_is_rejected(self):
        with self.assertRaises(ValueError):
            items_xml('classic')


class BridgeInterfaceFlagTests(unittest.TestCase):
    def read(self, flags):
        a, b = socket.socketpair()
        with a, b:
            raw = bytearray(bridge_preface(31001))
            raw[5] = flags
            a.sendall(raw)
            return read_bridge_preface(b, time.monotonic()+1)

    def test_language_and_interface_are_independent_bits(self):
        for flags, language, interface in ((0, 'russian', NEW), (1, 'english', NEW),
                                           (2, 'russian', ORIGINAL), (3, 'english', ORIGINAL)):
            port = self.read(flags)
            self.assertEqual((port.language, port.interface), (language, interface), flags)

    def test_unknown_flag_bits_are_rejected(self):
        for flags in (4, 0x80):
            with self.assertRaises(ValueError):
                self.read(flags)


class SessionCatalogueDeliveryTests(unittest.TestCase):
    """Two sessions with different launcher choices receive their own art."""

    def deliver(self, interface: str | None) -> bytes:
        with TemporaryDirectory() as directory:
            exchange = LoopbackExchange(Path(directory)/'trace.json')
            if interface is not None:
                exchange.interface = interface
            server, client = socket.socketpair()
            received, errors = [], []

            def peer():
                try:
                    reader = InitialFrameReader(InitialCipher('S2C'))
                    outbound = InitialCipher('C2S')
                    _, packets = exchange.receive_frame(client, reader)
                    self.assertEqual(decode_shared_config_set(packets[0])[0].name_bytes, b'items')
                    client.sendall(encode_initial_frame(b'\xb9\x02items\0', outbound))
                    _, packets = exchange.receive_frame(client, reader)
                    data = decode_shared_config_data(packets[0])
                    received.append(zlib.decompress(data.compressed_bytes))
                    client.sendall(encode_initial_frame(b'\xb9\x04', outbound))
                except BaseException as error:
                    errors.append(error)
                finally:
                    client.close()

            thread = threading.Thread(target=peer)
            thread.start()
            try:
                exchange.deliver_shared_config(server, InitialFrameReader(InitialCipher('C2S')), InitialCipher('S2C'))
            finally:
                server.close()
                exchange.listener.close()
                thread.join(6)
            self.assertFalse(thread.is_alive())
            if errors:
                raise errors[0]
            return received[0]

    def test_each_session_receives_its_chosen_catalogue(self):
        original, modern = self.deliver(ORIGINAL), self.deliver(NEW)
        self.assertEqual(original, items_xml(ORIGINAL))
        self.assertEqual(modern, items_xml(NEW))
        self.assertNotEqual(original, modern)

    def test_session_without_a_choice_keeps_the_new_catalogue(self):
        self.assertEqual(self.deliver(None), items_xml(NEW))


class OriginalImageDataTests(unittest.TestCase):
    def test_data_file_maps_item_ids_to_names_or_null(self):
        raw = json.loads((ROOT / 'config/original_item_images.json').read_text(encoding='utf-8'))
        self.assertTrue(all(key.isdigit() for key in raw['images']))
        self.assertTrue(all(value is None or isinstance(value, str) for value in raw['images'].values()))


if __name__ == '__main__':
    unittest.main()
