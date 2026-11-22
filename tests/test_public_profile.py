from contextlib import closing
from collections import deque
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from server.presence import Presence
from server.public_profile import prisoner_card, read_profile
from tio.characters import CharacterStore
from tio.owned_pets import OwnedPetStore
from tio.protocol.binary import Reader
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.clans import string
from tio.protocol.item_list import encode_item_list
from tio.protocol.presence import Player
from tio.protocol.public_profile import decode_edit_request,decode_request,encode_profile
from tio.roster_progression import profile


class PublicProfileTests(unittest.TestCase):
    def test_viewer_receives_all_fifteen_saved_fighters(self):
        fixture = Path(__file__).resolve().parents[1] / 'evidence/owned_pet_trial.json'
        template = bytes.fromhex(json.loads(fixture.read_text())['packet_hex'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'players.sqlite3'
            characters = CharacterStore(path)
            for account, name in (('alice', b'Alice'), ('bob', b'Bob')):
                characters.create(account, CharacterCreateRequest(name, 0, (0, 0, 0, 0)))
            store = OwnedPetStore(path)
            store.ensure('alice', profile(template, 1, 1, b'Alice'), encode_item_list(1, ()), human=True)
            names = [b'Bob'] + [f'Mercenary {i}'.encode() for i in range(2, 16)]
            for identity, name in enumerate(names, 1):
                store.ensure('bob', profile(template, identity, 1, name),
                             encode_item_list(identity, ()), human=True)

            hub = Presence()
            viewer = type('Session', (), {'account': 'alice', 'database': path})()
            hub.players[viewer] = (3, Player(101, b'Alice'))
            hub.messages[viewer] = deque()
            self.assertTrue(hub.handle(viewer, b'\x68\0Bob\0'))

            reader = Reader(hub.messages[viewer].popleft())
            self.assertEqual(reader.read(2), b'\xa7\0')
            reader.u32()
            self.assertEqual(string(reader), b'Bob')
            reader.read(5)  # level and avatar
            for _ in range(2):
                string(reader)
                reader.u32()
            reader.read(2 + 11 * 4)  # presence and battle statistics
            for _ in range(3):
                while reader.read(2) != b'\0\0':
                    pass
            self.assertEqual(reader.u8(), 15)
            soldiers = []
            for _ in names:
                soldiers.append((string(reader), reader.u8()))
                reader.read(6 * 4)
            self.assertEqual(soldiers, [(name, 1) for name in names])

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

    def test_public_card_orders_native_site_before_contact(self):
        packet = encode_profile(42, b'Alice', 3, 'О себе', contact='Спросить в игре',
                                website='https://example.test')
        native_order = b''.join(value.encode('utf-16-le') + b'\0\0'
                                for value in ('О себе', 'https://example.test', 'Спросить в игре'))
        self.assertIn(native_order, packet)

    def test_public_card_sends_empty_tournament_statistics_to_viewer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'players.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB,name_key TEXT)')
                db.execute('INSERT INTO characters VALUES (?,1,?,?)', ('bob', b'Bob', 'bob'))
                db.execute('CREATE TABLE battle_rewards(account TEXT,result INTEGER)')
                db.execute('INSERT INTO battle_rewards VALUES (?,1)', ('bob',))
            hub = Presence()
            class Session:
                def __init__(self, account):
                    self.account = account
                    self.database = path
            viewer, target = Session('alice'), Session('bob')
            for session, identity, name in ((viewer, 101, b'Alice'), (target, 102, b'Bob')):
                hub.players[session] = (3, Player(identity, name))
                hub.messages[session] = deque()
            before = path.read_bytes()
            self.assertTrue(hub.handle(viewer, b'\x68\0Bob\0'))
            self.assertEqual(list(hub.messages[viewer]), [
                encode_profile(102, b'Bob', 0, '', wins=1, town=3),
                b'\xa7\x03' + bytes(32),
            ])
            self.assertFalse(hub.messages[target])
            self.assertEqual(path.read_bytes(), before)

    def test_save_is_visible_to_another_account_and_only_edits_session_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'players.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB,name_key TEXT)')
                db.executemany('INSERT INTO characters VALUES (?,1,?,?)',
                               (('alice', b'Alice', 'alice'), ('bob', b'Bob', 'bob')))
                db.execute('CREATE TABLE pet_avatars(account TEXT,pet_id INTEGER,avatar_id INTEGER)')
                db.execute('INSERT INTO pet_avatars VALUES (?,1,?)', ('bob', 1001))
            hub = Presence()
            class Session:
                def __init__(self, account, name):
                    self.database = path
                    self.account = account
                    self.probe_character_name = name
            a, b = Session('alice', b'Alice'), Session('bob', b'Bob')
            for session, identity, location in ((a, 100, 3), (b, 101, 9)):
                hub.players[session] = (location, Player(identity, session.probe_character_name))
                hub.messages[session] = deque()
            texts = b''.join(value.encode('utf-16-le') + b'\0\0'
                             for value in ('Привет', 'https://example.test', 'Bob в чате'))
            self.assertTrue(hub.handle(b, b'\x51\0' + texts))
            self.assertFalse(hub.messages[a])
            self.assertTrue(hub.handle(a, b'\x68\0Bob\0'))
            r = Reader(hub.messages[a].popleft())
            self.assertEqual(r.read(2), b'\xa7\0')
            self.assertEqual((r.u32(), r.read(4), r.u8(), r.u32()), (101, b'Bob\0', 0, 1001))
            r.read(10)
            self.assertEqual((r.u8(), r.u8()), (0, 9))
            self.assertIn(texts, r.data)
            self.assertEqual(read_profile(path, name=b'Alice').summary, '')
            self.assertEqual(read_profile(path, name=b'Bob').summary, 'Привет')

    def test_edit_rejects_invalid_text_unsafe_site_and_appended_target(self):
        valid = b'\x51\0' + b'\0\0' * 3
        self.assertEqual(decode_edit_request(valid), ('', '', ''))
        unsafe = lambda url: b'\x51\0\0\0' + url.encode('utf-16-le') + b'\0\0\0\0'
        for packet in (valid + b'Bob\0', valid[:-1], unsafe('file:///test'),
                       unsafe('https://user@example.test'), unsafe('https://a.test\n'),
                       b'\x51\0\0\xd8\0\0\0\0\0\0',
                       b'\x51\0' + ('x' * 513).encode('utf-16-le') + b'\0\0' * 3):
            with self.subTest(packet=packet[:20]), self.assertRaises(ValueError):
                decode_edit_request(packet)

    def test_prison_card_reads_current_sentence_without_charging_time(self):
        from tio.world_completion import prison_schema

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'players.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB,name_key TEXT)')
                db.execute('INSERT INTO characters VALUES (?,1,?,?)', ('bob', b'Bob', 'bob'))
                prison_schema(db)
                db.execute('INSERT INTO world_prison VALUES (?,70.5,NULL,NULL,3,0,0)', ('bob',))
            before = path.read_bytes()
            self.assertTrue(read_profile(path, name=b'BOB').jailed)
            self.assertEqual(prisoner_card(path, b'BOB'),
                             b'\xab\x02Bob\0' + struct.pack('<fI', 1.0, 71) + b'\0\0' +
                             struct.pack('<fI', 1.0, 71))
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaisesRegex(ValueError, 'не отбывает'):
                prisoner_card(path, b'Alice')
