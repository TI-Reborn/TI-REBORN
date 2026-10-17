"""Private adapter regressions with disposable game data, never hosted saves."""
from contextlib import closing
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from registration.game_bridge import create_app, tcp_probe
from server.accounts import Accounts
from server.web_status import StatusPublisher

KEY = 'unit-test-private-key-with-more-than-32-characters'
PASSWORD = 'test-account-password-123'
CHANGED = 'updated-account-password-456'


class GameBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name)/'game.sqlite3'
        self.status_file = Path(self.temp.name)/'web-status.json'
        self.accounts = Accounts(self.database)
        self.accounts.create('existing', PASSWORD, character='Existing')
        self.now = 1000
        self.probe_calls = 0
        self.healthy = True
        def probe():
            self.probe_calls += 1
            return self.healthy
        self.app = create_app(self.database, KEY, self.status_file,
                              probe=probe, clock=lambda: self.now)
        self.client = self.app.test_client()
        self.headers = {'Authorization': 'Bearer ' + KEY}

    def post(self, endpoint, data, headers=None):
        return self.client.post('/v1/accounts/'+endpoint, json=data,
                                headers=self.headers if headers is None else headers)

    def create(self, request_id='create-request-00001', **fields):
        return self.post('create', dict(username='new_player', password=PASSWORD,
                                      requestId=request_id, **fields))

    def test_create_is_game_compatible_and_does_not_create_character(self):
        response = self.create()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json, dict(username='new_player', created=True, replayed=False))
        self.assertEqual(self.accounts.verify(b'new_player', PASSWORD.encode()), 'new_player')
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM characters WHERE account=?',
                                        ('new_player',)).fetchone()[0], 0)
            row = db.execute('SELECT salt,digest,iterations FROM accounts WHERE login=?',
                             ('new_player',)).fetchone()
            self.assertEqual((len(row[0]), len(row[1]), row[2]), (16, 32, 600000))
            self.assertNotIn(PASSWORD.encode(), self.database.read_bytes())

    def test_create_replay_is_atomic_and_conflict_does_not_change_password(self):
        self.assertEqual(self.create().status_code, 201)
        response = self.create()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['replayed'])
        response = self.post('create', dict(username='new_player', password=CHANGED,
                                           requestId='create-request-00001'))
        self.assertEqual((response.status_code, response.json['error']), (409, 'request_id_conflict'))
        self.assertEqual(self.accounts.verify(b'new_player', PASSWORD.encode()), 'new_player')
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM game_web_receipts').fetchone()[0], 1)

    def test_duplicate_username_is_not_claimed_and_leaves_no_receipt(self):
        response = self.post('create', dict(username='existing', password=CHANGED,
                                           requestId='duplicate-request-00001'))
        self.assertEqual((response.status_code, response.json['error']), (409, 'username_exists'))
        self.assertEqual(self.accounts.verify(b'existing', PASSWORD.encode()), 'existing')
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM game_web_receipts').fetchone()[0], 0)

    def test_receipt_storage_failure_rolls_back_game_account_creation(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON game_web_receipts BEGIN SELECT RAISE(ABORT, 'receipt unavailable'); END")
        self.assertEqual(self.create().status_code, 503)
        self.assertFalse(self.post('find', {'username':'new_player'}).json['exists'])
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('DROP TRIGGER reject_receipt')
        self.assertEqual(self.create().status_code, 201)

    def test_find_and_verify_expose_no_credential_or_player_fields(self):
        self.assertEqual(self.post('find', {'username':'existing'}).json,
                         {'username':'existing', 'exists':True})
        self.assertFalse(self.post('find', {'username':'unknown'}).json['exists'])
        response = self.post('verify', {'username':'existing', 'password':PASSWORD})
        self.assertEqual(response.json, {'username':'existing', 'verified':True})
        for username in ('existing', 'unknown'):
            response = self.post('verify', {'username':username, 'password':CHANGED})
            self.assertEqual((response.status_code, response.json),
                             (401, {'error':'invalid_credentials'}))

    def test_password_change_replay_preserves_existing_game_character(self):
        with closing(sqlite3.connect(self.database)) as db:
            before = db.execute('SELECT * FROM characters WHERE account=?', ('existing',)).fetchall()
        data = dict(username='existing', currentPassword=PASSWORD, newPassword=CHANGED,
                    requestId='password-request-00001')
        response = self.post('password', data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, dict(username='existing', changed=True, replayed=False))
        self.assertTrue(self.post('password', data).json['replayed'])
        with self.assertRaises(ValueError):
            self.accounts.verify(b'existing', PASSWORD.encode())
        self.assertEqual(self.accounts.verify(b'existing', CHANGED.encode()), 'existing')
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT * FROM characters WHERE account=?', ('existing',)).fetchall(), before)
        data['requestId'] = 'password-request-00002'
        self.assertEqual(self.post('password', data).json['error'], 'invalid_credentials')

    def test_legacy_cli_reset_is_authoritative(self):
        self.accounts.create('existing', CHANGED, reset=True)
        self.assertEqual(self.post('verify', {'username':'existing', 'password':PASSWORD}).status_code, 401)
        self.assertTrue(self.post('verify', {'username':'existing', 'password':CHANGED}).json['verified'])

    def test_old_password_receipt_cannot_claim_success_after_an_intervening_change(self):
        first = dict(username='existing', currentPassword=PASSWORD, newPassword=CHANGED,
                     requestId='password-replay-first-001')
        self.assertEqual(self.post('password', first).status_code, 200)
        self.assertTrue(self.post('password', first).json['replayed'])
        third = 'third-account-password-789'
        second = dict(username='existing', currentPassword=CHANGED, newPassword=third,
                      requestId='password-replay-second-001')
        self.assertEqual(self.post('password', second).status_code, 200)
        stale = self.post('password', first)
        self.assertEqual((stale.status_code, stale.json['error']), (401, 'invalid_credentials'))
        self.assertEqual(self.accounts.verify(b'existing', third.encode()), 'existing')
        with self.assertRaises(ValueError):
            self.accounts.verify(b'existing', CHANGED.encode())

    def test_secret_required_on_every_endpoint_and_cors_not_enabled(self):
        for endpoint in ('create', 'find', 'verify', 'password'):
            response = self.post(endpoint, {}, headers={})
            self.assertEqual((response.status_code, response.json), (401, {'error':'unauthorized'}))
            self.assertNotIn('Access-Control-Allow-Origin', response.headers)
        self.assertEqual(self.client.get('/v1/status').status_code, 401)
        self.assertEqual(self.post('find', {'username':'existing'},
            headers={'Authorization':'Bearer '+KEY+'wrong'}).status_code, 401)

    def test_validation_rejects_bad_inputs_and_body_overflow(self):
        samples = [
            ({'username':'UPPER', 'password':PASSWORD, 'requestId':'validation-request-01'}, 'username_invalid'),
            ({'username':'игрок', 'password':PASSWORD, 'requestId':'validation-request-01'}, 'username_invalid'),
            ({'username':'new_player', 'password':'short', 'requestId':'validation-request-01'}, 'password_invalid'),
            ({'username':'new_player', 'password':'пароль-длинный-123', 'requestId':'validation-request-01'}, 'password_invalid'),
            ({'username':'new_player', 'password':PASSWORD, 'requestId':'short'}, 'invalid_request'),
            ({'username':'new_player', 'password':PASSWORD, 'requestId':'validation-request-01', 'reset':True}, 'invalid_request'),
        ]
        for data, code in samples:
            self.assertEqual(self.post('create', data).json['error'], code)
        response = self.client.post('/v1/accounts/create', data=b'x'*5000,
                                    content_type='application/json', headers=self.headers)
        self.assertEqual(response.status_code, 413)

    def test_rate_budget_is_enforced_for_authorized_requests(self):
        for _ in range(60):
            self.assertEqual(self.post('find', {'username':'existing'}).status_code, 200)
        response = self.post('find', {'username':'existing'})
        self.assertEqual((response.status_code, response.json['error']), (429, 'rate_limited'))

    def write_status(self, **changes):
        data = dict(status='online', playersOnline=2, maxPlayers=16,
                    observedAt=self.now, serverVersion='test-release')
        data.update(changes)
        self.status_file.write_text(json.dumps(data), encoding='utf-8')

    def status(self):
        return self.client.get('/v1/status', headers=self.headers).json

    def test_fresh_runtime_population_and_cached_tcp_probe(self):
        self.write_status()
        result = self.status()
        self.assertEqual((result['status'], result['playersOnline'], result['maxPlayers']), ('online', 2, 16))
        self.assertEqual(result['serverVersion'], 'test-release')
        self.status()
        self.assertEqual(self.probe_calls, 1)

    def test_stale_missing_corrupt_or_unhealthy_status_never_invents_zero(self):
        self.assertIsNone(self.status()['playersOnline'])
        self.write_status(observedAt=self.now-21)
        self.assertIsNone(self.status()['playersOnline'])
        self.status_file.write_text('corrupt', encoding='utf-8')
        self.assertIsNone(self.status()['playersOnline'])
        self.write_status()
        self.healthy = False
        self.now += 10
        self.assertEqual((self.status()['status'], self.status()['playersOnline']), ('offline', None))

    def test_shutdown_status_is_offline_and_runtime_heartbeat_is_aggregate_only(self):
        with patch.dict('os.environ', {'TIO_WEB_STATUS_FILE':str(self.status_file), 'TIO_GAME_VERSION':'test-v1'}):
            publisher = StatusPublisher(self.status_file)
            publisher.publish((2, 16))
            snapshot = json.loads(self.status_file.read_text(encoding='utf-8'))
            self.assertEqual(set(snapshot), {'status','playersOnline','maxPlayers','serverVersion','observedAt'})
            self.assertEqual(snapshot['playersOnline'], 2)
            publisher.publish(status='offline')
            self.now = time.time()
            self.assertEqual((self.status()['status'], self.status()['playersOnline']), ('offline', None))

    def test_tcp_health_probe_checks_a_real_listener(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            self.assertTrue(tcp_probe('127.0.0.1', port))
        self.assertFalse(tcp_probe('127.0.0.1', port))

    def test_snapshot_write_failure_does_not_stop_gameplay_or_leave_temp_file(self):
        with patch.dict('os.environ', {'TIO_WEB_STATUS_FILE':str(self.status_file)}):
            publisher = StatusPublisher(self.status_file)
            with patch('server.web_status.os.replace', side_effect=OSError('test failure')):
                publisher.publish((2, 16))
            self.assertEqual(list(Path(self.temp.name).glob('.web-status-*')), [])

    def test_uninitialized_database_and_short_secret_fail_closed(self):
        with self.assertRaises(ValueError):
            create_app(self.database, 'short', self.status_file)
        blank = Path(self.temp.name)/'blank.sqlite3'
        sqlite3.connect(blank).close()
        with self.assertRaises(ValueError):
            create_app(blank, KEY, self.status_file)


if __name__ == '__main__':
    unittest.main()
