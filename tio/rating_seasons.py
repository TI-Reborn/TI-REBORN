"""UTC calendar seasons, sealed only after their durable matches close.

Monthly boundaries and the absence of monetary season rewards are emulator
policy, not a claim about the original Total Influence service.
"""
from datetime import datetime, timezone
import math
import re
import time


def boundary(now=None):
    now=time.time() if now is None else now
    if not isinstance(now,(int,float)) or isinstance(now,bool) or not math.isfinite(now):
        raise ValueError('Invalid season clock')
    try:current=datetime.fromtimestamp(now,timezone.utc)
    except (ValueError,OverflowError,OSError) as exc:raise ValueError('Invalid season clock') from exc
    first=current.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    last=first.replace(year=first.year+1,month=1) if first.month==12 else first.replace(month=first.month+1)
    return first.strftime('%Y-%m'),first.timestamp(),last.timestamp()


def validate(identity):
    if not isinstance(identity,str) or not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])',identity):
        raise ValueError('Сезон задаётся в формате ГГГГ-ММ')
    year,month=map(int,identity.split('-'))
    if not 1<=year<9999:raise ValueError('Invalid season year')
    return identity


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS team_rating_seasons (
        season_id TEXT PRIMARY KEY, starts_at REAL NOT NULL, ends_at REAL NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('open','closing','archived')),
        created_at REAL NOT NULL, archived_at REAL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS team_rating_archives (
        season_id TEXT NOT NULL, team_id TEXT NOT NULL, place INTEGER NOT NULL,
        mu REAL NOT NULL, sigma REAL NOT NULL, skill INTEGER NOT NULL,
        wins INTEGER NOT NULL, losses INTEGER NOT NULL, draws INTEGER NOT NULL,
        unrated INTEGER NOT NULL, archived_at REAL NOT NULL,
        PRIMARY KEY(season_id,team_id))''')


def close_finished(db,now=None):
    """Archive old seasons atomically; unfinished frozen matches retain them."""
    now=time.time() if now is None else now
    schema(db)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='team_ranked_matches'").fetchone():return ()
    closed=[]
    for (identity,) in db.execute("SELECT season_id FROM team_rating_seasons WHERE ends_at<=? AND state!='archived' ORDER BY starts_at",(now,)).fetchall():
        db.execute("UPDATE team_rating_seasons SET state='closing' WHERE season_id=?",(identity,))
        if db.execute("SELECT 1 FROM team_ranked_matches WHERE season_id=? AND state='pending' LIMIT 1",(identity,)).fetchone():continue
        rows=db.execute('''SELECT team_id,mu,sigma,skill,wins,losses,draws,unrated
            FROM team_rating_values WHERE scope=? AND wins+losses+draws>0
            ORDER BY skill DESC,team_id''',(identity,)).fetchall()
        place=0;previous=None
        for index,(team,mu,sigma,points,wins,losses,draws,unrated) in enumerate(rows,1):
            if points!=previous:place=index;previous=points
            db.execute('INSERT INTO team_rating_archives VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (identity,team,place,mu,sigma,points,wins,losses,draws,unrated,now))
        db.execute("UPDATE team_rating_seasons SET state='archived',archived_at=? WHERE season_id=?",(now,identity))
        closed.append(identity)
    return tuple(closed)


def current(db,now=None):
    """Lazy: no season or rating rows are created merely by server startup."""
    now=time.time() if now is None else now
    identity,first,last=boundary(now);schema(db)
    close_finished(db,now)
    prior=db.execute('SELECT starts_at,ends_at,state FROM team_rating_seasons WHERE season_id=?',(identity,)).fetchone()
    if prior is not None:
        if tuple(prior[:2])!=(first,last) or prior[2]!='open':raise ValueError('Season boundary conflict')
    else:db.execute("INSERT INTO team_rating_seasons VALUES (?,?,?,'open',?,NULL)",(identity,first,last,now))
    return identity,first,last


def listing(db,*,limit=12):
    if type(limit) is not int or not 1<=limit<=120:raise ValueError('Invalid season limit')
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='team_rating_seasons'").fetchone():return ()
    return tuple(dict(id=i,starts_at=start,ends_at=end,state=state,archived_at=archived)
        for i,start,end,state,archived in db.execute('''SELECT season_id,starts_at,ends_at,state,archived_at
            FROM team_rating_seasons ORDER BY starts_at DESC LIMIT ?''',(limit,)))
