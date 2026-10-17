"""Durable rating of fixed two-account squads, separate from duel ratings.

All four accounts, lifetime and seasonal ratings and their immutable match
receipt update inside the caller's existing battle reward transaction. The
opposing-pair limit uses authenticated accounts, including character aliases.
"""
from contextlib import closing
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import time

from .db_transaction import connect
from . import ranked, rating_seasons

ALL_TIME='all'


@lru_cache(maxsize=1)
def policy():
    row=json.loads((Path(__file__).resolve().parents[1]/'config/rating_seasons.json').read_text(encoding='utf-8'))
    if (row.get('version')!=1 or row.get('team_players')!=2 or
        not 1<=row.get('minimum_level',0)<=row.get('maximum_level',0)<=20 or
        not 1<=row.get('maximum_soldiers',0)<=3 or
        type(row.get('repeat_window_seconds')) is not int or not 1<=row['repeat_window_seconds']<=604800 or
        type(row.get('maximum_rated_opposing_pairs')) is not int or not 1<=row['maximum_rated_opposing_pairs']<=100):
        raise ValueError('Invalid team season policy')
    return row


def payload(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def members(accounts):
    values=tuple(accounts)
    if (len(values)!=2 or any(not isinstance(a,str) or not a or len(a)>128 or '\0' in a for a in values)
        or len(set(values))!=2):
        raise ValueError('Команда рейтинга требует два разных аккаунта')
    return tuple(sorted(values))


def identity(accounts):return hashlib.sha256(payload(members(accounts)).encode()).hexdigest()


def auth_owners(db,accounts):
    from .character_identity import auth_account
    # The root helper takes the authoritative database path, not a client login.
    path=db.execute('PRAGMA database_list').fetchone()[2]
    return tuple(auth_account(path,a) for a in accounts)


def schema(db):
    rating_seasons.schema(db)
    db.execute('''CREATE TABLE IF NOT EXISTS team_rating_teams (
        team_id TEXT PRIMARY KEY, members TEXT NOT NULL UNIQUE)''')
    db.execute('''CREATE TABLE IF NOT EXISTS team_rating_values (
        scope TEXT NOT NULL, team_id TEXT NOT NULL, mu REAL NOT NULL,
        sigma REAL NOT NULL, skill INTEGER NOT NULL, wins INTEGER NOT NULL,
        losses INTEGER NOT NULL, draws INTEGER NOT NULL, unrated INTEGER NOT NULL,
        revision INTEGER NOT NULL, updated_at REAL NOT NULL,
        PRIMARY KEY(scope,team_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS team_ranked_matches (
        match_id TEXT PRIMARY KEY, season_id TEXT NOT NULL,
        first_team TEXT NOT NULL, second_team TEXT NOT NULL,
        frozen TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','settled','void')),
        result TEXT, started_at REAL NOT NULL, finished_at REAL, rated INTEGER)''')
    db.execute('''CREATE TABLE IF NOT EXISTS team_ranked_opponents (
        match_id TEXT NOT NULL, first_account TEXT NOT NULL, second_account TEXT NOT NULL,
        started_at REAL NOT NULL, rated INTEGER NOT NULL,
        PRIMARY KEY(match_id,first_account,second_account))''')
    db.execute('CREATE INDEX IF NOT EXISTS team_ranked_pair_history ON team_ranked_opponents(first_account,second_account,started_at)')


def snapshot(db,team,scope=ALL_TIME):
    row=db.execute('''SELECT mu,sigma,skill,wins,losses,draws,unrated,revision
        FROM team_rating_values WHERE scope=? AND team_id=?''',(scope,team)).fetchone()
    values=row if row else (ranked.MU,ranked.SIGMA,0,0,0,0,0,0)
    return dict(zip(('mu','sigma','skill','wins','losses','draws','unrated','revision'),values))


def admit(db,match_id,teams,*,now=None):
    """Freeze fixed squads and both rating scopes when the real match is born."""
    now=time.time() if now is None else now
    if not isinstance(match_id,str) or not 1<=len(match_id)<=128:raise ValueError('Invalid team match identity')
    if len(teams)!=2:raise ValueError('Team rating requires two teams')
    teams=tuple(members(team) for team in teams);accounts=tuple(a for team in teams for a in team)
    if len(set(accounts))!=4:raise ValueError('Repeated team account')
    # Schema creation alone adds no rows; the first eligible live battle creates
    # a season. Wallet existence is the existing character ownership boundary.
    for account in accounts:
        if not db.execute('SELECT 1 FROM wallets WHERE account=?',(account,)).fetchone():raise ValueError('Team rating account missing')
    auth=auth_owners(db,accounts)
    if len(set(auth))!=4:raise ValueError('Рейтинговый бой требует четыре разных игровых аккаунта')
    schema(db)
    prior=db.execute('SELECT frozen,state FROM team_ranked_matches WHERE match_id=?',(match_id,)).fetchone()
    if prior:
        frozen=json.loads(prior[0])
        if frozen['teams']!=[list(team) for team in teams]:raise ValueError('Conflicting admitted team match')
        if prior[1]!='pending':raise ValueError('Team match already closed')
        return frozen
    season,first,last=rating_seasons.current(db,now)
    ids=tuple(identity(team) for team in teams)
    frozen=dict(version=1,match_id=match_id,season=season,starts_at=first,ends_at=last,
                admitted_at=now,teams=teams,team_ids=ids,auth_teams=(auth[:2],auth[2:]),
                snapshots={scope:[snapshot(db,team,scope) for team in ids] for scope in (ALL_TIME,season)})
    for team,accounts in zip(ids,teams):
        db.execute('INSERT OR IGNORE INTO team_rating_teams VALUES (?,?)',(team,payload(accounts)))
        prior_members=db.execute('SELECT members FROM team_rating_teams WHERE team_id=?',(team,)).fetchone()[0]
        if prior_members!=payload(accounts):raise ValueError('Team identity collision')
    frozen=json.loads(payload(frozen))
    db.execute("INSERT INTO team_ranked_matches VALUES (?,?,?,?,?,'pending',NULL,?,NULL,NULL)",
               (match_id,season,*ids,payload(frozen),now))
    return frozen


def report(frozen,winner,contested_sides):
    if type(winner) is bool or winner not in (None,0,1):raise ValueError('Invalid team winner')
    sides=tuple(sorted(set(contested_sides)))
    if any(type(side) is not int or side not in (0,1) for side in sides):raise ValueError('Invalid contested team')
    return dict(frozen=frozen,winner=winner,contested_sides=sides)


def validate_reward(account,result,report,*,escaped=False):
    """Ordinary wounds/reward outcomes and a fixed pair's rating stay separate.

An early deserter may already have a defeat receipt while their surviving
teammate later wins; the fixed squad receives the completed team outcome.
"""
    teams=report['frozen']['teams'];winner=report['winner']
    side=next((side for side,team in enumerate(teams) if account in team),None)
    if side is None:raise ValueError('Team rating reward account missing')
    if not escaped and result!=(2 if winner is None else int(side==winner)):
        raise ValueError('Team rating reward result mismatch')


def settle(db,match_id,value,*,now=None):
    """Caller owns BEGIN IMMEDIATE; conflicting retries cannot change ratings."""
    schema(db);now=time.time() if now is None else now
    if not isinstance(value,dict) or set(value)!={'frozen','winner','contested_sides'}:raise ValueError('Invalid team rating report')
    frozen=value['frozen'];winner=value['winner']
    if not isinstance(frozen,dict) or frozen.get('version')!=1 or frozen.get('match_id')!=match_id:
        raise ValueError('Invalid frozen team rating report')
    report(frozen,winner,value['contested_sides'])
    encoded=payload(value)
    prior=db.execute('SELECT frozen,state,result FROM team_ranked_matches WHERE match_id=?',(match_id,)).fetchone()
    if prior is None or prior[0]!=payload(frozen):raise ValueError('Team rating match admission missing or changed')
    if prior[1]=='settled':
        if prior[2]!=encoded:raise ValueError('Conflicting team rating result')
        return
    if prior[1]=='void':raise ValueError('Voided team rating match')
    season=frozen['season'];ids=frozen['team_ids'];teams=frozen['teams'];auth=frozen['auth_teams']
    if len(set(a for team in auth for a in team))!=4:raise ValueError('Repeated team authenticated account')
    if tuple(auth_owners(db,[a for team in teams for a in team]))!=tuple(a for team in auth for a in team):
        raise ValueError('Team authenticated owner changed')
    season_row=db.execute('SELECT starts_at,ends_at,state FROM team_rating_seasons WHERE season_id=?',(season,)).fetchone()
    if season_row is None or tuple(season_row[:2])!=(frozen['starts_at'],frozen['ends_at']) or season_row[2]=='archived':
        raise ValueError('Team rating season changed')
    config=policy();stamp=frozen['admitted_at'];pairs={tuple(sorted((first,second))) for first in auth[0] for second in auth[1]}
    repeated=any(db.execute('''SELECT count(*) FROM team_ranked_opponents WHERE first_account=? AND second_account=?
        AND started_at>? AND started_at<=? AND rated=1''',(first,second,stamp-config['repeat_window_seconds'],stamp)).fetchone()[0]
        >=config['maximum_rated_opposing_pairs'] for first,second in pairs)
    eligible=set(value['contested_sides'])=={0,1} and not repeated
    for scope in (ALL_TIME,season):
        old=[snapshot(db,team,scope) for team in ids]
        if old!=frozen['snapshots'][scope]:raise ValueError('Team rating snapshot changed')
        inferred=ranked.infer(tuple(((row['mu'],row['sigma']),) for row in old),winner) if eligible and winner is not None else None
        for side,(team,row) in enumerate(zip(ids,old)):
            row=dict(row)
            if not eligible:row['unrated']+=1
            elif winner is None:row['draws']+=1
            else:
                row['mu'],row['sigma']=inferred[side][0];row['skill']=ranked.skill(row['mu'],row['sigma'])
                row['wins' if side==winner else 'losses']+=1
            row['revision']+=1
            db.execute('INSERT OR REPLACE INTO team_rating_values VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (scope,team,row['mu'],row['sigma'],row['skill'],row['wins'],row['losses'],row['draws'],row['unrated'],row['revision'],now))
    for first,second in sorted(pairs):db.execute('INSERT INTO team_ranked_opponents VALUES (?,?,?,?,?)',(match_id,first,second,stamp,int(eligible)))
    db.execute("UPDATE team_ranked_matches SET state='settled',result=?,finished_at=?,rated=? WHERE match_id=?",(encoded,now,int(eligible),match_id))
    rating_seasons.close_finished(db,now)


def void(db,match_id,reason,*,now=None):
    """Server interruption never becomes a win, loss or opposing-pair credit."""
    if not isinstance(reason,str) or not 1<=len(reason)<=80:raise ValueError('Invalid team void reason')
    schema(db);now=time.time() if now is None else now
    row=db.execute('SELECT state,result FROM team_ranked_matches WHERE match_id=?',(match_id,)).fetchone()
    if row is None or row[0]=='settled':return False
    if row[0]=='void':return False
    db.execute("UPDATE team_ranked_matches SET state='void',result=?,finished_at=?,rated=0 WHERE match_id=?",(payload(dict(void=reason)),now,match_id))
    rating_seasons.close_finished(db,now)
    return True


def standings(db,*,scope=None,now=None,offset=0,limit=10):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:raise ValueError('Invalid team standings page')
    scope=rating_seasons.boundary(now)[0] if scope is None else scope
    if scope!=ALL_TIME:rating_seasons.validate(scope)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='team_rating_values'").fetchone():return ()
    archived=scope!=ALL_TIME and db.execute("SELECT 1 FROM team_rating_seasons WHERE season_id=? AND state='archived'",(scope,)).fetchone()
    table='team_rating_archives' if archived else 'team_rating_values';column='season_id' if archived else 'scope'
    all_rows=db.execute(f'''SELECT v.team_id,t.members,v.mu,v.sigma,v.skill,v.wins,v.losses,v.draws,v.unrated
        FROM {table} v JOIN team_rating_teams t ON t.team_id=v.team_id
        WHERE v.{column}=? AND v.wins+v.losses+v.draws>0 ORDER BY v.skill DESC,v.team_id''',(scope,)).fetchall()
    from .rating_visibility import excluded
    all_rows=[row for row in all_rows if not any(excluded(db,owner) for owner in json.loads(row[1]))]
    result=[];previous=None;place=0
    for index,(team,accounts,mu,sigma,points,wins,losses,draws,unrated) in enumerate(all_rows,1):
        if previous!=points:place=index;previous=points
        if not offset<=index-1<offset+limit:continue
        names=[]
        for account in json.loads(accounts):
            row=db.execute('SELECT name FROM characters WHERE account=? ORDER BY slot LIMIT 1',(account,)).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name='characters'").fetchone() else None
            names.append(bytes(row[0]).decode('cp1251',errors='replace') if row else account)
        result.append(dict(team_id=team,members=json.loads(accounts),names=names,place=place,skill=points,mu=mu,sigma=sigma,
                           wins=wins,losses=losses,draws=draws,unrated=unrated,scope=scope,archived=bool(archived)))
    return tuple(result)


def status(path,*,now=None):
    """Explicit query rolls seasons; no startup account/rating writes."""
    with closing(connect(path)) as db,db:
        db.execute('BEGIN IMMEDIATE');schema(db);rating_seasons.current(db,now)
        return rating_seasons.listing(db)
