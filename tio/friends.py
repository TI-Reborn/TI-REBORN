"""Durable mutual character friendships; public names are resolved on every read."""
from contextlib import closing
from .db_transaction import transaction,connect
from .character_identity import owner_for_name

LIMIT=100

def initialise(db):
    db.execute('CREATE TABLE IF NOT EXISTS friends(account TEXT NOT NULL,friend TEXT NOT NULL,CHECK(account!=friend),PRIMARY KEY(account,friend))')

def resolve(db,name):
    owner=owner_for_name(db,name)
    if owner is None:raise ValueError('Персонаж не найден')
    return owner

def members(path,owner):
    with closing(connect(path)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='friends'").fetchone():return ()
        return tuple(db.execute('SELECT c.account,c.name,c.rowid FROM friends f JOIN characters c ON c.account=f.friend WHERE f.account=? ORDER BY c.name_key',(owner,)))

def linked(path,owner,other):
    return any(r[0]==other for r in members(path,owner))

def accept(path,owner,other):
    with transaction(path) as db:
        initialise(db)
        if owner==other:raise ValueError('Нельзя добавить себя в друзья')
        for name in (owner,other):
            if not db.execute('SELECT 1 FROM characters WHERE account=?',(name,)).fetchone():raise ValueError('Персонаж не найден')
        if db.execute('SELECT 1 FROM friends WHERE account=? AND friend=?',(owner,other)).fetchone():return
        for name in (owner,other):
            if db.execute('SELECT count(*) FROM friends WHERE account=?',(name,)).fetchone()[0]>=LIMIT:raise ValueError('Список друзей заполнен')
        db.executemany('INSERT OR IGNORE INTO friends VALUES (?,?)',((owner,other),(other,owner)))

def remove(path,owner,other):
    with transaction(path) as db:
        initialise(db)
        db.execute('DELETE FROM friends WHERE (account=? AND friend=?) OR (account=? AND friend=?)',(owner,other,other,owner))
