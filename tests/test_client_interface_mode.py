"""The launcher-selected interface mode keeps one Silver for both layouts."""
from pathlib import Path
import re
import struct
import unittest

from deploy import client_barracks_a2 as a2
from server.tls import INTERFACE_FLAG, LANGUAGE_FLAG

ROOT = Path(__file__).resolve().parents[1]


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
    """The launcher writes the flag and the preface bits; both sides must agree."""

    def setUp(self):
        self.native = (ROOT / 'launcher/NativeInterfaceMode.cs').read_text(encoding='utf-8')
        self.bridge = (ROOT / 'launcher/LaunchVerification.cs').read_text(encoding='utf-8')

    def test_launcher_uses_the_native_mode_rva(self):
        match = re.search(r'ModeRva\s*=\s*0x([0-9a-f]+)', self.native)
        self.assertIsNotNone(match)
        self.assertEqual(int(match.group(1), 16), a2.MODE)

    def test_launcher_requires_the_mode_aware_signature(self):
        match = re.search(r'Signature\s*=\s*"([^"]+)"', self.native)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).encode(), a2.SIGNATURE)
        offset = re.search(r'SignatureRva\s*=\s*0x([0-9a-f]+)', self.native)
        self.assertEqual(int(offset.group(1), 16), a2.REGION+a2.SIGNATURE_OFFSET)

    def test_launcher_preface_bits_match_the_server(self):
        for name, value in (('LanguageFlag', LANGUAGE_FLAG), ('InterfaceFlag', INTERFACE_FLAG)):
            match = re.search(name + r'\s*=\s*(\d+)', self.bridge)
            self.assertIsNotNone(match, name)
            self.assertEqual(int(match.group(1)), value, name)


if __name__ == '__main__':
    unittest.main()
