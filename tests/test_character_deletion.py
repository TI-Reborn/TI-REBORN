"""Owned character retirement preserves saves and keeps native selection connected."""
from contextlib import closing
import sqlite3
import unittest

import test_character_slots as fixture
from tio.characters import CharacterStore
from tio.character_identity import auth_account, owner_for_name
from tio.wallets import NEW_CHARACTER_CREDITS, WalletStore
from tio.protocol.character_select import decode_character_list


class CharacterDeletionTests(unittest.TestCase):
    setUp = fixture.CharacterSlotTests.setUp
    create = fixture.CharacterSlotTests.create

    def test_delete_then_recreate_never_reuses_archived_wallet_or_save(self):
        self.create()
        old = self.store.owner('alice', 2)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE wallets SET credits=123 WHERE account=?', (old,))
        self.store.delete('alice', 2, now=1000)
        self.assertEqual([r.record_id for r in self.store.list('alice')], [1])
        with self.assertRaises(ValueError): self.store.owner('alice', 2)
        self.create(b'AliceNew')
        new = self.store.owner('alice', 2)
        self.assertNotEqual(new, old)
        self.assertEqual(auth_account(self.path, old), 'alice')
        self.assertEqual(auth_account(self.path, new), 'alice')
        self.assertEqual(WalletStore(self.path).ensure(old).credits, 123)
        self.assertEqual(WalletStore(self.path).ensure(new).credits, NEW_CHARACTER_CREDITS)
        self.assertEqual(self.accounts.verify(b'alice', fixture.PASSWORD.encode()), 'alice')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(owner_for_name(db, b'AliceTwo'))

    def test_delete_legacy_first_slot_preserves_authentication_and_other_characters(self):
        self.create()
        WalletStore(self.path).ensure('alice')
        before = self.store.list('bob')
        self.store.delete('alice', 1, now=1000)
        self.assertEqual([r.record_id for r in self.store.list('alice')], [2])
        self.store.create('alice', fixture.CharacterCreateRequest(b'AliceNew',0,(1,0,0,0)))
        self.assertNotEqual(self.store.owner('alice', 1), 'alice')
        self.assertEqual(self.store.list('bob'), before)
        self.assertEqual(self.accounts.verify(b'alice', fixture.PASSWORD.encode()), 'alice')

    def test_retirement_sql_failure_rolls_back_without_losing_save(self):
        self.create()
        before = self.store.list('alice')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER reject_retirement BEFORE INSERT ON character_revisions BEGIN SELECT RAISE(ABORT,'test rollback'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.store.delete('alice',2,now=1000)
        self.assertEqual(self.store.list('alice'), before)

    def test_retirement_refuses_persisted_battle_and_shared_clan_obligations(self):
        self.create()
        owner = self.store.owner('alice', 2)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE battle_checkpoint_members(account TEXT)')
            db.execute('INSERT INTO battle_checkpoint_members VALUES (?)',(owner,))
        with self.assertRaises(ValueError): self.store.delete('alice',2,now=1000)
        self.assertEqual(self.store.owner('alice',2),owner)

    def test_archived_primary_does_not_hide_recreated_character_from_public_ratings(self):
        from tio.world_completion import players
        self.store.delete('alice',1,now=1000)
        self.create(b'AliceNew')
        current = self.store.owner('alice',1)
        with closing(sqlite3.connect(self.path)) as db:
            public = players(db)
        self.assertIn(current, [row['owner'] for row in public])
        self.assertNotIn('alice', [row['owner'] for row in public])

    def test_missing_or_foreign_slots_are_rejected_without_modification(self):
        self.create()
        before = self.store.list('alice')
        for login, slot in (('bob',2),('alice',0),('alice',6)):
            with self.assertRaises(ValueError): self.store.delete(login,slot,now=1000)
        self.assertEqual(self.store.list('alice'), before)


class CharacterDeletionTCPTests(unittest.TestCase):
    setUp = fixture.CharacterSlotsTCPTests.setUp
    ready = fixture.CharacterSlotsTCPTests.ready
    connect = fixture.CharacterSlotsTCPTests.connect
    create_native = fixture.CharacterSlotsTCPTests.create_native

    def test_native_delete_and_rejected_delete_leave_connection_usable(self):
        self.ready()
        peer = self.connect()
        self.case.character_screen(peer)
        self.create_native(peer, b'AliceTwo', 2)
        peer.send(b'\x13\x02\0\0\0')
        self.assertEqual(peer.receive(), b'\x14\0')
        self.assertEqual([r.record_id for r in decode_character_list(peer.receive())], [1])
        peer.send(b'\x13\x05\0\0\0')
        self.assertEqual(peer.receive()[:1], b'\x14')
        self.assertEqual([r.record_id for r in decode_character_list(peer.receive())], [1])
        peer.send(b'\x13\x02')
        self.assertEqual(peer.receive(), b'\x14\x01')
        peer.receive()
        self.case.ping(peer)
        self.assertEqual(CharacterStore(self.path).list('bob')[0].name_bytes, b'Bob')
