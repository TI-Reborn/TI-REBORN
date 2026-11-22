"""Persist player administration grants against authenticated game logins."""
import sqlite3


def _has_roles(db: sqlite3.Connection) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='game_admins'"
    ).fetchone() is not None


def is_admin(db: sqlite3.Connection, login: str) -> bool:
    return _has_roles(db) and db.execute(
        'SELECT 1 FROM game_admins WHERE login=?', (login,)
    ).fetchone() is not None


def list_admins(db: sqlite3.Connection) -> tuple[str, ...]:
    if not _has_roles(db):
        return ()
    return tuple(login for (login,) in db.execute('SELECT login FROM game_admins ORDER BY login'))


def set_admin(db: sqlite3.Connection, login: str, *, enabled: bool) -> bool:
    """Change an existing login's grant inside the caller's write transaction."""
    if db.execute('SELECT 1 FROM accounts WHERE login=?', (login,)).fetchone() is None:
        raise ValueError('Game account does not exist')
    if not enabled:
        return _has_roles(db) and db.execute(
            'DELETE FROM game_admins WHERE login=?', (login,)
        ).rowcount == 1
    db.execute('''CREATE TABLE IF NOT EXISTS game_admins (
        login TEXT NOT NULL PRIMARY KEY REFERENCES accounts(login))''')
    # Legacy tools can delete accounts through connections without SQLite foreign keys.
    db.execute('''CREATE TRIGGER IF NOT EXISTS game_admins_account_deleted
        AFTER DELETE ON accounts BEGIN DELETE FROM game_admins WHERE login=OLD.login; END''')
    return db.execute(
        'INSERT INTO game_admins(login) VALUES (?) ON CONFLICT(login) DO NOTHING', (login,)
    ).rowcount == 1


def active_sanction(db: sqlite3.Connection, login: str, kind: str, *, now: int) -> bool:
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='game_sanctions'"
    ).fetchone() is None:
        return False
    return db.execute(
        'SELECT 1 FROM game_sanctions WHERE login=? AND kind=? AND (expires IS NULL OR expires>?)',
        (login, kind, now),
    ).fetchone() is not None


def record_sanction(
    db: sqlite3.Connection, login: str, kind: str, reason: str, expires: int | None
) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS game_sanctions (
        login TEXT NOT NULL REFERENCES accounts(login),
        kind TEXT NOT NULL CHECK(kind IN ('ban','mute')), reason TEXT NOT NULL, expires INTEGER,
        PRIMARY KEY (login,kind))''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS game_sanctions_account_deleted
        AFTER DELETE ON accounts BEGIN DELETE FROM game_sanctions WHERE login=OLD.login; END''')
    db.execute('''INSERT INTO game_sanctions(login,kind,reason,expires) VALUES (?,?,?,?)
        ON CONFLICT(login,kind) DO UPDATE SET reason=excluded.reason,
        expires=CASE WHEN excluded.expires IS NULL THEN NULL ELSE max(game_sanctions.expires,excluded.expires) END
        WHERE game_sanctions.reason<>excluded.reason''', (login, kind, reason, expires))


def lift_sanction(db: sqlite3.Connection, login: str, kind: str) -> bool:
    if db.execute('SELECT 1 FROM accounts WHERE login=?', (login,)).fetchone() is None:
        raise ValueError('Game account does not exist')
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='game_sanctions'"
    ).fetchone() is None:
        return False
    return db.execute('DELETE FROM game_sanctions WHERE login=? AND kind=?', (login, kind)).rowcount == 1
