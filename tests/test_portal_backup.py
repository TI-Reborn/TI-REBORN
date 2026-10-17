"""Portal backup publication and restore checks without PostgreSQL or network."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / 'web' / 'deploy' / 'portal_backup.py'
SPEC = importlib.util.spec_from_file_location('portal_backup_under_test', MODULE_PATH)
portal_backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(portal_backup)


class FakePostgres:
    """Write a synthetic archive and record only synthetic command arguments."""

    def __init__(self, *, fail=None, payload=b'PGDMP synthetic test archive',
                 rows=b'[{"table":"public.fixture","rows":2}]\n', observe=None):
        self.fail = fail
        self.payload = payload
        self.rows = rows
        self.observe = observe
        self.calls = []
        self.restore_inputs = []

    def __call__(self, args, *, check=True, stdin=None, stdout=None, stderr=None):
        args = [str(value) for value in args]
        if args[:8] != ['/usr/sbin/runuser', '-u', 'postgres', '--', '/usr/bin/env', '-i',
                       'PATH=/usr/lib/postgresql/16/bin:/usr/bin:/bin', 'LANG=C.UTF-8']:
            raise AssertionError('Database commands must run as postgres')
        command = [Path(args[8]).name, *args[9:]]
        for required in ('--host=/var/run/postgresql', '--port=5432', '--username=postgres'):
            if required not in command:
                raise AssertionError('Database commands must target the verified local PostgreSQL socket')
        if command[0] == 'pg_dump':
            stage = 'dump'
        elif command[0] == 'pg_restore':
            stage = 'validate' if '--file=/dev/null' in command else 'restore'
        elif command[0] == 'psql' and any(value.startswith('--command=REVOKE CONNECT') for value in command):
            stage = 'isolate'
        else:
            stage = command[0]
        if not check:
            raise AssertionError('A database command failure must propagate')
        self.calls.append((stage, command))
        if stage in ('validate', 'restore'):
            if stdin is None or not hasattr(stdin, 'read'):
                raise AssertionError('pg_restore must receive the private archive through stdin')
            self.restore_inputs.append((stage, Path(stdin.name), stdin.read()))
        if self.observe:
            self.observe(stage, command)
        if stage == 'dump':
            if stdout is None or not hasattr(stdout, 'write'):
                raise AssertionError('pg_dump needs an open binary output file')
            stdout.write(self.payload)
        if stage == self.fail:
            raise subprocess.CalledProcessError(1, args, stderr=b'private synthetic error detail')
        return subprocess.CompletedProcess(args, 0, stdout=self.rows if stage == 'psql' else None)

    @property
    def stages(self):
        return [stage for stage, _ in self.calls]


class PortalBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'backups'
        self.directory.mkdir()
        self.now = datetime(2026, 10, 7, 3, 30, 12, 345678, tzinfo=timezone.utc)
        self.final = self.directory / self.filename(self.now)

    @staticmethod
    def filename(stamp, tag='website'):
        return tag + '-' + stamp.strftime('%Y%m%dT%H%M%S%fZ') + '.dump'

    def dated(self, days, tag='website'):
        path = self.directory / self.filename(self.now - timedelta(days=days), tag)
        path.write_bytes(b'preserved old test backup')
        return path

    def snapshot(self, runner, **kwargs):
        return portal_backup.snapshot('tionline_web', self.directory, now=self.now,
                                      runner=runner, **kwargs)

    def assert_no_pending(self):
        self.assertFalse(list(self.directory.glob('.pending-*')))

    def test_success_restores_before_publication_and_selective_retention(self):
        expired, recent, boundary = self.dated(15), self.dated(1), self.dated(14)
        before_release = self.dated(30, tag='before-release')
        manual = self.directory / 'manual-recovery.dump'
        legacy = self.directory / 'website-20260901T033000Z-ABCDEFGH.dump'
        invalid_stamp = self.directory / 'website-20261301T033000000000Z.dump'
        for path in (manual, legacy, invalid_stamp):
            path.write_bytes(b'preserved test backup')

        def observe(stage, command):
            self.assertFalse(self.final.exists(), stage)
            self.assertTrue(expired.exists(), stage)
            self.assertEqual(len(list(self.directory.glob('.pending-*'))), 1, stage)

        runner = FakePostgres(observe=observe)
        result = self.snapshot(runner)
        self.assertEqual(result, self.final)
        self.assertEqual(result.read_bytes(), runner.payload)
        self.assertEqual(runner.stages, ['dump', 'validate', 'createdb', 'isolate', 'restore', 'psql', 'dropdb'])
        self.assertFalse(expired.exists())
        for path in (recent, boundary, before_release, manual, legacy, invalid_stamp):
            self.assertTrue(path.exists(), path.name)
        self.assert_no_pending()

        dump, validate, createdb, isolate, restore, row_check, dropdb = [command for _, command in runner.calls]
        self.assertIn('--format=custom', dump)
        self.assertIn('--dbname=tionline_web', dump)
        self.assertIn('--exit-on-error', validate)
        self.assertIn('--file=/dev/null', validate)
        validation_input, restoration_input = runner.restore_inputs
        self.assertTrue(validation_input[1].name.startswith('.pending-'))
        self.assertEqual(validation_input[1], restoration_input[1])
        self.assertEqual(validation_input[2], runner.payload)
        self.assertEqual(restoration_input[2], runner.payload)
        self.assertFalse(any(value.endswith('.dump') for value in validate + restore))
        self.assertIn('--template=template0', createdb)
        scratch = createdb[-1]
        self.assertIn('--command=REVOKE CONNECT ON DATABASE "' + scratch + '" FROM PUBLIC', isolate)
        self.assertRegex(scratch, r'^tiobackupcheck_[0-9a-f]{32}$')
        self.assertIn('--dbname=' + scratch, restore)
        for flag in ('--exit-on-error', '--single-transaction', '--no-owner', '--no-privileges'):
            self.assertIn(flag, restore)
        for flag in ('--no-psqlrc', '--no-align', '--tuples-only', '--set=ON_ERROR_STOP=1',
                     '--dbname=' + scratch):
            self.assertIn(flag, row_check)
        self.assertTrue(any(value.startswith('--command=') for value in row_check))
        self.assertEqual(dropdb[-1], scratch)
        self.assertNotEqual(scratch, 'tionline_web')

    def test_failed_dump_or_full_archive_validation_never_publishes_or_rotates(self):
        for failure, expected_stages in (
                ('dump', ['dump']),
                ('validate', ['dump', 'validate'])):
            with self.subTest(stage=failure):
                old = self.dated(30)
                runner = FakePostgres(fail=failure)
                with self.assertRaises(RuntimeError) as raised:
                    self.snapshot(runner)
                self.assertNotIn('private synthetic error detail', str(raised.exception))
                self.assertNotIn('runuser', str(raised.exception))
                self.assertEqual(runner.stages, expected_stages)
                self.assertEqual(list(self.directory.iterdir()), [old])
                self.assertEqual(old.read_bytes(), b'preserved old test backup')
                self.assert_no_pending()

    def test_failed_scratch_creation_does_not_drop_an_existing_database(self):
        old = self.dated(30)
        runner = FakePostgres(fail='createdb')
        with self.assertRaises(RuntimeError):
            self.snapshot(runner)
        self.assertEqual(runner.stages, ['dump', 'validate', 'createdb'])
        self.assertEqual(list(self.directory.iterdir()), [old])
        self.assert_no_pending()

    def test_failed_restore_drops_its_own_scratch_and_preserves_old_backups(self):
        old = self.dated(30)
        runner = FakePostgres(fail='restore')
        with self.assertRaises(RuntimeError):
            self.snapshot(runner)
        self.assertEqual(runner.stages, ['dump', 'validate', 'createdb', 'isolate', 'restore', 'dropdb'])
        createdb = runner.calls[2][1]
        dropdb = runner.calls[-1][1]
        self.assertEqual(createdb[-1], dropdb[-1])
        self.assertEqual(list(self.directory.iterdir()), [old])
        self.assert_no_pending()

    def test_failed_scratch_cleanup_prevents_publication_and_retention(self):
        old = self.dated(30)
        runner = FakePostgres(fail='dropdb')
        with self.assertRaises(RuntimeError):
            self.snapshot(runner)
        self.assertEqual(runner.stages, ['dump', 'validate', 'createdb', 'isolate', 'restore', 'psql', 'dropdb'])
        self.assertEqual(list(self.directory.iterdir()), [old])
        self.assert_no_pending()

    def test_failed_restored_row_checks_drop_scratch_and_prevent_publication(self):
        old = self.dated(30)
        runner = FakePostgres(fail='psql')
        with self.assertRaises(RuntimeError):
            self.snapshot(runner)
        self.assertEqual(runner.stages, ['dump', 'validate', 'createdb', 'isolate', 'restore', 'psql', 'dropdb'])
        self.assertEqual(list(self.directory.iterdir()), [old])
        self.assert_no_pending()

    def test_empty_dump_is_refused_before_any_restore_command(self):
        old = self.dated(30)
        runner = FakePostgres(payload=b'')
        with self.assertRaises((RuntimeError, ValueError)):
            self.snapshot(runner)
        self.assertEqual(runner.stages, ['dump'])
        self.assertEqual(list(self.directory.iterdir()), [old])
        self.assert_no_pending()

    def test_timestamp_collision_never_overwrites_or_rotates(self):
        old = self.dated(30)
        self.final.write_bytes(b'existing verified test backup')
        runner = FakePostgres()
        with self.assertRaises(FileExistsError):
            self.snapshot(runner)
        self.assertEqual(self.final.read_bytes(), b'existing verified test backup')
        self.assertTrue(old.exists())
        self.assert_no_pending()

    def test_publication_race_never_replaces_a_concurrent_backup(self):
        old = self.dated(30)

        def observe(stage, command):
            if stage == 'dropdb':
                self.final.write_bytes(b'concurrent verified test backup')

        with self.assertRaises(FileExistsError):
            self.snapshot(FakePostgres(observe=observe))
        self.assertEqual(self.final.read_bytes(), b'concurrent verified test backup')
        self.assertTrue(old.exists())
        self.assert_no_pending()

    def test_existing_dump_validation_returns_restored_aggregate_counts(self):
        archive = self.directory / 'manual-recovery.dump'
        archive.write_bytes(b'PGDMP synthetic test archive')
        before = archive.read_bytes()
        runner = FakePostgres()
        counts = portal_backup.validate_dump(archive, runner=runner)
        self.assertEqual(counts, [{'table': 'public.fixture', 'rows': 2}])
        self.assertEqual(runner.stages, ['validate', 'createdb', 'isolate', 'restore', 'psql', 'dropdb'])
        self.assertEqual(archive.read_bytes(), before)
        self.assertEqual(list(self.directory.iterdir()), [archive])

    def test_failed_scratch_isolation_drops_own_database_without_restoring(self):
        old = self.dated(30)
        runner = FakePostgres(fail='isolate')
        with self.assertRaises(RuntimeError):
            self.snapshot(runner)
        self.assertEqual(runner.stages, ['dump', 'validate', 'createdb', 'isolate', 'dropdb'])
        self.assertEqual(list(self.directory.iterdir()), [old])
        self.assert_no_pending()

    def test_invalid_database_names_fail_before_database_commands(self):
        for database in ('', '--dbname=postgres', '../postgres', 'tio web',
                         'tionline_web;DROP DATABASE postgres', 'postgres\n', 'a' * 64):
            with self.subTest(database=database):
                runner = FakePostgres()
                with self.assertRaises(ValueError):
                    portal_backup.snapshot(database, self.directory, now=self.now, runner=runner)
                self.assertEqual(runner.calls, [])
                self.assertEqual(list(self.directory.iterdir()), [])

    def test_invalid_retention_tags_and_naive_time_fail_before_database_commands(self):
        for kwargs in ({'days': 0}, {'days': -1}, {'days': True}, {'days': 1.5},
                       {'tag': '../outside'}, {'tag': 'manual'},
                       {'now': self.now.replace(tzinfo=None)}):
            with self.subTest(kwargs=kwargs):
                runner = FakePostgres()
                options = {'now': self.now, **kwargs}
                with self.assertRaises(ValueError):
                    portal_backup.snapshot('tionline_web', self.directory, runner=runner, **options)
                self.assertEqual(runner.calls, [])
                self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
