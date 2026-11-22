"""Public profile text belongs to the authenticated character's durable owner."""
from pathlib import Path
import sqlite3

from .character_lifecycle import retired
from .db_transaction import transaction


def read(db: sqlite3.Connection, owner: str) -> tuple[str, str, str]:
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='player_profile_text'").fetchone():
        row = db.execute('SELECT biography,website,contact FROM player_profile_text WHERE owner=?',
                         (owner,)).fetchone()
        if row is not None:
            return row
    return '', '', ''


def save(path: str | Path, owner: str, name: bytes, texts: tuple[str, str, str]) -> None:
    with transaction(path) as db:
        if not db.execute('SELECT 1 FROM characters WHERE account=? AND name=?', (owner, name)).fetchone() or retired(db, owner):
            raise ValueError('Персонаж недоступен для редактирования')
        db.execute('''CREATE TABLE IF NOT EXISTS player_profile_text (
            owner TEXT PRIMARY KEY, biography TEXT NOT NULL, website TEXT NOT NULL, contact TEXT NOT NULL)''')
        db.execute('''INSERT INTO player_profile_text VALUES (?,?,?,?)
            ON CONFLICT(owner) DO UPDATE SET biography=excluded.biography,website=excluded.website,
            contact=excluded.contact WHERE biography!=excluded.biography OR website!=excluded.website
            OR contact!=excluded.contact''', (owner, *texts))
