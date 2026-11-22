"""Private website account adapter. Never publish this listener through nginx."""
from collections import deque
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import threading
import time

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
from server.accounts import Accounts, ITERATIONS, identity, password_bytes

REQUEST_ID = re.compile(r'[A-Za-z0-9_-]{16,128}\Z')


class ApiError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status


class Budget:
    """Bound expensive work even with a compromised internal caller."""
    def __init__(self):
        self.lock = threading.Lock()
        self.attempts = deque()
        self.hash_slots = threading.BoundedSemaphore(2)

    def allow(self):
        now = time.monotonic()
        with self.lock:
            while self.attempts and now-self.attempts[0] >= 60:
                self.attempts.popleft()
            if len(self.attempts) >= 60:
                return False
            self.attempts.append(now)
            return True


class StatusReader:
    def __init__(self, path, probe, *, clock=time.time):
        self.path, self.probe, self.clock = Path(path), probe, clock
        self.lock = threading.Lock()
        self.last_probe, self.healthy = 0, False

    def read(self):
        now = self.clock()
        # Keep public status polling from consuming game connection budgets.
        with self.lock:
            if now-self.last_probe >= 10:
                self.healthy = self.probe()
                self.last_probe = now
            healthy = self.healthy
        result = dict(status='online' if healthy else 'offline', playersOnline=None,
                      maxPlayers=None, serverVersion='unknown', observedAt=None,
                      source='emulator')
        try:
            if self.path.stat().st_size > 4096:
                return result
            data = json.loads(self.path.read_text(encoding='utf-8'))
            stamp = data['observedAt']
            if type(stamp) not in (int, float) or not 0 <= now-stamp <= 20:
                return result
            if data.get('status') == 'offline':
                result['status'] = 'offline'
                return result
            players, capacity = data['playersOnline'], data['maxPlayers']
            if (not healthy or type(players) is not int or type(capacity) is not int
                    or not 0 <= players <= capacity <= 10000):
                return result
            version = data.get('serverVersion', 'unknown')
            if not isinstance(version, str) or len(version) > 80:
                return result
            result.update(playersOnline=players, maxPlayers=capacity,
                serverVersion=version,
                observedAt=datetime.fromtimestamp(stamp, timezone.utc).isoformat())
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            pass
        return result


def tcp_probe(address, port):
    try:
        with socket.create_connection((address, port), timeout=.3):
            return True
    except OSError:
        return False


def create_app(database, key, status_file, *, probe=lambda: False, clock=time.time):
    if not isinstance(key, str) or len(key) < 32:
        raise ValueError('Private API key must contain at least 32 characters')
    accounts = Accounts(database)
    accounts.check()  # Fail closed rather than initializing a wrong game database.
    with closing(sqlite3.connect(database, timeout=5)) as db, db:
        db.execute('''CREATE TABLE IF NOT EXISTS game_web_receipts (
            request_id TEXT PRIMARY KEY, operation TEXT NOT NULL,
            login TEXT NOT NULL, fingerprint BLOB NOT NULL, created REAL NOT NULL)''')
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=4096)
    budget, status = Budget(), StatusReader(status_file, probe, clock=clock)

    @app.before_request
    def authorize():
        supplied = request.headers.get('Authorization', '')
        expected = 'Bearer ' + key
        if len(supplied) > 1024 or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise ApiError('unauthorized', 401)
        if not budget.allow():
            raise ApiError('rate_limited', 429)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.errorhandler(ApiError)
    def api_error(error):
        return jsonify(error=error.code), error.status

    @app.errorhandler(sqlite3.Error)
    def database_error(_error):
        app.logger.warning('Private game account storage unavailable')
        return jsonify(error='service_unavailable'), 503

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error='invalid_request'), error.code

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.warning('Private game adapter unavailable: %s', type(error).__name__)
        return jsonify(error='service_unavailable'), 503

    def payload(fields):
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != set(fields):
            raise ApiError('invalid_request')
        if any(not isinstance(value, str) for value in data.values()):
            raise ApiError('invalid_request')
        try:
            identity(data['username'])
        except ValueError:
            raise ApiError('username_invalid') from None
        for field in ('password', 'currentPassword', 'newPassword'):
            if field in data:
                try:
                    password_bytes(data[field])
                except (ValueError, UnicodeError):
                    raise ApiError('password_invalid') from None
        if 'requestId' in data and not REQUEST_ID.fullmatch(data['requestId']):
            raise ApiError('invalid_request')
        return data

    def verify(username, password):
        try:
            return accounts.verify(username.encode('ascii'), password.encode('ascii'))
        except ValueError:
            raise ApiError('invalid_credentials', 401) from None

    def mutate(data, operation):
        fingerprint = hmac.digest(key.encode(),
            json.dumps(data, sort_keys=True, separators=(',', ':')).encode(), 'sha256')
        username, request_id = data['username'], data['requestId']

        def state(db):
            receipt = db.execute('SELECT operation,login,fingerprint FROM game_web_receipts WHERE request_id=?',
                                 (request_id,)).fetchone()
            current = db.execute('SELECT salt,digest,iterations FROM accounts WHERE login=?',
                                 (username,)).fetchone()
            provisioning = data.get('provisioningId')
            owner = db.execute('SELECT operation,login FROM game_web_receipts WHERE request_id=?',
                               (provisioning,)).fetchone() if provisioning else None
            return receipt, current, owner

        with closing(sqlite3.connect(database, timeout=5)) as db:
            for _ in range(3):
                with db:
                    db.execute('BEGIN')
                    observed = state(db)
                receipt, current, owner = observed
                if receipt:
                    if (receipt[0] != operation or receipt[1] != username
                            or not hmac.compare_digest(receipt[2], fingerprint)):
                        raise ApiError('request_id_conflict', 409)
                    if operation in ('password', 'recovery'):
                        # A receipt is valid only while its intended password is current.
                        if not current:
                            raise ApiError('invalid_credentials', 401)
                        actual = hashlib.pbkdf2_hmac('sha256', password_bytes(data['newPassword']),
                                                    current[0], current[2])
                        if not hmac.compare_digest(actual, current[1]):
                            raise ApiError('invalid_credentials', 401)
                else:
                    if operation == 'recovery':
                        if data['provisioningId']:
                            if current and owner != ('create', username):
                                raise ApiError('username_exists', 409)
                        elif not current:
                            raise ApiError('invalid_credentials', 401)
                    elif operation == 'create':
                        if current:
                            raise ApiError('username_exists', 409)
                    else:
                        salt, expected, rounds = current if current else (bytes(16), bytes(32), ITERATIONS)
                        actual = hashlib.pbkdf2_hmac('sha256', data['currentPassword'].encode('ascii'), salt, rounds)
                        if not current or not hmac.compare_digest(actual, expected):
                            raise ApiError('invalid_credentials', 401)
                    password = data['password'] if operation == 'create' else data['newPassword']
                    salt = secrets.token_bytes(16)
                    digest = hashlib.pbkdf2_hmac('sha256', password_bytes(password), salt, ITERATIONS)
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    # Hash outside the writer; revalidate every authorization input atomically.
                    if state(db) != observed:
                        continue
                    if receipt:
                        return True
                    if operation == 'create' or (operation == 'recovery' and not current):
                        db.execute('INSERT INTO accounts(login,salt,digest,iterations) VALUES (?,?,?,?)',
                                   (username, salt, digest, ITERATIONS))
                        if operation == 'recovery':
                            db.execute('INSERT INTO game_web_receipts VALUES (?,?,?,?,?)',
                                       (data['provisioningId'], 'create', username, fingerprint, time.time()))
                    else:
                        db.execute('UPDATE accounts SET salt=?,digest=?,iterations=? WHERE login=?',
                                   (salt, digest, ITERATIONS, username))
                    db.execute('INSERT INTO game_web_receipts VALUES (?,?,?,?,?)',
                               (request_id, operation, username, fingerprint, time.time()))
                return False
        raise ApiError('service_unavailable', 503)

    def hash_work(callback):
        if not budget.hash_slots.acquire(blocking=False):
            raise ApiError('rate_limited', 429)
        try:
            return callback()
        finally:
            budget.hash_slots.release()

    @app.post('/v1/accounts/create')
    def create():
        data = payload(('username', 'password', 'requestId'))
        replayed = hash_work(lambda: mutate(data, 'create'))
        return jsonify(username=data['username'], created=True, replayed=replayed), 200 if replayed else 201

    @app.post('/v1/accounts/find')
    def find():
        data = payload(('username',))
        with closing(sqlite3.connect(accounts.path.as_uri()+'?mode=ro', uri=True)) as db:
            exists = db.execute('SELECT 1 FROM accounts WHERE login=?', (data['username'],)).fetchone() is not None
        return jsonify(username=data['username'], exists=exists)

    @app.post('/v1/accounts/verify')
    def authenticate():
        data = payload(('username', 'password'))
        username = hash_work(lambda: verify(data['username'], data['password']))
        return jsonify(username=username, verified=True)

    @app.post('/v1/accounts/password')
    def password():
        data = payload(('username', 'currentPassword', 'newPassword', 'requestId'))
        replayed = hash_work(lambda: mutate(data, 'password'))
        return jsonify(username=data['username'], changed=True, replayed=replayed)

    @app.post('/v1/accounts/recovery')
    def recovery():
        data = payload(('username', 'newPassword', 'requestId', 'provisioningId'))
        if data['provisioningId'] and not REQUEST_ID.fullmatch(data['provisioningId']):
            raise ApiError('invalid_request')
        replayed = hash_work(lambda: mutate(data, 'recovery'))
        return jsonify(username=data['username'], changed=True, replayed=replayed)

    @app.get('/v1/status')
    def server_status():
        return jsonify(status.read())

    return app


def main():
    from waitress import serve
    from server.config import ServerConfig
    config = ServerConfig.load(os.environ.get('TIO_CONFIG', '/etc/tio-server/server.toml'))
    if not config.multi_account:
        raise ValueError('Website adapter requires multi_account=true')
    key = os.environ.get('GAME_SERVER_API_KEY')
    if key is None:
        key = Path(os.environ['TIO_GAME_API_KEY_FILE']).read_text(encoding='utf-8').strip()
    app = create_app(config.database, key,
        os.environ.get('TIO_WEB_STATUS_FILE', str(config.data_directory/'web-status.json')),
        probe=lambda: tcp_probe('127.0.0.1', config.game_port))
    serve(app, listen='127.0.0.1:8081', threads=2, connection_limit=16,
          channel_timeout=10, max_request_body_size=4096,
          clear_untrusted_proxy_headers=True)


if __name__ == '__main__':
    main()
