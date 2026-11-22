"""The full-suite runner separates environment gaps from real failures."""
from pathlib import Path
from contextlib import redirect_stdout
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import io

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import run_full_tests as runner


class RunFullTestsTests(unittest.TestCase):
    def repository_fixture(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name).resolve()
        subprocess.run(['git', 'init', '-q', str(root)], check=True, timeout=10)
        (root/'.gitignore').write_text('/reports/\n/evidence/*.bin\n', encoding='utf-8')
        patcher = patch.object(runner, 'ROOT', root)
        patcher.start()
        self.addCleanup(patcher.stop)
        return root

    def test_json_report_preserves_unicode_with_a_legacy_system_encoding(self):
        class CyrillicFailure(unittest.TestCase):
            def runTest(self):
                self.fail('\u041d\u043e\u0432\u0430\u044f \u043e\u0448\u0438\u0431\u043a\u0430')

        original_open = Path.open

        def legacy_open(path, mode='r', buffering=-1, encoding=None,
                        errors=None, newline=None):
            return original_open(path, mode, buffering, encoding or 'cp1252',
                                 errors, newline)

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'report.json'
            suite = unittest.TestSuite([CyrillicFailure()])
            with patch.object(runner, 'known_entries', return_value=[]), \
                    patch.object(unittest.defaultTestLoader, 'loadTestsFromNames', return_value=suite), \
                    patch.object(Path, 'open', legacy_open), redirect_stdout(io.StringIO()):
                status = runner.main(['test_fixture', '--json', str(output)])
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(status, 1)
            self.assertEqual(report['real'][0]['message'], '\u041d\u043e\u0432\u0430\u044f \u043e\u0448\u0438\u0431\u043a\u0430')

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
        root = self.repository_fixture()
        for error, reason in (
                (FileNotFoundError(2, 'missing', str(root/'evidence/x_native.bin')), 'file:evidence'),
                (FileNotFoundError(2, 'missing', 'C:\\Program Files (x86)\\TIOnline\\base\\x'), 'file:windows-client'),
                (FileNotFoundError(2, 'missing', '/mnt/elsewhere/client.dll'), 'file:outside-repository'),
                (ModuleNotFoundError("No module named 'pefile'", name='pefile'), 'module:pefile'),
                (ImportError("Failed to import\nModuleNotFoundError: No module named 'unicorn'"), 'module:unicorn')):
            with self.subTest(error=error):
                self.assertEqual(runner.environment_reason(error), reason)

    def test_wrapped_environment_cause_is_found(self):
        root = self.repository_fixture()
        try:
            try:raise FileNotFoundError(2, 'missing', str(root/'reports/a/b.json'))
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
