"""Keep QA and retired save owners out of public standings, including slots.

The random namespaces below are reserved by the hosted verification tools.
Other trusted fixtures can be explicitly marked in rating_exclusions(account).
Public queries never create or modify that table.
"""
import re
import sqlite3
from collections.abc import Callable, Iterable

QA_LOGIN = re.compile(r'(?:q(?:[a-z]|er)[0-9a-f]{8}[a-h]|webqa_[0-9a-f]{10}|qa_mail_[0-9a-f]{12}|uon[0-9a-f]{12}[ab])\Z')


def exclusion_filter(db: sqlite3.Connection) -> Callable[[str], bool]:
    """Read exclusions once for a standings query, never cache across requests."""
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    marked = {r[0] for r in db.execute('SELECT account FROM rating_exclusions')} if 'rating_exclusions' in tables else set()
    retired = {r[0] for r in db.execute('SELECT owner FROM character_revisions WHERE deleted_at IS NOT NULL')} if 'character_revisions' in tables else set()

    def hidden(owner: str) -> bool:
        login = owner.split(':')[1] if owner.startswith('@character:') else owner
        return owner in retired or owner in marked or login in marked or bool(QA_LOGIN.fullmatch(login))
    return hidden


def character_names(db: sqlite3.Connection, owners: Iterable[str]) -> dict[str, str]:
    """First-slot display names for one page; absent owners have no entry."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='characters'").fetchone():
        return {}
    names: dict[str, str] = {}
    accounts = sorted(set(owners))
    for start in range(0, len(accounts), 500):
        batch = accounts[start:start+500]
        for owner, raw in db.execute('SELECT account,name FROM characters WHERE account IN ('+
                                    ','.join('?' for _ in batch)+') ORDER BY slot', batch):
            names.setdefault(owner, bytes(raw).decode('cp1251', errors='replace'))
    return names


def excluded(db, owner, *, include_retired=True):
    from .character_lifecycle import retired
    if include_retired and retired(db, owner):
        return True
    login = owner.split(':')[1] if owner.startswith('@character:') else owner
    if QA_LOGIN.fullmatch(login):
        return True
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rating_exclusions'").fetchone():
        return bool(db.execute('SELECT 1 FROM rating_exclusions WHERE account IN (?,?)', (owner, login)).fetchone())
    return False
