from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from deploy.scheduled_backup import snapshot


class ScheduledBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'player.sqlite3'
        self.destination = self.root / 'backups'
        self.destination.mkdir()
        self.now = datetime(2026, 9, 21, 3, tzinfo=timezone.utc)
        with closing(sqlite3.connect(self.source)) as db:
            db.execute('CREATE TABLE balance (credits INTEGER)')
            db.execute('INSERT INTO balance VALUES (1821)')
            db.commit()

    def dated(self, days):
        stamp = (self.now - timedelta(days=days)).strftime('%Y%m%dT%H%M%S%fZ')
        result = self.destination / ('auto-' + stamp + '.sqlite3')
        result.write_bytes(b'old snapshot')
        return result

    def test_verified_snapshot_and_selective_retention(self):
        old, recent, boundary = self.dated(15), self.dated(1), self.dated(14)
        manual = self.destination / 'pre-update-keep.sqlite3'
        manual.write_bytes(b'manual')
        before = self.source.read_bytes()
        result = snapshot(self.source, self.destination, now=self.now)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(old.exists())
        self.assertTrue(all(p.exists() for p in (recent, boundary, manual)))
        with closing(sqlite3.connect(result)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('SELECT credits FROM balance').fetchone()[0], 1821)
        self.assertFalse(list(self.destination.glob('.pending-*')))

    def test_failure_preserves_existing_backups(self):
        old = self.dated(30)
        self.source.write_bytes(b'not a database')
        with self.assertRaises(sqlite3.DatabaseError):
            snapshot(self.source, self.destination, now=self.now)
        self.assertTrue(old.exists())
        self.assertEqual(list(self.destination.iterdir()), [old])

    def test_duplicate_does_not_overwrite(self):
        result = snapshot(self.source, self.destination, now=self.now, tag='pre-update')
        before = result.read_bytes()
        with self.assertRaises(FileExistsError):
            snapshot(self.source, self.destination, now=self.now, tag='pre-update')
        self.assertEqual(result.read_bytes(), before)

    def test_live_wal_snapshot_excludes_uncommitted_writes(self):
        with closing(sqlite3.connect(self.source)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('UPDATE balance SET credits=1')
            result = snapshot(self.source, self.destination, now=self.now)
            with closing(sqlite3.connect(result)) as db:
                self.assertEqual(db.execute('SELECT credits FROM balance').fetchone()[0], 1821)
            writer.rollback()
