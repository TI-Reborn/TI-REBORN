from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.check_handoff import check


class HandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def write(self, name: str, content: str = '') -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def check_root(self) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            status = check(self.root)
        return status, output.getvalue()

    def test_workspace_scans_source_selection_without_reading_private_state(self) -> None:
        self.write('server/runtime.py', 'RUNTIME_ASSETS = ()\n')
        for name in ('pyproject.toml', 'requirements.txt', 'registration/requirements.txt',
                     'assets/item-icons-hd-v1/manifest.json', 'tools/full_tests_known.json',
                     'tests/fixtures/game_tls/generate.ps1'):
            self.write(name)
        self.write('.secrets/production.key', 'private test data')
        status, output = self.check_root()
        self.assertEqual(status, 0)
        self.assertIn('Checked 7 files', output)
        self.assertNotIn('production.key', output)

    def test_export_rejects_extra_local_database(self) -> None:
        self.write('SOURCE_MANIFEST.json', '{}')
        self.write('data/saved.sqlite3')
        status, output = self.check_root()
        self.assertEqual(status, 1)
        self.assertIn('data/saved.sqlite3: forbidden state/file type', output)

    @unittest.skipUnless(shutil.which('git'), 'Git is needed for the tracked-files check')
    def test_git_checks_tracked_files_even_with_an_export_manifest(self) -> None:
        self.write('SOURCE_MANIFEST.json', '{}')
        self.write('data/saved.sqlite3')
        subprocess.run(['git', 'init', '-q'], cwd=self.root, check=True, timeout=15)
        subprocess.run(['git', 'add', '-f', 'SOURCE_MANIFEST.json'], cwd=self.root, check=True,
                       capture_output=True, timeout=15)
        status, output = self.check_root()
        self.assertEqual(status, 0)
        self.assertIn('Checked 1 files', output)
        self.assertNotIn('saved.sqlite3', output)

    def test_reports_secret_location_without_the_secret_value(self) -> None:
        self.write('SOURCE_MANIFEST.json', '{}')
        marker = 'ghp_' + 'z' * 32
        self.write('server/example.py', f'\nvalue = {marker!r}\n')
        status, output = self.check_root()
        self.assertEqual(status, 1)
        self.assertIn('server/example.py:2: github-token', output)
        self.assertNotIn(marker, output)


if __name__ == '__main__':
    unittest.main()
