"""Client publications keep the launcher's native adapters bound."""
from contextlib import redirect_stdout
import hashlib
import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pefile

from tools import build_launcher_silver_regions as regions

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT/'reports/skill-tooltip-scale-20261114/candidate-silver.dll'
LAUNCHER_ASSET = ROOT/'work/launcher-0149-20261118/launcher/Assets/native-silver-regions.json'
F7_READER = 0x8798a7  # recon fog hook inside the baked F7 block


def changed(raw: bytes, rva: int) -> bytes:
    with pefile.PE(data=raw, fast_load=True) as pe:
        offset = pe.get_offset_from_rva(rva)
    result = bytearray(raw); result[offset] ^= 0x5a
    return bytes(result)


@unittest.skipUnless(PUBLISHED.exists(), 'published Silver 2026.11.14.2 required')
class SilverRegionGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = PUBLISHED.read_bytes()

    def test_published_client_keeps_every_adapter_bound(self):
        self.assertEqual(regions.mismatches(self.raw), {})
        regions.require_compatible(self.raw)

    def test_unrelated_code_change_is_accepted(self):
        regions.require_compatible(changed(self.raw, 0x1000))

    def test_changed_adapter_dependency_is_refused_with_its_name(self):
        with self.assertRaisesRegex(ValueError, r'recon: 0x879000, 0x8798a7; throwables: 0x879000; flame: 0x879000'):
            regions.require_compatible(changed(self.raw, F7_READER))

    def test_cli_rejects_a_region_missing_from_candidate_raw_data(self):
        with pefile.PE(data=self.raw, fast_load=True) as pe:
            section = pe.get_section_by_rva(F7_READER)
            candidate = bytearray(self.raw)
            struct.pack_into('<I', candidate, section.get_field_absolute_offset('SizeOfRawData'),
                             F7_READER - section.VirtualAddress)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root/'candidate.dll'
            image.write_bytes(candidate)
            output = io.StringIO()
            with patch.object(regions, 'adapter_regions', return_value={'recon': [(F7_READER, 1)]}), \
                    patch.object(sys, 'argv', ['guard', str(PUBLISHED), folder, str(root/'plan.json'),
                                              '--check', str(image)]), redirect_stdout(output):
                self.assertEqual(regions.main(), 1)
            self.assertEqual(json.loads(output.getvalue().splitlines()[-1])['adapters'],
                             {'recon': [hex(F7_READER)]})

    def test_publisher_refuses_before_any_hosting_operation(self):
        from tools import publish_player_feedback_20261104 as publisher
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            (out/'source-silver.dll').write_bytes(self.raw)
            (out/'manifest-before.json').write_text(json.dumps({'version': 'x', 'files': [
                {'path': 'silver.dll', 'sha256': hashlib.sha256(self.raw).hexdigest(), 'size': len(self.raw)}]}))
            with patch.object(publisher, 'OUT', out), \
                    patch.object(publisher, 'SOURCE_SHA', hashlib.sha256(self.raw).hexdigest()), \
                    patch.object(publisher, 'patch', lambda source: changed(source, F7_READER)), \
                    patch.object(publisher.subprocess, 'run', side_effect=AssertionError('hosting touched')), \
                    patch.object(publisher.urllib.request, 'urlopen', side_effect=AssertionError('hosting touched')), \
                    patch.object(sys, 'argv', ['publish', 'inspect']):
                with self.assertRaisesRegex(ValueError, 'launcher adapters'):
                    publisher.main()
            self.assertFalse((out/'candidate-silver.dll').exists())

    @unittest.skipUnless(LAUNCHER_ASSET.exists(), 'launcher 0.1.49 source copy required')
    def test_guard_uses_exactly_the_published_launcher_regions(self):
        self.assertEqual(regions.PLAN.read_bytes(), LAUNCHER_ASSET.read_bytes())


if __name__ == '__main__':
    unittest.main()
