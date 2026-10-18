"""Login-wide TrueSkill daily token and idempotent battle admission receipt.

Original russian.lng m1060: one daily token only while balance is empty.
86400-second rollover and +10/+25 loan kits are emulator policies.
Purchase/subscription offers stay empty until their original prices are known.
"""
import time
import struct
from .character_identity import auth_account


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS ranked_tokens(login TEXT PRIMARY KEY,balance INTEGER NOT NULL CHECK(balance>=0),granted_at REAL NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS ranked_token_matches(match_id TEXT NOT NULL,login TEXT NOT NULL,state TEXT NOT NULL,PRIMARY KEY(match_id,login))')


def status(db,account,*,now=None):
    schema(db);now=time.time() if now is None else now
    path=db.execute('PRAGMA database_list').fetchone()[2];login=auth_account(path,account)
    row=db.execute('SELECT balance,granted_at FROM ranked_tokens WHERE login=?',(login,)).fetchone()
    if row is None:
        db.execute('INSERT INTO ranked_tokens VALUES (?,1,?)',(login,now));balance=1
    else:
        balance,stamp=row
        if not balance and now>=stamp+86400:
            db.execute('UPDATE ranked_tokens SET balance=1,granted_at=? WHERE login=?',(now,login));balance=1
    return login,balance


def packets(db,account):
    _,balance=status(db,account)
    # Native 953fa4: count:u32, remaining subscription duration:u64.
    # Native 9540d4: four arrays of (u32,u32), no unknown-price offers.
    return b'\xc6\x24'+struct.pack('<IQ',balance,0),b'\xc6\x28'+bytes(16)


def consume(db,match_id,accounts):
    schema(db)
    path=db.execute('PRAGMA database_list').fetchone()[2]
    for account in accounts:
        login=auth_account(path,account)
        prior=db.execute('SELECT state FROM ranked_token_matches WHERE match_id=? AND login=?',(match_id,login)).fetchone()
        if prior:
            if prior[0]!='spent':raise ValueError('TrueSkill token admission was refunded')
            continue
        login,balance=status(db,account)
        if not balance:raise ValueError('Нет жетонов для бонусного набора TrueSkill')
        db.execute('UPDATE ranked_tokens SET balance=balance-1 WHERE login=?',(login,))
        db.execute('INSERT INTO ranked_token_matches VALUES (?,?,?)',(match_id,login,'spent'))


def refund(db,match_id):
    schema(db)
    for login, in db.execute("SELECT login FROM ranked_token_matches WHERE match_id=? AND state='spent'",(match_id,)).fetchall():
        db.execute('UPDATE ranked_tokens SET balance=balance+1 WHERE login=?',(login,))
        db.execute("UPDATE ranked_token_matches SET state='refunded' WHERE match_id=? AND login=?",(match_id,login))
