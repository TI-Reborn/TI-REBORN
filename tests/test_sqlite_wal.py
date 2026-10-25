"""Opt-in SQLite WAL: config switch, persistent mode, readers beside a writer."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from server.config import ServerConfig
from tio.db_transaction import journal_mode, transaction

BASE = '''bind_address = "127.0.0.1"
advertised_address = "127.0.0.1"
game_port = 28512
data_directory = "players"
log_level = "ERROR"
'''


class SqliteWalTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.root = Path(folder.name); self.path = self.root / 'db.sqlite3'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE t(v INTEGER)'); db.execute('INSERT INTO t VALUES (1)')

    def config(self, extra=''):
        (self.root / 'server.toml').write_text(BASE + extra)
        return ServerConfig.load(self.root / 'server.toml')

    def test_config_is_opt_in_and_strict(self):
        self.assertFalse(self.config().sqlite_wal)
        self.assertTrue(self.config('sqlite_wal = true\n').sqlite_wal)
        with self.assertRaises(ValueError):self.config('sqlite_wal = "yes"\n')

    def test_default_leaves_mode_and_switch_persists(self):
        self.assertEqual(journal_mode(self.path), 'delete')
        self.assertEqual(journal_mode(self.path, wal=True), 'wal')
        self.assertEqual(journal_mode(self.path), 'wal')  # Stored in the file.

    def test_reader_proceeds_while_gameplay_transaction_writes(self):
        journal_mode(self.path, wal=True)
        with transaction(self.path) as db:
            db.execute('UPDATE t SET v=2')
            with closing(sqlite3.connect(self.path, timeout=0)) as reader:
                self.assertEqual(reader.execute('SELECT v FROM t').fetchone()[0], 1)
        with closing(sqlite3.connect(self.path)) as reader:
            self.assertEqual(reader.execute('SELECT v FROM t').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
