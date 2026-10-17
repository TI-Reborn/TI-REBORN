"""The checked native map extension is presentation-only and SHA guarded."""
import json
from pathlib import Path
import tempfile
import unittest

from deploy import client_global_map as patcher
from tools.verify_global_map_native import verify
from tools.verify_global_map_filter import verify as verify_filter


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'reports/global-map-integration-20261010/baseline/client/silver.dll'


class GlobalMapClientTests(unittest.TestCase):
    def test_resource_contract_is_complete_and_unique(self):
        rows = patcher.resources()
        self.assertEqual([r['id'] for r in rows], list(range(23)))
        self.assertEqual(len(set(r['path'].rsplit('\\', 1)[-1] for r in rows)), 23)
        self.assertTrue(all(r['path'].startswith('pda\\global-map-v2\\') for r in rows))
        self.assertTrue(all(r['path'].rsplit('\\', 1)[-1].startswith('gm-v2-') for r in rows))
        self.assertEqual(rows[0]['path'], 'pda\\global-map-v2\\gm-v2-terrain.png')

    def test_guard_rejects_unreviewed_binary(self):
        with self.assertRaises(ValueError): patcher.patch(b'unreviewed client')
        if SOURCE.exists():
            with self.assertRaises(ValueError): patcher.patch(SOURCE.read_bytes(), expected_sha='0' * 64)

    @unittest.skipUnless(SOURCE.exists(), 'Requires the pinned hosted native baseline')
    def test_x86_abi_projection_picking_and_world_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            _, report = verify(SOURCE.read_bytes(), Path(directory) / 'review.json')
        self.assertTrue(report['passed'])
        self.assertTrue(report['all_undeclared_source_bytes_unchanged'])
        self.assertEqual(len(report['cases']), 10)
        self.assertTrue(all(c['town_geometry_unchanged'] and c['avatar_unchanged']
                            and c['native_hover_throttle_preserved']
                            and c['partial_load_uses_original_render_and_click'] for c in report['cases']))
        self.assertEqual(sum(len(c['enabled_town_center_clicks']) for c in report['cases']), 210)

    @unittest.skipUnless(SOURCE.exists(), 'Requires the pinned hosted native baseline')
    def test_x86_mips_iat_exception_and_sampler_scopes(self):
        report = verify_filter(patcher.patch(SOURCE.read_bytes()))
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['cases']), 2)
        self.assertTrue(all(c['object_mip_chains'] == 22 and c['terrain_arguments_unchanged']
                            and c['iat_pointer_and_protection_restored']
                            and c['seh_continue_search_cleanup']
                            and c['foreign_thread_arguments_unchanged'] for c in report['cases']))


if __name__ == '__main__': unittest.main()
