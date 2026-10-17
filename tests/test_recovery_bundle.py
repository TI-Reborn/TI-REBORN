"""Full recovery capture safety against temporary fixtures and fake commands."""
from contextlib import closing, redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from deploy import recovery_bundle as bundle


PORTAL_VALIDATOR = Path(__file__).resolve().parents[1] / 'web' / 'deploy' / 'portal_backup.py'


class FakePostgres:
    def __init__(self, *, fail=None):
        self.fail = fail
        self.calls = []

    def __call__(self, args, *, check=True, stdin=None, stdout=None, stderr=None):
        args = [str(value) for value in args]
        if args[:8] != ['/usr/sbin/runuser', '-u', 'postgres', '--', '/usr/bin/env', '-i',
                       'PATH=/usr/lib/postgresql/16/bin:/usr/bin:/bin', 'LANG=C.UTF-8'] or not check:
            raise AssertionError('Unsafe synthetic database command')
        command = [Path(args[8]).name, *args[9:]]
        for required in ('--host=/var/run/postgresql', '--port=5432', '--username=postgres'):
            if required not in command:
                raise AssertionError('Database commands must target the local PostgreSQL socket')
        phase = command[0]
        if phase == 'pg_restore':
            phase = 'validate' if '--file=/dev/null' in command else 'restore'
        elif phase == 'psql' and any(value.startswith('--command=REVOKE CONNECT') for value in command):
            phase = 'isolate'
        self.calls.append((phase, command))
        if phase in ('pg_dump', 'pg_dumpall'):
            stdout.write(b'PGDMP synthetic archive' if phase == 'pg_dump'
                         else b'-- synthetic private globals\nCREATE ROLE toy_user;\n')
        if phase == self.fail:
            raise subprocess.CalledProcessError(1, args, stderr=b'PRIVATE_SYNTHETIC_FAILURE')
        rows = b'[{"table":"public.fixture","rows":2}]\n' if phase == 'psql' else None
        return subprocess.CompletedProcess(args, 0, stdout=rows)


class RecoveryBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / 'game'
        for name in ('server', 'tio', 'tools', 'config', 'deploy', 'registration'):
            self.write(self.game / name / 'fixture.py', b'game code fixture\n')
        self.write(self.game / 'server' / 'runtime.py',
                   b"RUNTIME_ASSETS = ('catalog.xml', 'map.json')\n"
                   b"raise AssertionError('Runtime code must never be imported for capture')\n")
        self.write(self.game / 'requirements.txt', b'fixture-package==1.0\n')
        self.write(self.game / 'pyproject.toml', b'[project]\nname="fixture"\n')
        self.write(self.game / 'evidence' / 'catalog.xml', b'<fixture />\n')
        self.write(self.game / 'evidence' / 'map.json', b'{"fixture":true}\n')
        self.write(self.game / 'tools' / '__pycache__' / 'omit.pyc', b'cache')
        self.database = self.root / 'hosted.sqlite3'
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)')
            db.executemany('INSERT INTO accounts VALUES (?, ?)', [(1, 'toy_one'), (2, 'toy_two')])
            db.commit()
        self.portal = self.root / 'portal-current'
        self.write(self.portal / 'package.json', b'{"name":"toy-portal"}\n')
        self.write(self.portal / '.next' / 'server' / 'app.js', b'portal runtime\n')
        self.write(self.portal / '.next' / 'cache' / 'omit', b'cache')
        self.write(self.portal / 'node_modules' / 'fixture' / 'index.js', b'portal dependency\n')
        maintenance = self.root / 'portal-maintenance'
        maintenance.mkdir()
        shutil.copyfile(PORTAL_VALIDATOR, maintenance / 'portal_backup.py')
        self.write(maintenance / 'backup_portal.sh', b'#!/bin/sh\n# fixture\n')
        self.write(maintenance / 'cleanup.sql', b'-- fixture maintenance\n')
        self.private_game = self.root / 'etc' / 'tio-server'
        self.private_portal = self.root / 'etc' / 'tio-portal'
        self.write(self.private_game / 'server.toml', b'# synthetic private configuration\n')
        self.write(self.private_portal / 'portal.env', b'SYNTHETIC_PRIVATE_VALUE=fixture\n')
        self.nginx = self.root / 'etc' / 'nginx' / 'nginx.conf'
        self.write(self.nginx, b'# fixture nginx\n')
        self.tls = self.root / 'etc' / 'letsencrypt'
        for name in ('cert.pem', 'chain.pem', 'fullchain.pem', 'privkey.pem'):
            self.write(self.tls / 'live' / 'toy.invalid' / name, b'synthetic TLS material\n')
        self.write(self.tls / 'renewal' / 'toy.invalid.conf', b'# fixture renewal\n')
        self.write(self.tls / 'accounts' / 'acme.invalid' / 'toy' / 'account.json', b'{"fixture":true}\n')
        self.write(self.tls / 'options-ssl-nginx.conf', b'# fixture TLS options\n')
        self.write(self.tls / 'ssl-dhparams.pem', b'synthetic DH parameters\n')
        self.units = self.root / 'etc' / 'systemd'
        for name in ('tio-server.service', 'tio-portal.service', 'tio-backup.timer',
                     'tio-portal-backup.service', 'tio-cert-renew.timer'):
            self.write(self.units / name, b'# fixture systemd unit\n')
        self.write(self.units / 'tio-server.service.d' / 'status.conf', b'# fixture drop-in\n')
        self.write(self.units / 'unrelated.service', b'must not be included\n')
        self.runtime = self.root / 'tio-node'
        self.write(self.runtime / 'bin' / 'node', b'synthetic Node runtime\n')
        self.client = self.root / 'client'
        self.blob = b'published client fixture\n'
        self.sha = hashlib.sha256(self.blob).hexdigest()
        self.write(self.client / 'updates' / 'blobs' / self.sha, self.blob)
        self.write(self.client / 'updates' / 'blobs' / ('0' * 64), b'unreferenced historical blob\n')
        self.client_manifest = self.client / 'updates' / 'manifest.json'
        manifest = {'schema': 1, 'version': 'synthetic.1', 'files': [
            {'path': 'base/fixture.dat', 'size': len(self.blob), 'sha256': self.sha},
            {'path': 'base/shared.dat', 'size': len(self.blob), 'sha256': self.sha},
        ]}
        self.write(self.client_manifest, json.dumps(manifest).encode())
        self.write(self.client / 'downloads' / 'TionlineLauncher.exe', b'synthetic launcher\n')
        self.layout = bundle.Layout(
            game=self.game, sqlite=self.database, portal=self.portal, client=self.client,
            config=(self.private_game, self.private_portal), nginx=(self.nginx,),
            letsencrypt=self.tls, systemd=self.units,
            portal_backup_module=maintenance / 'portal_backup.py', runtime=(self.runtime,),
        )
        self.now = datetime(2026, 10, 7, 9, 1, 2, 345678, tzinfo=timezone.utc)
        self.output = io.BytesIO()
        self.runner = FakePostgres()

    @staticmethod
    def write(path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def capture(self, **kwargs):
        return bundle.capture(self.layout, output=self.output, runner=self.runner,
                              now=self.now, **kwargs)

    def test_deployed_module_layout_without_optional_pyproject_is_complete(self):
        (self.game / 'pyproject.toml').unlink()
        manifest = self.capture()
        records = {record['path'] for record in manifest['files']}
        self.assertIn('game/requirements.txt', records)
        self.assertNotIn('game/pyproject.toml', records)
        self.assertEqual(manifest['postgres']['restored_tables'], [{'table': 'public.fixture', 'rows': 2}])

    def test_complete_verified_bundle_contains_only_regular_checksummed_members(self):
        database_before = self.database.read_bytes()
        console = io.StringIO()
        with redirect_stdout(console):
            manifest = self.capture()
        self.assertEqual(console.getvalue(), '')
        self.assertEqual(self.database.read_bytes(), database_before)
        self.assertEqual(manifest['schema'], 2)
        self.assertEqual(manifest['scope'], 'platform')
        self.assertEqual(manifest['sqlite'], {'path': 'data/reservation.sqlite3', 'accounts': 2})
        self.assertEqual(manifest['postgres'], {
            'path': 'data/portal.dump', 'restored_tables': [{'table': 'public.fixture', 'rows': 2}]})
        self.assertEqual(manifest['globals']['path'], 'data/postgres-globals.sql')
        records = {record['path']: record for record in manifest['files']}
        with tarfile.open(fileobj=io.BytesIO(self.output.getvalue()), mode='r:gz') as archive:
            names = set(archive.getnames())
            self.assertEqual(names, set(records) | {'manifest.json'})
            self.assertEqual(json.load(archive.extractfile('manifest.json')), manifest)
            for member in archive:
                self.assertTrue(member.isfile(), member.name)
                bundle.safe_member(member.name)
                if member.name != 'manifest.json':
                    raw = archive.extractfile(member).read()
                    self.assertEqual(len(raw), records[member.name]['size'])
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), records[member.name]['sha256'])
            self.assertTrue({
                'game/server/runtime.py', 'game/tio/fixture.py', 'game/tools/fixture.py',
                'game/config/fixture.py', 'game/deploy/fixture.py', 'game/registration/fixture.py',
                'game/evidence/catalog.xml', 'game/evidence/map.json', 'game/requirements.txt',
                'game/pyproject.toml', 'portal/.next/server/app.js',
                'portal/node_modules/fixture/index.js', 'portal-maintenance/portal_backup.py',
                'portal-maintenance/backup_portal.sh', 'portal-maintenance/cleanup.sql',
                'config/tio-server/server.toml', 'config/tio-portal/portal.env', 'nginx/nginx.conf',
                'letsencrypt/live/toy.invalid/privkey.pem', 'letsencrypt/renewal/toy.invalid.conf',
                'letsencrypt/accounts/acme.invalid/toy/account.json', 'systemd/tio-server.service',
                'letsencrypt/options-ssl-nginx.conf', 'letsencrypt/ssl-dhparams.pem',
                'systemd/tio-portal.service', 'systemd/tio-server.service.d/status.conf',
                'runtime/tio-node/bin/node', 'client/updates/manifest.json',
                'client/updates/blobs/' + self.sha, 'client/downloads/TionlineLauncher.exe',
            }.issubset(names))
            self.assertNotIn('client/updates/blobs/' + '0' * 64, names)
            self.assertFalse(any('__pycache__' in name or '.next/cache/' in name for name in names))
            self.assertNotIn('systemd/unrelated.service', names)
            with closing(sqlite3.connect(':memory:')) as db:
                db.deserialize(archive.extractfile('data/reservation.sqlite3').read())
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.execute('SELECT count(*) FROM accounts').fetchone()[0], 2)
        self.assertEqual([phase for phase, _ in self.runner.calls],
                         ['pg_dump', 'validate', 'createdb', 'isolate', 'restore', 'psql', 'dropdb', 'pg_dumpall'])

    def test_live_sqlite_snapshot_contains_committed_wal_but_excludes_uncommitted_rows(self):
        with closing(sqlite3.connect(self.database)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute("INSERT INTO accounts VALUES (3, 'committed_toy')")
            writer.commit()
            writer.execute("INSERT INTO accounts VALUES (4, 'uncommitted_toy')")
            manifest = self.capture()
            self.assertEqual(manifest['sqlite']['accounts'], 3)
            writer.rollback()

    def test_corrupt_referenced_client_blob_fails_before_any_archive_output(self):
        (self.client / 'updates' / 'blobs' / self.sha).write_bytes(b'corrupt fixture')
        with self.assertRaises(RuntimeError):
            self.capture()
        self.assertEqual(self.output.getvalue(), b'')

    def test_changed_active_client_manifest_rejects_otherwise_valid_archive(self):
        original_verify = bundle._verify_archive

        def concurrent_publish(*args, **kwargs):
            original_verify(*args, **kwargs)
            self.client_manifest.write_bytes(b'{"schema":1,"files":[]}')

        with patch.object(bundle, '_verify_archive', side_effect=concurrent_publish):
            with self.assertRaisesRegex(RuntimeError, 'Active client manifest changed'):
                self.capture()
        self.assertEqual(self.output.getvalue(), b'')

    def test_changed_portal_release_rejects_otherwise_valid_archive(self):
        original_required = bundle._required
        original_verify = bundle._verify_archive
        changed = False

        def resolve(path):
            if changed and Path(path) == self.layout.portal:
                return self.root / 'different-portal-release'
            return original_required(path)

        def verified(*args, **kwargs):
            nonlocal changed
            original_verify(*args, **kwargs)
            changed = True

        with patch.object(bundle, '_required', side_effect=resolve), \
                patch.object(bundle, '_verify_archive', side_effect=verified):
            with self.assertRaisesRegex(RuntimeError, 'Active portal release changed'):
                self.capture()
        self.assertEqual(self.output.getvalue(), b'')

    def test_missing_required_sources_fail_closed_without_archive_output(self):
        (self.game / 'evidence' / 'catalog.xml').unlink()
        with self.assertRaises(RuntimeError):
            self.capture()
        self.assertEqual(self.output.getvalue(), b'')

    def test_database_failure_never_leaks_process_errors_or_archive_bytes(self):
        self.runner.fail = 'pg_dumpall'
        with self.assertRaises(RuntimeError) as raised:
            self.capture()
        self.assertNotIn('PRIVATE_SYNTHETIC_FAILURE', str(raised.exception))
        self.assertNotIn('runuser', str(raised.exception))
        self.assertEqual(self.output.getvalue(), b'')

    def test_limits_reject_capture_before_output(self):
        for kwargs in ({'max_bytes': 10}, {'max_files': 1}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(RuntimeError):
                    self.capture(**kwargs)
                self.assertEqual(self.output.getvalue(), b'')

    def test_duplicate_archive_names_are_rejected(self):
        self.layout = replace(self.layout, config=(self.private_game, self.private_game))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.capture()
        self.assertEqual(self.output.getvalue(), b'')

    def test_unsafe_archive_paths_and_sources_outside_roots_are_rejected(self):
        for name in ('/absolute', '../outside', 'safe/../outside', 'safe\\outside',
                     'C:/outside', 'safe//file', './file', ''):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    bundle.safe_member(name)
        with self.assertRaises(ValueError):
            bundle._within(self.nginx, self.game.resolve())

    def test_symlink_outside_approved_config_root_is_rejected(self):
        link = self.private_game / 'escape'
        try:
            link.symlink_to(self.nginx)
        except (OSError, NotImplementedError):
            self.skipTest('Creating symbolic links is unavailable on this test host')
        with self.assertRaisesRegex(ValueError, 'approved root'):
            self.capture()
        self.assertEqual(self.output.getvalue(), b'')

    def test_tls_symlinks_inside_approved_root_are_materialized_as_regular_files(self):
        target = self.tls / 'archive' / 'toy.invalid' / 'privkey1.pem'
        self.write(target, b'synthetic archived private key\n')
        link = self.tls / 'live' / 'toy.invalid' / 'privkey.pem'
        link.unlink()
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('Creating symbolic links is unavailable on this test host')
        manifest = self.capture()
        with tarfile.open(fileobj=io.BytesIO(self.output.getvalue()), mode='r:gz') as archive:
            member = archive.getmember('letsencrypt/live/toy.invalid/privkey.pem')
            self.assertTrue(member.isfile())
            self.assertEqual(archive.extractfile(member).read(), target.read_bytes())
            self.assertIn('letsencrypt/archive/toy.invalid/privkey1.pem', archive.getnames())
            self.assertEqual(manifest['tls']['live_links'], [{
                'path': 'letsencrypt/live/toy.invalid/privkey.pem',
                'target': 'letsencrypt/archive/toy.invalid/privkey1.pem',
            }])

    def test_cli_error_is_sanitized_without_private_paths_or_payload(self):
        console = io.StringIO()
        with patch.object(bundle, 'capture', side_effect=RuntimeError('PRIVATE_SYNTHETIC_FAILURE')), \
                patch.object(bundle.sys, 'stderr', console):
            self.assertEqual(bundle.main(), 1)
        self.assertNotIn('PRIVATE_SYNTHETIC_FAILURE', console.getvalue())
        self.assertIn('capture failed', console.getvalue())


if __name__ == '__main__':
    unittest.main()
