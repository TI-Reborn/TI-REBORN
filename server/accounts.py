"""Local account administration. No registration UI or REST service."""
import argparse
from contextlib import closing
import getpass
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3

from .config import ServerConfig
from .auth_errors import LoginRejected
from tio.protocol.login import LoginFailureStatus

ITERATIONS = 600_000


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9_]{3,32}', value):
        raise ValueError('Login must use 3–32 lowercase ASCII letters, digits or underscores')
    return value


def password_bytes(value):
    raw = value.encode('ascii')
    if not 12 <= len(raw) <= 64 or any(c < 33 or c > 126 for c in raw):
        raise ValueError('Use 12–64 printable ASCII password characters, without spaces')
    return raw


class Accounts:
    def __init__(self, path):
        self.path = Path(path).resolve()

    def create(self, login, password, *, character=None, reset=False):
        login = identity(login)
        raw = password_bytes(password)
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac('sha256', raw, salt, ITERATIONS)
        name = None if character is None else character.encode('ascii')
        if name is not None and not re.fullmatch(rb'[A-Za-z][A-Za-z0-9]{2,15}', name):
            raise ValueError('Character must use 3–16 ASCII letters/digits, starting with a letter')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS accounts (login TEXT PRIMARY KEY, salt BLOB NOT NULL, digest BLOB NOT NULL, iterations INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS characters (account TEXT NOT NULL, slot INTEGER NOT NULL, name BLOB NOT NULL, name_key TEXT NOT NULL UNIQUE, request BLOB NOT NULL, PRIMARY KEY(account,slot))')
            db.execute('BEGIN IMMEDIATE')
            exists = db.execute('SELECT 1 FROM accounts WHERE login=?', (login,)).fetchone()
            if reset:
                if not exists:raise ValueError('Account does not exist; use create')
                db.execute('UPDATE accounts SET salt=?,digest=?,iterations=? WHERE login=?', (salt,digest,ITERATIONS,login))
            else:
                if exists:raise ValueError('Account exists; use reset-password')
                db.execute('INSERT INTO accounts VALUES (?,?,?,?)', (login,salt,digest,ITERATIONS))
            saved = db.execute('SELECT 1 FROM characters WHERE account=?', (login,)).fetchone()
            if not saved and name is not None:
                from tio.protocol.character_create import CharacterCreateRequest, encode_character_create
                packet = encode_character_create(CharacterCreateRequest(name,0,(0,0,0,0)))
                db.execute('INSERT INTO characters VALUES (?,?,?,?,?)', (login,1,name,name.decode().lower(),packet))
            elif saved and name is not None:
                raise ValueError('Existing character is preserved; omit --character')

    def verify(self, login, password):
        try:
            name = identity(login.decode('ascii'))
        except (ValueError, UnicodeError):
            name = ''
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)) as db:
            row = db.execute('SELECT salt,digest,iterations FROM accounts WHERE login=?', (name,)).fetchone()
        # Comparable hash work for an unknown login; never store plaintext.
        salt, expected, rounds = row if row else (bytes(16), bytes(32), ITERATIONS)
        actual = hashlib.pbkdf2_hmac('sha256', password, salt, rounds)
        if row and hmac.compare_digest(actual, expected):return name
        raise LoginRejected('credentials', LoginFailureStatus.INVALID_CREDENTIALS, 'Authentication failed')

    def check(self):
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='accounts'").fetchone():
                raise ValueError('Provision accounts with python -m server.accounts before enabling multi_account')
            if not db.execute('SELECT 1 FROM accounts LIMIT 1').fetchone():
                raise ValueError('No accounts provisioned')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('create','reset-password'))
    parser.add_argument('login')
    parser.add_argument('--character')
    parser.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[1]/'config/server.toml')
    args = parser.parse_args()
    first = getpass.getpass('Password (12–64 ASCII characters): ')
    if first != getpass.getpass('Repeat password: '):parser.error('Passwords differ')
    try:
        Accounts(ServerConfig.load(args.config).database).create(args.login, first,
            character=args.character, reset=args.command=='reset-password')
    except (ValueError, sqlite3.Error) as exc:parser.error(str(exc))
    print('Account credentials saved. Existing player data preserved.')


if __name__ == '__main__':main()
