"""Persistent authoritative battle totals and per-soldier legacy rating.

Called inside the reward transaction, so retries never count a battle twice.
TrueSkill is intentionally separate: Reservation is not a league battle.
"""

from .db_transaction import connect
from contextlib import closing
import sqlite3
import time


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS player_battle_statistics (
        account TEXT NOT NULL, match_id TEXT NOT NULL, result INTEGER NOT NULL,
        kills INTEGER NOT NULL, deaths INTEGER NOT NULL, damage_dealt INTEGER NOT NULL,
        damage_received INTEGER NOT NULL, settled_at REAL NOT NULL,
        PRIMARY KEY(account,match_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS soldier_ratings (
        account TEXT NOT NULL, pet_id INTEGER NOT NULL, rating INTEGER NOT NULL,
        PRIMARY KEY(account,pet_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS player_online (
        account TEXT PRIMARY KEY, seconds REAL NOT NULL DEFAULT 0)''')
    db.execute('''CREATE TABLE IF NOT EXISTS player_statistics_baselines (
        account TEXT PRIMARY KEY, kills INTEGER NOT NULL)''')


def settle_statistics(db, account, match_id, result, report, *, now=None):
    totals, soldiers = report
    values = tuple(totals.get(k,0) for k in ('kills','losses','damage_dealt','damage_received'))
    if any(type(n) is not int or n < 0 for n in values):
        raise ValueError('Invalid battle statistics')
    if any(type(i) is not int or len(v)!=2 or any(type(n) is not int or n<0 for n in v)
           for i,v in soldiers.items()):raise ValueError('Invalid soldier statistics')
    schema(db)
    historical=0
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='achievement_counters'").fetchone():
        row=db.execute("SELECT value FROM achievement_counters WHERE account=? AND metric='kills'",(account,)).fetchone()
        if row:historical=row[0]
    db.execute('INSERT OR IGNORE INTO player_statistics_baselines VALUES (?,?)',(account,historical))
    if db.execute('SELECT 1 FROM player_battle_statistics WHERE account=? AND match_id=?',
                  (account,match_id)).fetchone():return
    for identity,(kills,deaths) in soldiers.items():
        if not db.execute('SELECT 1 FROM owned_pets WHERE account=? AND pet_id=?',
                          (account,identity)).fetchone():raise ValueError('Unowned statistics participant')
        db.execute('''INSERT INTO soldier_ratings VALUES (?,?,?)
            ON CONFLICT(account,pet_id) DO UPDATE SET rating=rating+excluded.rating''',
            (account,identity,kills-deaths))
    db.execute('INSERT INTO player_battle_statistics VALUES (?,?,?,?,?,?,?,?)',
               (account,match_id,result,*values,time.time() if now is None else now))


def battle_report(combat, owner):
    owners=getattr(combat,'actor_owners',None)
    if owners is None:owners={i:a.owner_id for i,a in combat.field._actors.items()}
    soldiers={combat.storage_ids.get(i,i):[0,0]
              for i,actor_owner in owners.items() if actor_owner==owner and i in combat.persistence}
    for killer,victim in combat.rank_kills:
        # Bot and mutant kills cannot create a public PvP rating. Both ends
        # must have real, distinct persistent accounts on the shared field.
        if killer not in combat.persistence or victim not in combat.persistence:continue
        if combat.persistence[killer]==combat.persistence[victim]:continue
        identity=combat.storage_ids.get(killer,killer)
        if owners[killer]==owner:soldiers[identity][0]+=1
        if owners[victim]==owner:soldiers[combat.storage_ids.get(victim,victim)][1]+=1
    return dict(combat.statistics.get(owner,{})),soldiers


def save_online(path, account, seconds):
    if seconds<0:raise ValueError('Invalid online duration')
    with closing(connect(path)) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS player_online (account TEXT PRIMARY KEY, seconds REAL NOT NULL DEFAULT 0)')
        db.execute('''INSERT INTO player_online VALUES (?,?)
            ON CONFLICT(account) DO UPDATE SET seconds=seconds+excluded.seconds''',(account,seconds))
