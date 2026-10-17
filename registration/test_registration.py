from contextlib import closing
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest

from server.accounts import Accounts
from registration.app import create_app


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name)/'reservation.sqlite3'
        self.accounts = Accounts(self.db)
        self.accounts.create('existing', 'existing-password-123', character='Existing')
        self.app = create_app(self.db, 's'*40, 'https://185.184.42.88')
        self.client = self.app.test_client()

    def get_token(self):
        response = self.client.get('/register/?lang=ru', base_url='https://185.184.42.88')
        self.assertEqual(response.status_code, 200)
        return re.search(rb'name="csrf" value="([^"]+)"', response.data)[1].decode()

    def submit(self, **changes):
        fields = dict(csrf=self.get_token(), login='new_player', character='NewPlayer',
                      password='different-password-123', confirm='different-password-123')
        fields.update(changes)
        return self.client.post('/register/', data=fields, base_url='https://185.184.42.88',
                                headers={'Origin':'https://185.184.42.88'})

    def test_registration_allows_game_authentication(self):
        self.assertEqual(self.submit().status_code, 201)
        self.assertEqual(self.accounts.verify(b'new_player', b'different-password-123'), 'new_player')
        self.assertEqual(self.accounts.verify(b'existing', b'existing-password-123'), 'existing')
        with closing(sqlite3.connect(self.db)) as db:
            self.assertIsNone(db.execute('SELECT name FROM characters WHERE account=?', ('new_player',)).fetchone())
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_form_policy_preserves_origin_and_null_origin_is_rejected(self):
        response = self.client.get('/register/', base_url='https://185.184.42.88')
        self.assertEqual(response.headers['Referrer-Policy'], 'same-origin')
        self.assertEqual(self.client.head('/register/', base_url='https://185.184.42.88').status_code, 200)
        token = re.search(rb'name="csrf" value="([^"]+)"', response.data)[1].decode()
        response = self.client.post('/register/', data={'csrf': token},
            base_url='https://185.184.42.88', headers={'Origin': 'null'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.submit().status_code, 201)

    def test_cannot_reset_or_claim_existing_accounts(self):
        self.assertEqual(self.submit(login='existing').status_code, 400)
        self.assertEqual(self.submit(login='existing',character='Existing').status_code, 400)
        self.assertEqual(self.accounts.verify(b'existing', b'existing-password-123'), 'existing')
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM accounts').fetchone()[0], 1)

    def test_csrf_replay_origin_and_http_rejected(self):
        token = self.get_token()
        self.assertEqual(self.client.post('/register/', data={'csrf':token}, base_url='https://185.184.42.88', headers={'Origin':'https://evil.example'}).status_code, 403)
        self.assertEqual(self.submit(csrf='wrong').status_code, 403)
        self.assertEqual(self.client.get('/register/', base_url='http://185.184.42.88').status_code, 400)
        self.assertEqual(self.client.get('/register/', base_url='https://evil.example').status_code, 400)
        self.assertEqual(self.submit().status_code, 201)
        self.assertEqual(self.client.post('/register/', data={'csrf':token}, base_url='https://185.184.42.88', headers={'Origin':'https://185.184.42.88'}).status_code, 403)

    def test_invalid_input_limits_and_body_limit(self):
        self.assertEqual(self.submit(password='short', confirm='short').status_code, 400)
        self.assertEqual(self.submit(confirm='mismatch').status_code, 400)
        self.assertEqual(self.submit(login="x';DROP TABLE accounts;--").status_code, 400)
        self.assertEqual(self.submit(login='BADLOGIN').status_code, 400)
        self.assertEqual(self.submit(login='Ник').status_code, 400)
        self.assertEqual(self.submit().status_code, 429)
        self.assertEqual(self.client.post('/register/', data=b'x'*5000, base_url='https://185.184.42.88', headers={'Origin':'https://185.184.42.88'}).status_code, 413)


if __name__ == '__main__':unittest.main()
