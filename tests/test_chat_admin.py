"""Server-authoritative player administration through the native chat path."""
from collections import deque
from contextlib import closing, redirect_stdout
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest

from server.accounts import Accounts
from server.auth_errors import LoginRejected
from server.player_admin import main
from server.presence import Presence
from tio import world_completion
from tio.character_identity import alias
from tio.locations import LocationStore
from tio.protocol.chat import encode_message
from tio.protocol.presence import Player

MODERATION_NOTICE = b'\x22\0\0\0\0\x09Moderation\0'


class PlayerAdminTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.path = root / 'reservation.sqlite3'
        self.config = root / 'server.toml'
        self.config.write_text(
            'bind_address="127.0.0.1"\nadvertised_address="127.0.0.1"\n'
            'game_port=28512\ndata_directory="."\nlog_level="INFO"\n'
            'multi_account=true\n', encoding='utf-8')
        accounts = Accounts(self.path)
        accounts.create('first_login', 'first-test-password', character='FirstPlayer')
        accounts.create('second_login', 'second-test-password', character='SecondPlayer')
        LocationStore(self.path)
        self.hub = Presence()
        self.first = self.session('first_login', b'FirstPlayer')
        self.second = self.session('second_login', b'SecondPlayer')

    def session(self, login, name):
        class Session:
            pass
        session = Session()
        session.authenticated_account = session.account = login
        session.database = self.path
        self.hub.players[session] = (3, Player(len(self.hub.players) + 1, name))
        self.hub.messages[session] = deque()
        return session

    def cli(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--config', str(self.config), *args]), 0)
        return output.getvalue().splitlines()

    def send(self, session, text, channel=0):
        packet = bytes((0x21, channel)) + text.encode('utf-16-le') + b'\0\0'
        self.assertTrue(self.hub.handle(session, packet))
        return self.hub.messages[session].popleft()

    def prison(self, login='second_login'):
        with closing(sqlite3.connect(self.path)) as db:
            return world_completion.prison_state(db, login)

    def test_grant_and_revoke_change_authorization_for_connected_accounts(self):
        self.assertEqual(self.cli('list'), [])
        self.assertTrue(self.send(self.first, '//jail SecondPlayer 30 case1').startswith(b'\xf0'))
        self.assertIsNone(self.prison())
        self.cli('grant', 'first_login')
        self.cli('grant', 'first_login')
        self.assertEqual(self.cli('list'), ['first_login'])
        self.first.account = alias('first_login', 2)
        self.assertTrue(self.send(self.first, '//jail SecondPlayer 30 case1').startswith(MODERATION_NOTICE))
        self.assertEqual(self.prison(), {'remaining': 30, 'town_id': 10})
        self.assertFalse(self.hub.messages[self.second])
        self.cli('revoke', 'first_login')
        self.cli('revoke', 'first_login')
        self.assertEqual(self.cli('list'), [])
        self.assertTrue(self.send(self.first, '//jail SecondPlayer 30 case2').startswith(b'\xf0'))
        self.assertEqual(self.prison()['remaining'], 30)

    def test_repeated_case_does_not_extend_sentence(self):
        self.cli('grant', 'first_login')
        self.assertTrue(self.send(self.first, '//jail SecondPlayer 30 case1').startswith(MODERATION_NOTICE))
        self.assertTrue(self.send(self.first, '//jail SecondPlayer 30 case1').startswith(MODERATION_NOTICE))
        self.assertTrue(self.send(self.first, '//jail SecondPlayer 31 case1').startswith(b'\xf0'))
        self.assertEqual(self.prison()['remaining'], 30)

    def test_admin_cannot_sentence_other_admin_and_command_requires_local_channel(self):
        self.cli('grant', 'first_login')
        self.assertTrue(self.send(self.first, '//jail SecondPlayer 30 case1', 12).startswith(b'\xf0'))
        self.cli('grant', 'second_login')
        self.assertTrue(self.send(self.first, '//jail SecondPlayer 30 case2').startswith(b'\xf0'))
        self.assertIsNone(self.prison())

    def test_unknown_login_is_not_preprovisioned(self):
        with self.assertRaises(SystemExit) as error:
            self.cli('grant', 'unknown_login')
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.cli('list'), [])

    def test_deleted_login_does_not_keep_its_grant(self):
        self.cli('grant', 'first_login')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM accounts WHERE login='first_login'")
        self.assertEqual(self.cli('list'), [])

    def test_ordinary_chat_keeps_wire_format(self):
        self.hub.handle(self.first, b'\x21\0' + 'hi'.encode('utf-16-le') + b'\0\0')
        self.assertEqual(self.hub.messages[self.second].popleft(),
                         encode_message(0, b'FirstPlayer', 'hi'))

    def test_chat_ban_quiets_all_slots_and_operator_can_lift_it(self):
        self.cli('grant', 'first_login')
        applied = self.send(self.first, '//banchat SecondPlayer 2 Rules violation')
        self.assertTrue(applied.startswith(MODERATION_NOTICE))
        self.second.account = alias('second_login', 2)
        denied = self.send(self.second, 'hello', 12)
        self.assertIn('Чат заблокирован', denied[13:-2].decode('utf-16-le'))
        self.assertFalse(self.hub.messages[self.first])
        self.cli('unmute', 'second_login')
        self.hub.handle(self.second, b'\x21\x0c' + 'hello'.encode('utf-16-le') + b'\0\0')
        self.assertEqual(self.hub.messages[self.first].popleft(),
                         encode_message(12, b'SecondPlayer', 'hello'))

    def test_account_ban_blocks_login_until_operator_lifts_it(self):
        self.cli('grant', 'first_login')
        self.assertTrue(self.send(self.first, '//ban SecondPlayer Rules violation').startswith(MODERATION_NOTICE))
        accounts = Accounts(self.path)
        with self.assertRaises(LoginRejected):
            accounts.verify(b'second_login', b'second-test-password')
        self.cli('unban', 'second_login')
        self.assertEqual(accounts.verify(b'second_login', b'second-test-password'), 'second_login')

    def test_native_jail_uses_minutes_and_opens_private_notice(self):
        self.cli('grant', 'first_login')
        result = self.send(self.first, '//jail SecondPlayer m2 Two words')
        self.assertTrue(result.startswith(MODERATION_NOTICE))
        self.assertIn('120', result[len(MODERATION_NOTICE):-2].decode('utf-16-le'))
        self.assertEqual(self.prison()['remaining'], 120)
        self.assertFalse(self.hub.messages[self.second])
