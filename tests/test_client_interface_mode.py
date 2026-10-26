"""The launcher-selected interface mode keeps one Silver for both layouts."""
from pathlib import Path
import re
import struct
import unittest

from deploy import client_barracks_a2 as a2
from deploy.client_item_icons_hd import replace_item_images, restore_item_images

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = b'''<?xml version='1.0' encoding='utf-8'?>
<items>
  <item id="17" name="Kit">
    <value key="image" val="kit.png" />
    <value key="stackable" val="1" />
  </item>
  <item id="40" name="Rifle">
    <value key="image" val="rifle.png" />
    <value key="weight" val="4" />
  </item>
  <item id="41" name="Knife">
    <value key="image" val="knife.png" />
  </item>
</items>
'''


def _images(raw: bytes) -> dict[str, str]:
    return dict(re.findall(rb'id="(\d+)"[^>]*>\s*<value key="image" val="([^"]+)"', raw))


class NativeModeFlagTests(unittest.TestCase):
    def setUp(self):
        self.region = a2.payload((40, 41))

    def test_mode_flag_defaults_to_new_interface(self):
        offset = a2.MODE - a2.REGION
        self.assertEqual(self.region[offset:offset+4], bytes(4))

    def test_mode_flag_does_not_overlap_layout_state_or_signature(self):
        self.assertGreaterEqual(a2.MODE, a2.STATE+4)
        self.assertLessEqual(a2.MODE+4, a2.REGION+a2.SIGNATURE_OFFSET)

    def test_signature_announces_mode_support(self):
        at = a2.SIGNATURE_OFFSET
        self.assertEqual(self.region[at:at+len(a2.SIGNATURE)], a2.SIGNATURE)
        self.assertTrue(a2.SIGNATURE.endswith(b'-v2'))

    def test_layout_skips_arrangement_when_original_mode_is_selected(self):
        gate = bytes.fromhex('83bb') + struct.pack('<I', a2.MODE) + b'\x00\x0f\x85'
        layout = self.region[:0xc000]
        canvas_check = bytes.fromhex('817e38b0040000')
        self.assertIn(gate, layout)
        self.assertLess(layout.index(gate), layout.index(canvas_check))


class LauncherContractTests(unittest.TestCase):
    """The launcher writes the flag; both sides must agree on its location."""

    def setUp(self):
        self.source = (ROOT / 'launcher/NativeInterfaceMode.cs').read_text(encoding='utf-8')

    def test_launcher_uses_the_native_mode_rva(self):
        match = re.search(r'ModeRva\s*=\s*0x([0-9a-f]+)', self.source)
        self.assertIsNotNone(match)
        self.assertEqual(int(match.group(1), 16), a2.MODE)

    def test_launcher_requires_the_mode_aware_signature(self):
        match = re.search(r'Signature\s*=\s*"([^"]+)"', self.source)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).encode(), a2.SIGNATURE)
        offset = re.search(r'SignatureRva\s*=\s*0x([0-9a-f]+)', self.source)
        self.assertEqual(int(offset.group(1), 16), a2.REGION+a2.SIGNATURE_OFFSET)


class OriginalCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.published = replace_item_images(CATALOGUE, {40: 'tio_ii_40.png'})

    def test_original_catalogue_restores_previous_item_art(self):
        original = restore_item_images(self.published, CATALOGUE, (40,))
        self.assertEqual(_images(original)[b'40'], b'rifle.png')

    def test_original_catalogue_keeps_unrelated_published_values(self):
        original = restore_item_images(self.published, CATALOGUE, (40,))
        self.assertIn(b'<value key="weight" val="4" />', original)
        self.assertIn(b'<value key="stackable" val="1" />', original)
        self.assertEqual(_images(original)[b'41'], b'knife.png')

    def test_image_added_by_the_new_art_is_removed_again(self):
        earlier = CATALOGUE.replace(b'<value key="image" val="knife.png" />', b'')
        published = replace_item_images(earlier, {41: 'tio_ii_41.png'})
        original = restore_item_images(published, earlier, (41,))
        self.assertNotIn(b'tio_ii_41.png', original)
        self.assertNotIn(b'41', _images(original))

    def test_unchanged_selection_returns_identical_bytes(self):
        self.assertEqual(restore_item_images(CATALOGUE, CATALOGUE, (40,)), CATALOGUE)

    def test_missing_reference_item_is_rejected(self):
        with self.assertRaises(ValueError):
            restore_item_images(self.published, CATALOGUE, (99,))

    def test_ambiguous_image_is_rejected(self):
        doubled = CATALOGUE.replace(b'<value key="weight"', b'<value key="image" val="x.png" /><value key="weight"')
        with self.assertRaises(ValueError):
            restore_item_images(doubled, CATALOGUE, (40,))


if __name__ == '__main__':
    unittest.main()
