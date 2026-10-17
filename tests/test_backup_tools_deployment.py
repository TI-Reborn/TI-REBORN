"""Backup deployment safety on temporary operational files, no host or DB access."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import deploy_backup_tools_remote as remote
from tools import prepare_backup_tools_deploy as local


class BackupToolsDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 10, 7, 19, 0, tzinfo=timezone.utc)
        self.package = local.prepare(self.root / 'package', now=self.now,
                                     validate_dump='/root/toy-backup/website.dump')
        self.contents, self.manifest = remote.load_package(self.package['archive'], self.package['archive_sha256'])

    def test_package_contains_exact_operational_files_and_safe_stdin_scripts(self):
        self.assertEqual(set(self.contents), set(remote.FILES))
        self.assertEqual(len(self.contents), 5)
        for value in self.contents.values():
            self.assertNotIn(b'\r', value)
        for mode, path in self.package['stdin_scripts'].items():
            compile(Path(path).read_text(), 'reviewed-' + mode, 'exec')
        self.assertFalse(self.package['remote_operations_executed'])
        self.assertNotIn('reservation.sqlite3', json.dumps(self.package['files']))

    def modified_archive(self, *, manifest=None, extra=None):
        output = self.root / 'modified.tar.gz'
        with tarfile.open(output, 'w:gz') as archive:
            for name, raw in list(self.contents.items()) + [('manifest.json', json.dumps(manifest or self.manifest).encode())]:
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
            if extra is not None:
                archive.addfile(extra, io.BytesIO(b'x' * extra.size))
        return output, hashlib.sha256(output.read_bytes()).hexdigest()

    def test_unknown_members_links_wrong_hash_and_database_target_are_refused(self):
        for name in ('../escape', '/absolute', 'reservation.sqlite3'):
            extra = tarfile.TarInfo(name)
            extra.size = 1
            path, sha = self.modified_archive(extra=extra)
            with self.assertRaises(ValueError):
                remote.load_package(path, sha)
        link = tarfile.TarInfo('deploy/backup.py')
        link.type = tarfile.SYMTYPE
        link.linkname = '/etc/secret'
        path, sha = self.modified_archive(extra=link)
        with self.assertRaises(ValueError):
            remote.load_package(path, sha)
        manifest = deepcopy(self.manifest)
        manifest['files'][0]['target'] = '/var/lib/tio-server/reservation.sqlite3'
        path, sha = self.modified_archive(manifest=manifest)
        with self.assertRaises(ValueError):
            remote.load_package(path, sha)
        with self.assertRaises(ValueError):
            remote.load_package(self.package['archive'], '0' * 64)

    def test_existing_package_and_invalid_dump_are_not_modified(self):
        before = Path(self.package['archive']).read_bytes()
        with self.assertRaises(FileExistsError):
            local.prepare(self.root / 'package', now=self.now)
        self.assertEqual(Path(self.package['archive']).read_bytes(), before)
        with self.assertRaises(ValueError):
            local.prepare(self.root / 'outside', now=self.now, validate_dump='/var/lib/live.dump')
        self.assertFalse((self.root / 'outside').exists())

    def operational_layout(self):
        mapped = {}
        originals = {}
        for index, (name, (_, mode)) in enumerate(remote.FILES.items()):
            path = self.root / 'operational' / str(index) / Path(name).name
            path.parent.mkdir(parents=True)
            if index != 1:
                originals[name] = ('synthetic previous script ' + str(index)).encode()
                path.write_bytes(originals[name])
            mapped[name] = (str(path), mode)
        baseline = {'kind': 'backup-tools-inspection', 'package_files': self.manifest['files'],
                    'before': {name: remote.state(target) for name, (target, _) in mapped.items()},
                    'game': {'ActiveState': 'active', 'MainPID': '123', 'NRestarts': '0'},
                    'portal': {'ActiveState': 'active', 'MainPID': '456', 'NRestarts': '0'},
                    'jobs': {'tio-backup': 'inactive', 'tio-portal-backup': 'inactive'}}
        return mapped, originals, baseline

    @staticmethod
    def fake_command(args, **kwargs):
        if args == ['/usr/bin/systemctl', 'daemon-reload']:
            return subprocess.CompletedProcess(args, 0, stdout='')
        raise AssertionError('Only daemon-reload is permitted in this synthetic install')

    def test_apply_backs_up_before_atomic_writes_and_does_not_restart_services(self):
        mapped, originals, baseline = self.operational_layout()
        real_write = remote.atomic_write
        def checked_write(path, raw, **kwargs):
            backups = list(self.root.glob('tio-before-backup-tools-*'))
            self.assertEqual(len(backups), 1)
            for name, value in originals.items():
                self.assertEqual((backups[0] / name).read_bytes(), value)
            return real_write(path, raw, **kwargs)
        with patch.object(remote, 'FILES', mapped), patch.object(remote, 'inspect', return_value=baseline), \
             patch.object(remote, 'atomic_write', checked_write), patch.object(remote.os, 'chown', create=True), \
             patch.object(remote, 'service', side_effect=[baseline['game'], baseline['portal']]):
            result = remote.apply(self.contents, self.manifest, baseline, runner=self.fake_command,
                                  backup_parent=self.root)
        self.assertFalse(result['service_restart'])
        self.assertFalse(result['backup_capture'])
        for name, (target, _) in mapped.items():
            self.assertEqual(Path(target).read_bytes(), self.contents[name])
        self.assertTrue((Path(result['backup']) / 'rollback.json').is_file())

    def test_partial_failure_restores_old_code_and_removes_only_its_new_file(self):
        mapped, originals, baseline = self.operational_layout()
        real_write, calls = remote.atomic_write, []
        def failing_write(path, raw, **kwargs):
            calls.append(str(path))
            if len(calls) == 3:
                raise OSError('synthetic write failure')
            return real_write(path, raw, **kwargs)
        with patch.object(remote, 'FILES', mapped), patch.object(remote, 'inspect', return_value=baseline), \
             patch.object(remote, 'atomic_write', failing_write), patch.object(remote.os, 'chown', create=True):
            with self.assertRaises(OSError):
                remote.apply(self.contents, self.manifest, baseline, runner=self.fake_command,
                             backup_parent=self.root)
        for name, (target, _) in mapped.items():
            if name in originals:
                self.assertEqual(Path(target).read_bytes(), originals[name])
            else:
                self.assertFalse(Path(target).exists())
        self.assertFalse(list((self.root / 'operational').rglob('*.backup-tools-*')))

    def test_changed_baseline_or_active_job_prevents_any_installation(self):
        mapped, originals, baseline = self.operational_layout()
        for kind in ('changed', 'active'):
            with self.subTest(kind=kind):
                actual = deepcopy(baseline)
                if kind == 'changed':
                    actual['before'][next(iter(mapped))]['sha256'] = '0' * 64
                else:
                    actual['jobs']['tio-portal-backup'] = 'active'
                with patch.object(remote, 'FILES', mapped), patch.object(remote, 'inspect', return_value=actual):
                    with self.assertRaises(RuntimeError):
                        remote.apply(self.contents, self.manifest, baseline, runner=self.fake_command,
                                     backup_parent=self.root)
                self.assertFalse(list(self.root.glob('tio-before-backup-tools-*')))
                for name, value in originals.items():
                    self.assertEqual(Path(mapped[name][0]).read_bytes(), value)


if __name__ == '__main__':
    unittest.main()
