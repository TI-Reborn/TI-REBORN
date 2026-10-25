"""The full-suite runner separates environment gaps from real failures."""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import run_full_tests as runner


class RunFullTestsTests(unittest.TestCase):
    def test_missing_local_inputs_and_optional_modules_are_environment(self):
        for error, reason in (
                (FileNotFoundError(2, 'missing', str(ROOT/'evidence/x_native.json')), 'file:evidence'),
                (FileNotFoundError(2, 'missing', 'C:\\Program Files (x86)\\TIOnline\\base\\x'), 'file:windows-client'),
                (FileNotFoundError(2, 'missing', '/mnt/elsewhere/client.dll'), 'file:outside-repository'),
                (ModuleNotFoundError("No module named 'pefile'", name='pefile'), 'module:pefile'),
                (ImportError("Failed to import\nModuleNotFoundError: No module named 'unicorn'"), 'module:unicorn')):
            with self.subTest(error=error):
                self.assertEqual(runner.environment_reason(error), reason)

    def test_wrapped_environment_cause_is_found(self):
        try:
            try:raise FileNotFoundError(2, 'missing', str(ROOT/'reports/a/b.json'))
            except FileNotFoundError as cause:raise ValueError('wrapped') from cause
        except ValueError as error:
            self.assertEqual(runner.environment_reason(error), 'file:reports')

    def test_real_failures_stay_real(self):
        for error in (AssertionError('x'), ValueError('x'), ModuleNotFoundError("No module named 'tio.nope'", name='tio.nope'),
                      FileNotFoundError(2, 'missing', str(ROOT/'tio/does_not_exist.json'))):
            with self.subTest(error=error):
                self.assertIsNone(runner.environment_reason(error))

    def test_known_list_is_valid_and_explained(self):
        entries = runner.known_entries()
        self.assertTrue(entries)
        for entry in entries:
            self.assertIn(entry['category'], {'retired-gold', 'superseded-client-status', 'local-artifact', 'not-merged'})
            self.assertGreater(len(entry['note']), 20)
        self.assertEqual(len({e['test'] for e in entries}), len(entries))


if __name__ == '__main__':
    unittest.main()
