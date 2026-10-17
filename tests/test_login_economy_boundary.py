"""A native empty selection screen grants no economy state or lost wallet."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from server.accounts import Accounts
from server.multi import MultiServer
from tio import bank_economy
from tio.characters import CharacterStore
from tio.protocol.character_create import CharacterCreateRequest, encode_character_create
from tio.shooting_range import AdmissionStore
from tio.wallets import STARTING_CREDITS, STARTING_GOLD


class LoginEconomyBoundaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)/'players.sqlite3'
        self.accounts = Accounts(self.path)
        self.accounts.create('new_user', 'fixture-password-123')
        self.admission = AdmissionStore(self.path)
        self.exchange = SimpleNamespace(shooting_range=SimpleNamespace(admission=self.admission))
        self.multi = MultiServer.__new__(MultiServer)
        self.multi.config = SimpleNamespace(database=self.path)

    def rows(self, table):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT * FROM '+table).fetchall()

    def test_account_without_character_never_opens_bank_or_seeds_economy(self):
        with patch.object(bank_economy, 'owner', side_effect=AssertionError('Premature bank access')):
            with patch.object(self.admission, 'assets', wraps=self.admission.assets) as assets:
                self.assertFalse(self.multi.initialize_character_economy(self.exchange, 'new_user'))
                assets.assert_not_called()
        self.assertEqual(self.rows('characters'), [])
        self.assertEqual(self.rows('wallets'), [])
        self.assertEqual(self.rows('range_accounts'), [])

    def test_existing_character_with_missing_wallet_rejects_before_ensure(self):
        self.accounts.create('existing_user', 'fixture-password-123', character='ExistingUser')
        with patch.object(self.admission, 'assets', wraps=self.admission.assets) as assets:
            with self.assertRaises(bank_economy.BankRejected):
                self.multi.initialize_character_economy(self.exchange, 'existing_user')
            assets.assert_not_called()
        self.assertEqual(self.rows('wallets'), [])
        self.assertEqual(self.rows('range_accounts'), [])
        self.assertEqual(len(self.rows('characters')), 1)

    def test_native_creation_grants_once_then_login_preserves_saved_balance(self):
        CharacterStore(self.path).create('new_user', CharacterCreateRequest(b'NewUser', 0, (1,0,0,0)))
        self.assertEqual(self.rows('wallets'), [('new_user', STARTING_CREDITS, STARTING_GOLD)])
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE wallets SET credits=537,gold=11 WHERE account='new_user'")
        self.assertTrue(self.multi.initialize_character_economy(self.exchange, 'new_user'))
        self.assertTrue(self.multi.initialize_character_economy(self.exchange, 'new_user'))
        self.assertEqual(self.rows('wallets'), [('new_user', 537, 11)])
        self.assertEqual([row[0] for row in self.rows('range_accounts')], ['new_user'])
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM wallets WHERE account='new_user'")
        with self.assertRaises(bank_economy.BankRejected):
            self.multi.initialize_character_economy(self.exchange, 'new_user')
        self.assertEqual(self.rows('wallets'), [])


class NativeTCPLoginEconomyBoundaryTests(unittest.TestCase):
    def setUp(self):
        # Reuse the real two-port encrypted TCP harness without inheriting its
        # unrelated test methods. Every fixture cleanup belongs to this case.
        import test_multi_account as multiplayer
        self.game = multiplayer.MultiAccountTests()
        self.game.addCleanup = self.addCleanup
        self.game.setUp()
        self.password = multiplayer.PASSWORD

    def account_rows(self, table, account):
        with closing(sqlite3.connect(self.game.config.database)) as db:
            return db.execute('SELECT * FROM '+table+' WHERE account=?', (account,)).fetchall()

    def test_real_native_login_and_empty_character_screen_seed_nothing_before_create(self):
        self.game.accounts.create('new_user', self.password)
        self.game.start()
        peer = self.game.handoff(self.game.begin('new_user'))
        self.assertEqual(self.game.character_screen(peer), ())
        self.game.ping(peer)
        for table in ('characters','wallets','range_accounts','owned_pets', 'bank_securities'):
            self.assertEqual(self.account_rows(table, 'new_user'), [], table)
        peer.send(encode_character_create(CharacterCreateRequest(b'NewUser', 0, (1,0,0,0))))
        self.assertEqual(peer.receive(), b'\x12\x05')
        self.assertEqual(peer.receive()[:1], b'\x10')
        self.assertEqual(self.account_rows('wallets', 'new_user'), [('new_user', STARTING_CREDITS, STARTING_GOLD)])
        self.assertEqual(self.account_rows('range_accounts', 'new_user'), [])

    def test_real_login_rejects_lost_wallet_without_creating_a_replacement(self):
        with closing(sqlite3.connect(self.game.config.database)) as db, db:
            db.execute("DELETE FROM wallets WHERE account='alice'")
        self.game.start()
        with self.assertRaises((EOFError, ConnectionResetError)):
            self.game.begin('alice')
        self.assertEqual(self.account_rows('wallets', 'alice'), [])
        self.assertEqual(self.account_rows('range_accounts', 'alice'), [])
        self.assertEqual(len(self.account_rows('characters', 'alice')), 1)


if __name__ == '__main__':
    unittest.main()
