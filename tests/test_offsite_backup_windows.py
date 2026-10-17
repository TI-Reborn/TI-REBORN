"""Recovery verification/DPAPI/retention tests using synthetic public fixtures only."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import offsite_backup_windows as offsite


def archive(files, *, manifest=None, extra=None):
    values = dict(files)
    if manifest is not None:
        values['manifest.json'] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as tar:
        for name, raw in values.items():
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
        if extra is not None:
            tar.addfile(extra, io.BytesIO(b'x' * extra.size))
    return output.getvalue()


def identity(data, *, decrypt=False):
    return data


class OffsiteBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.now = datetime(2026, 10, 7, 6, 45, 12, 345678, tzinfo=timezone.utc)
        with closing(sqlite3.connect(':memory:')) as database:
            database.execute('CREATE TABLE accounts(id INTEGER PRIMARY KEY)')
            database.executemany('INSERT INTO accounts VALUES(?)', [(1,), (2,)])
            database.commit()
            image = database.serialize()
        self.files = {name: b'synthetic public fixture' for name in offsite.PLATFORM_REQUIRED}
        self.files['data/reservation.sqlite3'] = image
        blob = b'synthetic public client blob'
        self.sha = hashlib.sha256(blob).hexdigest()
        self.files['client/updates/blobs/' + self.sha] = blob
        self.files['client/updates/manifest.json'] = json.dumps({'schema': 1, 'files': [
            {'path': 'base/fixture.dat', 'size': len(blob), 'sha256': self.sha}]}).encode()
        self.live = 'letsencrypt/live/toy.invalid/cert.pem'
        self.target = 'letsencrypt/archive/toy.invalid/cert1.pem'
        self.files[self.live] = self.files[self.target] = b'synthetic public certificate'

    def manifest(self, files=None):
        files = self.files if files is None else files
        return {
            'schema': 2, 'scope': 'platform', 'created': self.now.isoformat(),
            'files': [{'path': name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                       'mode': 0o600} for name, raw in sorted(files.items())],
            'sqlite': {'path': 'data/reservation.sqlite3', 'accounts': 2},
            'postgres': {'path': 'data/portal.dump',
                         'restored_tables': [{'table': 'public.fixture', 'rows': 2}]},
            'globals': {'path': 'data/postgres-globals.sql'},
            'tls': {'live_links': [{'path': self.live, 'target': self.target}]},
        }

    def payload(self):
        return archive(self.files, manifest=self.manifest())

    def dated(self, days, prefix='platform'):
        path = self.directory / (prefix + '-' + (self.now - timedelta(days=days)).strftime('%Y%m%dT%H%M%S%fZ') + '.dpapi')
        path.write_bytes(b'preserved synthetic old copy')
        return path

    def test_complete_manifest_and_database_image_verify_in_memory(self):
        result = offsite.verify_payload(self.payload())
        self.assertEqual(result['scope'], 'platform')
        self.assertEqual(result['accounts'], 2)
        self.assertEqual(result['portal_tables'], 1)
        self.assertEqual(result['portal_rows'], 2)
        self.assertEqual(result['verified_restore'], ['in-memory SQLite', 'remote isolated PostgreSQL'])
        self.assertNotIn('synthetic public fixture', json.dumps(result))

    def test_changed_missing_duplicate_or_unlisted_members_are_rejected(self):
        for kind in ('changed', 'missing', 'unlisted', 'duplicate'):
            with self.subTest(kind=kind):
                files, manifest = dict(self.files), self.manifest()
                extra = None
                if kind == 'changed':
                    files['portal/server.js'] = b'changed synthetic source'
                elif kind == 'missing':
                    del files['portal/server.js']
                elif kind == 'unlisted':
                    files['private-unlisted'] = b'toy'
                else:
                    extra = tarfile.TarInfo('portal/server.js')
                    extra.size = 1
                with self.assertRaises(ValueError):
                    offsite.verify_payload(archive(files, manifest=manifest, extra=extra))

    def test_archive_traversal_links_and_windows_aliases_are_rejected(self):
        for name in ('../escape', '/absolute', 'folder\\escape', 'C:/escape', 'folder/NUL.txt', 'folder/trailing.'):
            with self.subTest(name=name):
                extra = tarfile.TarInfo(name)
                extra.size = 1
                with self.assertRaises(ValueError):
                    offsite.verify_payload(archive(self.files, manifest=self.manifest(), extra=extra))
        extra = tarfile.TarInfo('external-link')
        extra.type = tarfile.SYMTYPE
        extra.linkname = '../outside'
        with self.assertRaises(ValueError):
            offsite.verify_payload(archive(self.files, manifest=self.manifest(), extra=extra))

    def test_restored_sqlite_integrity_and_counts_are_required(self):
        files = dict(self.files)
        files['data/reservation.sqlite3'] = b'not a SQLite database'
        with self.assertRaises(ValueError):
            offsite.verify_payload(archive(files, manifest=self.manifest(files)))
        manifest = self.manifest()
        manifest['sqlite']['accounts'] = 3
        with self.assertRaises(ValueError):
            offsite.verify_payload(archive(self.files, manifest=manifest))

    def test_postgres_evidence_and_tls_link_targets_are_checked(self):
        for kind in ('no-rows', 'negative', 'boolean', 'duplicate', 'tls-different', 'tls-outside'):
            with self.subTest(kind=kind):
                files, manifest = dict(self.files), self.manifest()
                rows = manifest['postgres']['restored_tables']
                if kind == 'no-rows':
                    manifest['postgres']['restored_tables'] = []
                elif kind == 'negative':
                    rows[0]['rows'] = -1
                elif kind == 'boolean':
                    rows[0]['rows'] = True
                elif kind == 'duplicate':
                    rows.append(dict(rows[0]))
                elif kind == 'tls-different':
                    files[self.target] = b'different toy certificate'
                    manifest['files'] = self.manifest(files)['files']
                else:
                    manifest['tls']['live_links'][0]['target'] = 'portal/server.js'
                with self.assertRaises(ValueError):
                    offsite.verify_payload(archive(files, manifest=manifest))

    def test_client_active_blobs_required_and_historical_blob_rejected(self):
        for kind in ('missing', 'extra'):
            files = dict(self.files)
            if kind == 'missing':
                del files['client/updates/blobs/' + self.sha]
            else:
                files['client/updates/blobs/' + ('0' * 64)] = b'old synthetic blob'
            with self.assertRaises(ValueError):
                offsite.verify_payload(archive(files, manifest=self.manifest(files)))

    def test_archive_resource_limits_are_enforced(self):
        with patch.object(offsite, 'MAX_BYTES', 1):
            with self.assertRaises(ValueError):
                offsite.verify_payload(self.payload())
        with patch.object(offsite, 'MAX_FILES', 1):
            with self.assertRaises(ValueError):
                offsite.verify_payload(self.payload())

    def test_publish_exclusive_verified_and_selective_retention(self):
        old, boundary, recent = self.dated(32), self.dated(31), self.dated(1)
        legacy = self.dated(100, prefix='tio')
        manual = self.directory / 'manual-recovery.dpapi'
        manual.write_bytes(b'preserved manual toy copy')
        invalid = self.directory / 'platform-20261301T033000000000Z.dpapi'
        invalid.write_bytes(b'preserved malformed name')
        with patch.object(offsite, 'crypt', identity):
            result = offsite.publish(self.payload(), self.directory, now=self.now)
            self.assertEqual(result['status'], 'captured')
            self.assertEqual(result['pruned'], 1)
            self.assertEqual(offsite.verify(Path(result['path']))['accounts'], 2)
        self.assertFalse(old.exists())
        for path in (boundary, recent, legacy, manual, invalid):
            self.assertTrue(path.exists())
        self.assertFalse(list(self.directory.glob('.pending-*')))

    def test_encryption_or_verification_failure_preserves_all_existing_files(self):
        old = self.dated(50)
        for kind in ('encrypt', 'verify'):
            with self.subTest(kind=kind):
                def fail(data, *, decrypt=False):
                    if (kind == 'encrypt' and not decrypt) or (kind == 'verify' and decrypt):
                        raise RuntimeError('synthetic crypt failure')
                    return data
                with patch.object(offsite, 'crypt', fail):
                    with self.assertRaises(RuntimeError):
                        offsite.publish(self.payload(), self.directory, now=self.now)
                self.assertEqual(list(self.directory.iterdir()), [old])

    def test_duplicate_or_publication_race_never_overwrites_or_rotates(self):
        old = self.dated(50)
        final = self.directory / ('platform-' + self.now.strftime('%Y%m%dT%H%M%S%fZ') + '.dpapi')
        final.write_bytes(b'existing synthetic encrypted copy')
        with patch.object(offsite, 'crypt', identity):
            with self.assertRaises(FileExistsError):
                offsite.publish(self.payload(), self.directory, now=self.now)
        self.assertEqual(final.read_bytes(), b'existing synthetic encrypted copy')
        final.unlink()
        real_verify = offsite.verify
        def racing_verify(path):
            result = real_verify(path)
            final.write_bytes(b'concurrent synthetic encrypted copy')
            return result
        with patch.object(offsite, 'crypt', identity), patch.object(offsite, 'verify', racing_verify):
            with self.assertRaises(FileExistsError):
                offsite.publish(self.payload(), self.directory, now=self.now)
        self.assertEqual(final.read_bytes(), b'concurrent synthetic encrypted copy')
        self.assertTrue(old.exists())
        self.assertFalse(list(self.directory.glob('.pending-*')))

    def test_if_due_requires_verified_recent_copy_and_rejects_future_or_invalid(self):
        future = self.dated(-1)
        bad = self.dated(0)
        with patch.object(offsite, 'crypt', identity):
            self.assertIsNone(offsite.recently_verified(self.directory, now=self.now))
            bad.unlink()
            result = offsite.publish(self.payload(), self.directory, now=self.now)
            skipped = offsite.recently_verified(self.directory, now=self.now + timedelta(minutes=1))
            self.assertEqual(skipped['status'], 'skipped')
            self.assertEqual(skipped['path'], result['path'])
            self.assertIsNone(offsite.recently_verified(self.directory, now=self.now + timedelta(days=2)))
        self.assertTrue(future.exists())

    def test_legacy_dpapi_copies_remain_verifiable(self):
        files = {name: b'legacy synthetic code fixture' for name in offsite.LEGACY_REQUIRED}
        files['reservation.sqlite3'] = self.files['data/reservation.sqlite3']
        files['metadata.json'] = json.dumps({'accounts': 2, 'database_sha256':
            hashlib.sha256(files['reservation.sqlite3']).hexdigest()}).encode()
        result = offsite.verify_payload(archive(files))
        self.assertEqual(result['scope'], 'game')
        self.assertEqual(result['verified_restore'], ['in-memory SQLite'])

    def test_remote_bundle_adapter_and_local_verifier_agree_on_complete_toy_layout(self):
        # Exercise the independently written capture module's actual schema.
        # Its PostgreSQL runner is fake; all filesystem sources are temporary.
        from tests.test_recovery_bundle import RecoveryBundleTests
        fixture = RecoveryBundleTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.write(fixture.game / 'tio' / 'battle_state.py', b'# public toy code\n')
        fixture.write(fixture.portal / 'server.js', b'// public toy runtime\n')
        (fixture.game / 'pyproject.toml').unlink()
        fixture.capture()
        result = offsite.verify_payload(fixture.output.getvalue())
        self.assertEqual(result['scope'], 'platform')
        self.assertEqual(result['accounts'], 2)
        self.assertEqual(result['portal_tables'], 1)

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows CurrentUser DPAPI integration')
    def test_real_dpapi_private_directory_lock_roundtrip_and_explicit_export(self):
        offsite._protect_directory(self.directory)
        with offsite.capture_lock(self.directory):
            with self.assertRaises(RuntimeError):
                with offsite.capture_lock(self.directory):
                    pass
            result = offsite.publish(self.payload(), self.directory, now=self.now)
        path = Path(result['path'])
        self.assertNotIn(b'public.fixture', path.read_bytes())
        self.assertEqual(offsite.verify(path)['accounts'], 2)
        exported = self.directory / 'explicit-plaintext-toy-recovery'
        offsite.export_new(path, exported)
        self.assertEqual((exported / 'data' / 'reservation.sqlite3').read_bytes(), self.files['data/reservation.sqlite3'])
        with self.assertRaises(FileExistsError):
            offsite.export_new(path, exported)
        with self.assertRaises(RuntimeError):
            offsite.crypt(b'not a valid protected DPAPI blob', decrypt=True)


if __name__ == '__main__':
    unittest.main()
