"""Reject altered native/auth modules and personal state in menu graphical QA."""
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.hosted_graphical_qa_bridge import HASHES, MENU_LAYOUT_SHA, SPANS, static_guards, validate_native_binary

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'reports/arena-surroundings-implementation/client-qa/game-a'


@unittest.skipUnless((SOURCE/'ti.exe').is_file(), 'owned native QA resources unavailable')
class MenuQaGuardsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='tio-menu-guard-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root/'.tio-owned-qa').write_bytes(b'')
        (self.root/'base').mkdir()
        for name in HASHES:
            source = SOURCE/name
            # Stable prior release preserved by the actual remote inspection.
            if name == 'silver.dll' and (ROOT/'reports/menu-interface-v1/source/silver.dll').is_file():
                source = ROOT/'reports/menu-interface-v1/source/silver.dll'
            shutil.copyfile(source, self.root/name)
        for name in ('config.cfg', 'autoexec.cfg'):
            (self.root/'base'/name).write_text('orange_addr 185.184.42.88\norange_port 28512\n', encoding='ascii')

    def test_known_previous_release_and_auth_spans_are_preserved(self):
        guards = static_guards(self.root)
        self.assertEqual({row['name'] for row in guards}, {row[0] for row in SPANS})
        self.assertEqual(len(guards), 16)
        self.assertIn('auth_result', {row['name'] for row in guards})
        self.assertIn('login_builder', {row['name'] for row in guards})

    def test_single_foreign_byte_rejected_outside_layout(self):
        path = self.root/'silver.dll'
        binary = bytearray(path.read_bytes())
        binary[-1] ^= 1
        path.write_bytes(binary)
        with self.assertRaisesRegex(ValueError, 'silver.dll'):
            static_guards(self.root)

    def test_exact_authored_layout_variant_preserves_every_auth_span(self):
        from deploy.client_menu_interface import patch
        path = self.root/'silver.dll'
        updated = patch(path.read_bytes())
        self.assertEqual(validate_native_binary('silver.dll', updated), MENU_LAYOUT_SHA)
        path.write_bytes(updated)
        guards = static_guards(self.root)
        self.assertEqual({row['name'] for row in guards}, {row[0] for row in SPANS})

    def test_unknown_change_to_authored_variant_rejected(self):
        from deploy.client_menu_interface import patch
        path = self.root/'silver.dll'
        updated = bytearray(patch(path.read_bytes()))
        updated[-1] ^= 1
        path.write_bytes(updated)
        with self.assertRaisesRegex(ValueError, 'silver.dll'):
            static_guards(self.root)

    def test_transport_module_change_rejected(self):
        path = self.root/'orange.dll'
        binary = bytearray(path.read_bytes())
        binary[-1] ^= 1
        path.write_bytes(binary)
        with self.assertRaisesRegex(ValueError, 'orange.dll'):
            static_guards(self.root)

    def test_wrong_endpoint_rejected(self):
        (self.root/'base/config.cfg').write_text('orange_addr 127.0.0.1\norange_port 28512\n', encoding='ascii')
        with self.assertRaisesRegex(ValueError, 'hosted initial endpoint'):
            static_guards(self.root)

    def test_inherited_login_file_rejected_without_reading(self):
        (self.root/'base/login.ini').write_bytes(b'not a valid login schema')
        with self.assertRaisesRegex(ValueError, 'inherited login.ini'):
            static_guards(self.root)


if __name__ == '__main__':
    unittest.main()
