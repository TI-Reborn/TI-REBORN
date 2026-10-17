"""Separate authenticated logins from durable character save owners.

Slot one deliberately keeps its historical login key. Additional owners cannot
be supplied as Accounts logins, and are reached only through an owned slot.
Mappings are created with the character, never by a startup data migration.
"""
from contextlib import closing

from .db_transaction import connect

MAX_CHARACTERS = 5
PREFIX = '@character:'


def initialise(db):
    db.execute('''CREATE TABLE IF NOT EXISTS character_identities (
        login TEXT NOT NULL, slot INTEGER NOT NULL CHECK(slot BETWEEN 2 AND 5),
        owner TEXT NOT NULL UNIQUE, PRIMARY KEY(login,slot))''')


def alias(login, slot):
    if not isinstance(login, str) or not login or login.startswith(PREFIX):
        raise ValueError('Authenticated account identity required')
    if type(slot) is not int or not 1 <= slot <= MAX_CHARACTERS:
        raise ValueError('Character slot must be 1..5')
    return login if slot == 1 else f'{PREFIX}{login}:{slot}'


def has_mappings(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='character_identities'").fetchone())


def owner_for_slot(db, login, slot):
    """An unowned or missing slot has no valid gameplay identity."""
    expected = alias(login, slot)
    if slot != 1:
        row = db.execute('SELECT owner FROM character_identities WHERE login=? AND slot=?',
                         (login, slot)).fetchone() if has_mappings(db) else None
        if row is None or row[0] != expected:
            raise ValueError('Character slot is not owned by this account')
    if not db.execute('SELECT 1 FROM characters WHERE account=? AND slot=1', (expected,)).fetchone():
        raise ValueError('Character slot is not owned by this account')
    return expected


def owners(path, login):
    """Return persisted owners for login fences, including the legacy first key."""
    alias(login, 1)
    with closing(connect(path)) as db:
        # Keep the old key even before first creation: existing wallets and
        # recovery records can precede the first character on older builds.
        result = [login]
        if has_mappings(db):
            for slot, owner in db.execute('SELECT slot,owner FROM character_identities WHERE login=? ORDER BY slot', (login,)):
                if owner != alias(login, slot):
                    raise ValueError('Corrupt character ownership mapping')
                result.append(owner)
    return tuple(result)


def auth_account(path, owner):
    """Canonical human identity for one-login and anti-farming decisions."""
    if not isinstance(owner, str) or not owner:
        raise ValueError('Character owner identity required')
    if not owner.startswith(PREFIX):
        return owner
    with closing(connect(path)) as db:
        row = db.execute('SELECT login,slot FROM character_identities WHERE owner=?',
                         (owner,)).fetchone() if has_mappings(db) else None
    if row is None or alias(row[0], row[1]) != owner:
        raise ValueError('Unknown character owner identity')
    return row[0]


def owner_for_name(db, name):
    """Return save owner for a public character name, without auth credentials."""
    try:
        key = name.decode('ascii').lower() if isinstance(name, bytes) else name.lower()
    except (AttributeError, UnicodeError):
        return None
    row = db.execute('SELECT account FROM characters WHERE name_key=?', (key,)).fetchone()
    return None if row is None else row[0]
