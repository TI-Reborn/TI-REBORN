"""Exercise UI publication failures against isolated files, never the VPS."""
from contextlib import closing, nullcontext
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from deploy import publish_menu_interface_update as publisher
from launcher.build_menu_interface_update import build
from tools import deploy_menu_interface_remote as remote


def record(path, raw, seed=False):
    return dict(path=path, size=len(raw), sha256=remote.sha(raw), seed=seed)


class MenuInterfacePublishSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.live = self.root / 'live'
        (self.live / 'blobs').mkdir(parents=True)
        self.original = dict(schema=1, version='2026.10.07.3', news='Existing', files=[
            record('base/pda/mainbg.jpg', b'old image'),
            record('base/config.cfg', b'client preferences', True),
            record('base/autoexec.cfg', b'client server address', True),
            record('silver.dll', b'unchanged executable'),
        ])
        self.original_raw = (json.dumps(self.original, indent=2) + '\n').encode()
        (self.live / 'manifest.json').write_bytes(self.original_raw)
        (self.live / 'blobs' / remote.sha(b'old image')).write_bytes(b'old image')
        previous = self.root / 'previous.json'
        previous.write_bytes(self.original_raw)
        assets = self.root / 'assets'
        assets.mkdir()
        (assets / 'mainbg.jpg').write_bytes(b'new image')
        self.output = self.root / 'release'
        self.proof = build(previous, assets, {'base/pda/mainbg.jpg': 'mainbg.jpg'},
                           '2026.10.07.4', self.output)
        self.new_raw = (self.output / 'client-release/manifest.json').read_bytes()
        self.database = self.root / 'hosted.sqlite3'
        with closing(sqlite3.connect(self.database)) as database, database:
            database.execute('CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)')
            database.executemany('INSERT INTO accounts VALUES (?, ?)', [(1, 'real_one'), (2, 'real_two')])
        self.database_raw = self.database.read_bytes()
        self.code = self.root / 'code'
        self.code.mkdir()
        (self.code / 'server.py').write_text('preserved code\n')
        self.config = self.root / 'server.toml'
        self.config.write_text('preserved hosted config\n')
        self.fragment = self.root / 'tio-server.service'
        self.fragment.write_text('preserved hosted service\n')
        self.dropin = self.root / 'portal-status.conf'
        self.dropin.write_text('preserved hosted service environment\n')
        staging = self.root / 'staging'
        staging.mkdir()
        for name, value in (('LIVE', self.live), ('DATABASE', self.database),
                            ('ROOT', self.code), ('CONFIGURATION', self.config),
                            ('STAGING_ROOT', staging)):
            self.enterContext(patch.object(remote, name, value))
        self.enterContext(patch.object(remote, 'publication_lock', side_effect=nullcontext))
        def fake_command(*args):
            if '--property=DropInPaths' in args:
                return str(self.dropin).replace('\\', '/')
            if 'cat' in args:
                return 'preserved effective service configuration'
            return str(self.fragment)
        self.enterContext(patch.object(remote, 'command', side_effect=fake_command))
        self.state = self.enterContext(patch.object(remote, 'service_state', return_value=('active', '123')))

    def publish(self):
        return remote.publish(self.output / 'patch.tar.gz', self.proof['archive_sha256'])

    def assert_database_preserved(self):
        self.assertEqual(self.database.read_bytes(), self.database_raw)
        with closing(sqlite3.connect(f'file:{self.database}?mode=ro', uri=True)) as database:
            self.assertEqual(database.execute('SELECT name FROM accounts ORDER BY id').fetchall(),
                             [('real_one',), ('real_two',)])

    def test_success_preserves_accounts_seed_configs_and_code_with_complete_backup(self):
        result = self.publish()
        self.assertEqual((self.live / 'manifest.json').read_bytes(), self.new_raw)
        self.assertFalse(result['service_restarted'])
        self.assertEqual(result['accounts_after'], 2)
        self.assertEqual(result['service_dropins_backed_up'], 1)
        backup = Path(result['backup'])
        self.assertEqual((backup / 'client-manifest.json').read_bytes(), self.original_raw)
        for name in ('reservation.sqlite3', 'server.toml', 'tio-server.service',
                     'previous-code-config.tar.gz', 'deployment.json',
                     'effective-tio-server.service', 'service-dropins/portal-status.conf'):
            self.assertTrue((backup / name).is_file(), name)
        with closing(sqlite3.connect(backup / 'reservation.sqlite3')) as database:
            self.assertEqual(database.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(database.execute('SELECT COUNT(*) FROM accounts').fetchone()[0], 2)
        updated = json.loads(self.new_raw)
        self.assertEqual(updated['files'][1:], self.original['files'][1:])
        self.assertEqual((self.code / 'server.py').read_text(), 'preserved code\n')
        self.assert_database_preserved()

    def test_corrupt_existing_old_blob_refuses_without_manifest_commit(self):
        (self.live / 'blobs' / remote.sha(b'old image')).write_bytes(b'corrupt prior image')
        with self.assertRaisesRegex(ValueError, 'blob size/checksum mismatch'):
            self.publish()
        self.assertEqual((self.live / 'manifest.json').read_bytes(), self.original_raw)
        self.assertFalse((self.live / 'blobs' / remote.sha(b'new image')).exists())
        self.assert_database_preserved()

    def test_corrupt_preexisting_new_blob_refuses_without_overwriting_it(self):
        target = self.live / 'blobs' / remote.sha(b'new image')
        target.write_bytes(b'corrupt cached image')
        with self.assertRaisesRegex(ValueError, 'blob size/checksum mismatch'):
            self.publish()
        self.assertEqual(target.read_bytes(), b'corrupt cached image')
        self.assertEqual((self.live / 'manifest.json').read_bytes(), self.original_raw)
        self.assert_database_preserved()

    def test_stale_baseline_after_backup_does_not_clobber_competing_manifest(self):
        competing = dict(self.original, version='2026.10.07.5')
        competing_raw = json.dumps(competing).encode()
        actual_backup = remote.copy_code_backup

        def change_baseline(backup):
            actual_backup(backup)
            (self.live / 'manifest.json').write_bytes(competing_raw)

        with patch.object(remote, 'copy_code_backup', side_effect=change_baseline), \
                self.assertRaisesRegex(ValueError, 'baseline changed while backing up'):
            self.publish()
        self.assertEqual((self.live / 'manifest.json').read_bytes(), competing_raw)
        self.assertFalse((self.live / 'blobs' / remote.sha(b'new image')).exists())
        self.assert_database_preserved()

    def test_audit_report_write_failure_rolls_back_manifest(self):
        original_write = Path.write_text

        def fail_report(path, *args, **kwargs):
            if path.name == 'deployment.json':
                raise OSError('simulated audit storage failure')
            return original_write(path, *args, **kwargs)

        with patch.object(Path, 'write_text', fail_report), \
                self.assertRaisesRegex(OSError, 'audit storage failure'):
            self.publish()
        self.assertEqual((self.live / 'manifest.json').read_bytes(), self.original_raw)
        self.assert_database_preserved()

    def test_postcommit_failure_does_not_rollback_another_publisher(self):
        competing = dict(self.original, version='2026.10.07.5')
        competing_raw = json.dumps(competing).encode()
        calls = 0

        def service_change():
            nonlocal calls
            calls += 1
            if calls == 3:
                (self.live / 'manifest.json').write_bytes(competing_raw)
                return ('active', '456')
            return ('active', '123')

        self.state.side_effect = service_change
        with self.assertRaisesRegex(ValueError, 'service or server code changed'):
            self.publish()
        self.assertEqual((self.live / 'manifest.json').read_bytes(), competing_raw)
        self.assert_database_preserved()

    def test_local_publisher_rejects_archive_different_from_reviewed_loose_release(self):
        alternate = self.root / 'alternate-assets'
        alternate.mkdir()
        (alternate / 'mainbg.jpg').write_bytes(b'alternate UI image')
        alternate_output = self.root / 'alternate-release'
        alternate_proof = build(self.root / 'previous.json', alternate,
            {'base/pda/mainbg.jpg': 'mainbg.jpg'}, '2026.10.07.4', alternate_output)
        shutil.copy2(alternate_output / 'patch.tar.gz', self.output / 'patch.tar.gz')
        proof = dict(self.proof, archive_sha256=alternate_proof['archive_sha256'])
        (self.output / 'release-verification.json').write_text(json.dumps(proof))
        with patch.object(publisher, 'fetch', side_effect=AssertionError('No network allowed')), \
                self.assertRaisesRegex(ValueError, 'Archive contents differ'):
            publisher.publish(self.output)
        self.assertEqual((self.live / 'manifest.json').read_bytes(), self.original_raw)


if __name__ == '__main__':
    unittest.main()
