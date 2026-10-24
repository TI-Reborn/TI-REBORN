"""Additive character retirement; archived save owners are never reused.

No save rows are moved or deleted. Each recreated slot gets a new durable key,
so immutable receipts, wallets, inventory and history retain their old owner.
Legacy keys and mappings remain valid for accounting and anti-farming.
"""
import math
import sqlite3


def schema(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS character_revisions (
        login TEXT NOT NULL, slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 5),
        generation INTEGER NOT NULL CHECK(generation>=0), owner TEXT NOT NULL UNIQUE,
        deleted_at REAL, PRIMARY KEY(login,slot,generation))''')


def exists(db: sqlite3.Connection) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='character_revisions'").fetchone() is not None


def latest(db: sqlite3.Connection, login: str, slot: int) -> tuple | None:
    if not exists(db):
        return None
    return db.execute('''SELECT generation,owner,deleted_at FROM character_revisions
        WHERE login=? AND slot=? ORDER BY generation DESC LIMIT 1''', (login, slot)).fetchone()


def retired(db: sqlite3.Connection, owner: str) -> bool:
    return exists(db) and db.execute('''SELECT 1 FROM character_revisions
        WHERE owner=? AND deleted_at IS NOT NULL''', (owner,)).fetchone() is not None


def valid_key(login: str, slot: int, owner: str) -> bool:
    from .character_identity import alias, PREFIX
    original = alias(login, slot)
    if owner == original:
        return True
    prefix = f'{PREFIX}{login}:{slot}:'
    generation = owner.removeprefix(prefix)
    return (owner.startswith(prefix) and generation.isascii() and generation.isdigit()
            and generation == str(int(generation)) and 0 < int(generation) <= 0xffffffff)


def allocate(db: sqlite3.Connection, login: str, slot: int) -> str:
    from .character_identity import alias, PREFIX
    previous = latest(db, login, slot)
    if previous is None:
        return alias(login, slot)
    if previous[2] is None:
        raise ValueError('Character slot is occupied')
    generation = previous[0] + 1
    if generation > 0xffffffff:
        raise ValueError('Character generation exhausted')
    owner = f'{PREFIX}{login}:{slot}:{generation}'
    db.execute('INSERT INTO character_revisions VALUES (?,?,?,?,NULL)',
               (login, slot, generation, owner))
    return owner


def retire(db: sqlite3.Connection, login: str, slot: int, owner: str, now: float) -> None:
    if type(now) not in (float, int) or not math.isfinite(now) or now < 0:
        raise ValueError('Invalid character retirement time')
    previous = latest(db, login, slot)
    if previous is None:
        db.execute('INSERT INTO character_revisions VALUES (?,?,0,?,?)', (login, slot, owner, now))
    elif previous[1] == owner and previous[2] is None:
        db.execute('UPDATE character_revisions SET deleted_at=? WHERE owner=?', (now, owner))
    else:
        raise ValueError('Character selection changed')
