from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from server.public_profile import read_profile
from tio.protocol.public_profile import decode_request,encode_profile


class PublicProfileTests(unittest.TestCase):
    def test_saved_totals_are_account_scoped_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'players.sqlite3'
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB,name_key TEXT)')
                db.executemany('INSERT INTO characters VALUES (?,1,?,?)',(('alice',b'Alice','alice'),('bob',b'Bob','bob')))
                db.execute('CREATE TABLE battle_rewards(account TEXT,result INTEGER)')
                db.executemany('INSERT INTO battle_rewards VALUES (?,?)',(('alice',1),('alice',1),('alice',0),('bob',2)))
            before=path.read_bytes()
            alice=read_profile(path,name=b'ALICE');bob=read_profile(path,name=b'Bob')
            self.assertEqual((alice.wins,alice.losses,alice.draws),(2,1,0))
            self.assertEqual((bob.wins,bob.losses,bob.draws),(0,0,1))
            self.assertIsNone(read_profile(path,name=b'Missing'))
            self.assertEqual(path.read_bytes(),before)
            packet=encode_profile(42,alice.name,alice.level,alice.summary)
            self.assertIn(b'Alice\0',packet);self.assertNotIn(b'Bob',packet)

    def test_request_validation(self):
        self.assertEqual(decode_request(b'\x68\0Alice\0'),b'Alice')
        for bad in (b'\x68',b'\x68\1Alice\0',b'\x68\0Alice',b'\x68\0Alice\0extra',b'\x68\0../db\0',b'\xc8\x68\0Alice\0'):
            with self.assertRaises(ValueError):decode_request(bad)
