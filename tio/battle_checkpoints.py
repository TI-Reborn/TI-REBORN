"""Atomic server snapshots and exclusive account bindings in the hosted SQLite."""
from contextlib import closing
import hashlib
import sqlite3
import time
from .db_transaction import connect


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS battle_checkpoints (
        match_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL,
        checksum TEXT NOT NULL,updated_at REAL NOT NULL,status TEXT NOT NULL,
        error_type TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS battle_checkpoint_members (
        account TEXT PRIMARY KEY,match_id TEXT NOT NULL,owner_id INTEGER NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS battle_checkpoint_matches ON battle_checkpoint_members(match_id)')


def initialise(path):
    with closing(connect(path)) as db,db:schema(db)


def save(db,match_id,payload,members,*,status='active',now=None):
    schema(db)
    if len(set(members))!=len(members):raise ValueError('Duplicate checkpoint account')
    for account in members:
        prior=db.execute('SELECT match_id FROM battle_checkpoint_members WHERE account=?',(account,)).fetchone()
        if prior and prior[0]!=match_id:raise ValueError('Account belongs to another durable battle')
    checksum=hashlib.sha256(payload.encode()).hexdigest()
    db.execute('''INSERT INTO battle_checkpoints VALUES (?,1,?,?,?,?,NULL)
        ON CONFLICT(match_id) DO UPDATE SET revision=revision+1,payload=excluded.payload,
        checksum=excluded.checksum,updated_at=excluded.updated_at,status=excluded.status,error_type=NULL''',
        (match_id,payload,checksum,time.time() if now is None else now,status))
    db.execute('DELETE FROM battle_checkpoint_members WHERE match_id=?',(match_id,))
    for account,owner in members.items():
        db.execute('INSERT INTO battle_checkpoint_members VALUES (?,?,?)',(account,match_id,owner))


def delete(db,match_id):
    db.execute('DELETE FROM battle_checkpoint_members WHERE match_id=?',(match_id,))
    db.execute('DELETE FROM battle_checkpoints WHERE match_id=?',(match_id,))


def read(path):
    with closing(connect(path)) as db:
        rows=db.execute('SELECT match_id,payload,checksum,status FROM battle_checkpoints ORDER BY match_id').fetchall()
        members=db.execute('SELECT account,match_id,owner_id FROM battle_checkpoint_members').fetchall()
        return [(m,p,c,s,{a:o for a,x,o in members if x==m}) for m,p,c,s in rows]


def quarantine(path,match_id,error):
    with closing(connect(path)) as db,db:
        db.execute('UPDATE battle_checkpoints SET status=?,error_type=? WHERE match_id=?',
                   ('quarantined',type(error).__name__,match_id))


def blocked(path,account):
    with closing(connect(path)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='battle_checkpoints'").fetchone():return False
        return bool(db.execute('''SELECT 1 FROM battle_checkpoint_members m JOIN battle_checkpoints c
            ON c.match_id=m.match_id WHERE m.account=? AND c.status='quarantined' ''',(account,)).fetchone())
