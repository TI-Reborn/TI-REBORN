"""The full-suite runner separates environment gaps from real failures."""
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch
import io

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import run_full_tests as runner


class RunFullTestsTests(unittest.TestCase):
    def classify(self, identity, error, entries):
        class Failing(unittest.TestCase):
            def id(self):
                return identity

            def runTest(self):
                raise error

        with patch.object(runner, 'known_entries', return_value=entries):
            return unittest.TextTestRunner(
                stream=io.StringIO(), resultclass=runner.ClassifyingResult,
            ).run(Failing())

    def test_missing_repository_runtime_file_is_a_real_error(self):
        error = FileNotFoundError(2, 'missing', str(ROOT/'tio/missing/new.json'))
        result = self.classify('test_runtime.Case.test_data', error, [])
        self.assertEqual(len(result.real), 1)
        self.assertEqual(result.environment, [])

    def test_loader_text_keeps_missing_repository_files_real(self):
        error = ImportError("FileNotFoundError: [Errno 2] No such file or directory: "
                            + repr(str(ROOT/'tio/no_such_file.json')))
        self.assertIsNone(runner.environment_reason(error))

    def test_module_prefix_does_not_suppress_a_new_regression(self):
        entry = dict(test='test_bank_economy.', category='retired-gold',
                     note='Old gold tests do not describe new credit failures.')
        result = self.classify('test_bank_economy.NewCase.test_credit_transfer',
                               RuntimeError('new transaction defect'), [entry])
        self.assertEqual(len(result.real), 1)
        self.assertEqual(result.known, [])

    def test_known_failure_requires_the_exact_test_and_failure_signature(self):
        entry = dict(test='test_legacy.Case.test_gold', kind='failure',
                     error='AssertionError', message='old gold expectation',
                     category='retired-gold', note='A specific retired expectation.')
        result = self.classify(entry['test'], AssertionError(entry['message']), [entry])
        self.assertEqual(len(result.known), 1)
        for identity, error in ((entry['test'], RuntimeError(entry['message'])),
                                (entry['test'], AssertionError('different defect')),
                                (entry['test']+'_new', AssertionError(entry['message']))):
            with self.subTest(identity=identity, error=error):
                result = self.classify(identity, error, [entry])
                self.assertEqual(len(result.real), 1)

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
