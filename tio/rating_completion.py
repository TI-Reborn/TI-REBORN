"""Durable rating of fixed four-account Wall squads, separate from duel ratings.

All eight accounts, lifetime and seasonal ratings and their immutable match
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
    row=json.loads((Path(__file__).resolve().parents[1]/'config/rating_completion.json').read_text(encoding='utf-8'))
    if (row.get('version')!=1 or row.get('season_rewards')!=[] or row.get('team_players')!=4 or
        not 1<=row.get('minimum_level',0)<=row.get('maximum_level',0)<=20 or
        row.get('maximum_soldiers')!=1 or type(row.get('ranked_four_soldier_turn_seconds')) is not int or
        not 40<=row['ranked_four_soldier_turn_seconds']<=120 or
        type(row.get('repeat_window_seconds')) is not int or not 1<=row['repeat_window_seconds']<=604800 or
        type(row.get('maximum_rated_opposing_pairs')) is not int or not 1<=row['maximum_rated_opposing_pairs']<=100):
        raise ValueError('Invalid team season policy')
    return row


def ranked_turn_seconds(count):
    """Classic 1..3 timing retained; fourth pet's 120s is explicit policy."""
    from .protocol.battle_turn import turn_seconds
    if type(count) is not int or not 1<=count<=4:raise ValueError('Invalid ranked squad count')
    return turn_seconds(count) if count<=3 else policy()['ranked_four_soldier_turn_seconds']


def payload(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def members(accounts):
    values=tuple(accounts)
    if (len(values)!=4 or any(not isinstance(a,str) or not a or len(a)>128 or '\0' in a for a in values)
        or len(set(values))!=4):
        raise ValueError('Команда рейтинга требует четыре разных аккаунта')
    return tuple(sorted(values))


def identity(accounts):return hashlib.sha256(payload(members(accounts)).encode()).hexdigest()


def auth_owners(db,accounts):
    from .character_identity import auth_account
    # The root helper takes the authoritative database path, not a client login.
    path=db.execute('PRAGMA database_list').fetchone()[2]
    return tuple(auth_account(path,a) for a in accounts)


def schema(db):
    season_schema(db)
    db.execute('''CREATE TABLE IF NOT EXISTS wall_rating_teams (
        team_id TEXT PRIMARY KEY, members TEXT NOT NULL UNIQUE)''')
    db.execute('''CREATE TABLE IF NOT EXISTS wall_rating_values (
        scope TEXT NOT NULL, team_id TEXT NOT NULL, mu REAL NOT NULL,
        sigma REAL NOT NULL, skill INTEGER NOT NULL, wins INTEGER NOT NULL,
        losses INTEGER NOT NULL, draws INTEGER NOT NULL, unrated INTEGER NOT NULL,
        revision INTEGER NOT NULL, updated_at REAL NOT NULL,
        PRIMARY KEY(scope,team_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS wall_ranked_matches (
        match_id TEXT PRIMARY KEY, season_id TEXT NOT NULL,
        first_team TEXT NOT NULL, second_team TEXT NOT NULL,
        frozen TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','settled','void')),
        result TEXT, started_at REAL NOT NULL, finished_at REAL, rated INTEGER)''')
    db.execute('''CREATE TABLE IF NOT EXISTS wall_ranked_opponents (
        match_id TEXT NOT NULL, first_account TEXT NOT NULL, second_account TEXT NOT NULL,
        started_at REAL NOT NULL, rated INTEGER NOT NULL,
        PRIMARY KEY(match_id,first_account,second_account))''')
    db.execute('CREATE INDEX IF NOT EXISTS wall_ranked_pair_history ON wall_ranked_opponents(first_account,second_account,started_at)')


def snapshot(db,team,scope=ALL_TIME):
    row=db.execute('''SELECT mu,sigma,skill,wins,losses,draws,unrated,revision
        FROM wall_rating_values WHERE scope=? AND team_id=?''',(scope,team)).fetchone()
    values=row if row else (ranked.MU,ranked.SIGMA,0,0,0,0,0,0)
    return dict(zip(('mu','sigma','skill','wins','losses','draws','unrated','revision'),values))


def admit(db,match_id,teams,*,now=None):
    """Freeze fixed Wall squads and both rating scopes when the real match is born."""
    now=time.time() if now is None else now
    rating_seasons.boundary(now)
    if not isinstance(match_id,str) or not 1<=len(match_id)<=128:raise ValueError('Invalid team match identity')
    if len(teams)!=2:raise ValueError('Team rating requires two teams')
    teams=tuple(members(team) for team in teams);accounts=tuple(a for team in teams for a in team)
    if len(set(accounts))!=8:raise ValueError('Repeated team account')
    # Schema creation alone adds no rows; the first eligible live battle creates
    # a season. Wallet existence is the existing character ownership boundary.
    for account in accounts:
        if not db.execute('SELECT 1 FROM wallets WHERE account=?',(account,)).fetchone():raise ValueError('Team rating account missing')
    auth=auth_owners(db,accounts)
    if len(set(auth))!=8:raise ValueError('Рейтинговый бой требует восемь разных игровых аккаунтов')
    schema(db)
    prior=db.execute('SELECT frozen,state FROM wall_ranked_matches WHERE match_id=?',(match_id,)).fetchone()
    if prior:
        frozen=json.loads(prior[0])
        if frozen['teams']!=[list(team) for team in teams]:raise ValueError('Conflicting admitted team match')
        if prior[1]!='pending':raise ValueError('Team match already closed')
        return frozen
    season,first,last=current(db,now)
    ids=tuple(identity(team) for team in teams)
    frozen=dict(version=2,format='wall',match_id=match_id,season=season,starts_at=first,ends_at=last,
                admitted_at=now,teams=teams,team_ids=ids,auth_teams=(auth[:4],auth[4:]),
                snapshots={scope:[snapshot(db,team,scope) for team in ids] for scope in (ALL_TIME,season)})
    for team,accounts in zip(ids,teams):
        db.execute('INSERT OR IGNORE INTO wall_rating_teams VALUES (?,?)',(team,payload(accounts)))
        prior_members=db.execute('SELECT members FROM wall_rating_teams WHERE team_id=?',(team,)).fetchone()[0]
        if prior_members!=payload(accounts):raise ValueError('Team identity collision')
    frozen=json.loads(payload(frozen))
    db.execute("INSERT INTO wall_ranked_matches VALUES (?,?,?,?,?,'pending',NULL,?,NULL,NULL)",
               (match_id,season,*ids,payload(frozen),now))
    return frozen


def report(frozen,winner,contested_sides):
    if type(winner) is bool or winner not in (None,0,1):raise ValueError('Invalid team winner')
    sides=tuple(sorted(set(contested_sides)))
    if any(type(side) is not int or side not in (0,1) for side in sides):raise ValueError('Invalid contested team')
    return dict(frozen=frozen,winner=winner,contested_sides=sides)


def validate_reward(account,result,report,*,escaped=False):
    """Ordinary wounds/reward outcomes and a fixed Wall squad's rating stay separate.

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
    rating_seasons.boundary(now)
    if not isinstance(value,dict) or set(value)!={'frozen','winner','contested_sides'}:raise ValueError('Invalid team rating report')
    frozen=value['frozen'];winner=value['winner']
    if not isinstance(frozen,dict) or frozen.get('version')!=2 or frozen.get('format')!='wall' or frozen.get('match_id')!=match_id:
        raise ValueError('Invalid frozen team rating report')
    report(frozen,winner,value['contested_sides'])
    encoded=payload(value)
    prior=db.execute('SELECT frozen,state,result FROM wall_ranked_matches WHERE match_id=?',(match_id,)).fetchone()
    if prior is None or prior[0]!=payload(frozen):raise ValueError('Team rating match admission missing or changed')
    if prior[1]=='settled':
        if prior[2]!=encoded:raise ValueError('Conflicting team rating result')
        return
    if prior[1]=='void':raise ValueError('Voided team rating match')
    season=frozen['season'];ids=frozen['team_ids'];teams=frozen['teams'];auth=frozen['auth_teams']
    if len(set(a for team in auth for a in team))!=8:raise ValueError('Repeated team authenticated account')
    if tuple(auth_owners(db,[a for team in teams for a in team]))!=tuple(a for team in auth for a in team):
        raise ValueError('Team authenticated owner changed')
    season_row=db.execute('SELECT starts_at,ends_at,state FROM wall_rating_seasons WHERE season_id=?',(season,)).fetchone()
    if season_row is None or tuple(season_row[:2])!=(frozen['starts_at'],frozen['ends_at']) or season_row[2]=='archived':
        raise ValueError('Team rating season changed')
    config=policy();stamp=frozen['admitted_at'];pairs={tuple(sorted((first,second))) for first in auth[0] for second in auth[1]}
    repeated=any(db.execute('''SELECT count(*) FROM wall_ranked_opponents WHERE first_account=? AND second_account=?
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
            db.execute('INSERT OR REPLACE INTO wall_rating_values VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (scope,team,row['mu'],row['sigma'],row['skill'],row['wins'],row['losses'],row['draws'],row['unrated'],row['revision'],now))
    for first,second in sorted(pairs):db.execute('INSERT INTO wall_ranked_opponents VALUES (?,?,?,?,?)',(match_id,first,second,stamp,int(eligible)))
    db.execute("UPDATE wall_ranked_matches SET state='settled',result=?,finished_at=?,rated=? WHERE match_id=?",(encoded,now,int(eligible),match_id))
    close_finished(db,now)


def void(db,match_id,reason,*,now=None):
    """Server interruption never becomes a win, loss or opposing-pair credit."""
    if not isinstance(reason,str) or not 1<=len(reason)<=80:raise ValueError('Invalid team void reason')
    schema(db);now=time.time() if now is None else now
    row=db.execute('SELECT state,result FROM wall_ranked_matches WHERE match_id=?',(match_id,)).fetchone()
    if row is None or row[0]=='settled':return False
    if row[0]=='void':return False
    db.execute("UPDATE wall_ranked_matches SET state='void',result=?,finished_at=?,rated=0 WHERE match_id=?",(payload(dict(void=reason)),now,match_id))
    close_finished(db,now)
    return True


def standings(db,*,scope=None,now=None,offset=0,limit=10):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:raise ValueError('Invalid team standings page')
    scope=rating_seasons.boundary(now)[0] if scope is None else scope
    if scope!=ALL_TIME:rating_seasons.validate(scope)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='wall_rating_values'").fetchone():return ()
    archived=scope!=ALL_TIME and db.execute("SELECT 1 FROM wall_rating_seasons WHERE season_id=? AND state='archived'",(scope,)).fetchone()
    table='wall_rating_archives' if archived else 'wall_rating_values';column='season_id' if archived else 'scope'
    all_rows=db.execute(f'''SELECT v.team_id,t.members,v.mu,v.sigma,v.skill,v.wins,v.losses,v.draws,v.unrated
        FROM {table} v JOIN wall_rating_teams t ON t.team_id=v.team_id
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
        db.execute('BEGIN IMMEDIATE');schema(db);current(db,now)
        return seasons(db)


def season_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS wall_rating_seasons (
        season_id TEXT PRIMARY KEY, starts_at REAL NOT NULL, ends_at REAL NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('open','closing','archived')),
        created_at REAL NOT NULL, archived_at REAL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS wall_rating_archives (
        season_id TEXT NOT NULL, team_id TEXT NOT NULL, place INTEGER NOT NULL,
        mu REAL NOT NULL, sigma REAL NOT NULL, skill INTEGER NOT NULL,
        wins INTEGER NOT NULL, losses INTEGER NOT NULL, draws INTEGER NOT NULL,
        unrated INTEGER NOT NULL, archived_at REAL NOT NULL,
        PRIMARY KEY(season_id,team_id))''')


def close_finished(db,now=None):
    """Archive old seasons atomically; unfinished frozen matches retain them."""
    now=time.time() if now is None else now
    season_schema(db)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='wall_ranked_matches'").fetchone():return ()
    closed=[]
    for (identity,) in db.execute("SELECT season_id FROM wall_rating_seasons WHERE ends_at<=? AND state!='archived' ORDER BY starts_at",(now,)).fetchall():
        db.execute("UPDATE wall_rating_seasons SET state='closing' WHERE season_id=?",(identity,))
        if db.execute("SELECT 1 FROM wall_ranked_matches WHERE season_id=? AND state='pending' LIMIT 1",(identity,)).fetchone():continue
        rows=db.execute('''SELECT team_id,mu,sigma,skill,wins,losses,draws,unrated
            FROM wall_rating_values WHERE scope=? AND wins+losses+draws>0
            ORDER BY skill DESC,team_id''',(identity,)).fetchall()
        place=0;previous=None
        for index,(team,mu,sigma,points,wins,losses,draws,unrated) in enumerate(rows,1):
            if points!=previous:place=index;previous=points
            db.execute('INSERT INTO wall_rating_archives VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (identity,team,place,mu,sigma,points,wins,losses,draws,unrated,now))
        db.execute("UPDATE wall_rating_seasons SET state='archived',archived_at=? WHERE season_id=?",(now,identity))
        closed.append(identity)
    return tuple(closed)


def current(db,now=None):
    """Lazy: no season or rating rows are created merely by server startup."""
    now=time.time() if now is None else now
    identity,first,last=rating_seasons.boundary(now);season_schema(db)
    close_finished(db,now)
    prior=db.execute('SELECT starts_at,ends_at,state FROM wall_rating_seasons WHERE season_id=?',(identity,)).fetchone()
    if prior is not None:
        if tuple(prior[:2])!=(first,last) or prior[2]!='open':raise ValueError('Season boundary conflict')
    else:db.execute("INSERT INTO wall_rating_seasons VALUES (?,?,?,'open',?,NULL)",(identity,first,last,now))
    return identity,first,last


def seasons(db,*,limit=12):
    if type(limit) is not int or not 1<=limit<=120:raise ValueError('Invalid season limit')
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='wall_rating_seasons'").fetchone():return ()
    return tuple(dict(id=i,starts_at=start,ends_at=end,state=state,archived_at=archived)
        for i,start,end,state,archived in db.execute('''SELECT season_id,starts_at,ends_at,state,archived_at
            FROM wall_rating_seasons ORDER BY starts_at DESC LIMIT ?''',(limit,)))


def public_listing(db,*,format='wall',scope=None,offset=0,limit=10,now=None):
    """Read-only UI DTO: no logins, aliases, wallet grants or lazy SQL writes.

    Fixed-pair tables and values are read by their original implementation.
    Wall values remain independent. Rewards are explicitly empty until an
    authenticated historical specification or a server policy is approved.
    """
    from . import team_ratings
    if format not in ('pairs','wall'):raise ValueError('Unknown rating format')
    if type(offset) is not int or not 0<=offset<=9990 or type(limit) is not int or not 1<=limit<=100:
        raise ValueError('Invalid rating page')
    now=time.time() if now is None else now
    current_id,first,last=rating_seasons.boundary(now)
    scope=current_id if scope is None else scope
    if scope!=ALL_TIME:rating_seasons.validate(scope)
    query_standings=team_ratings.standings if format=='pairs' else standings
    result=query_standings(db,scope=scope,offset=offset,limit=limit)
    rows=[]
    has_characters=bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='characters'").fetchone())
    for row in result:
        names=[]
        for owner in row['members']:
            saved=db.execute('SELECT name FROM characters WHERE account=? ORDER BY slot LIMIT 1',(owner,)).fetchone() if has_characters else None
            name=bytes(saved[0]).decode('cp1251',errors='replace') if saved else 'Удалённый персонаж'
            names.append(name)
        rows.append(dict(teamId=row['team_id'],names=names,place=row['place'],skill=row['skill'],
                         wins=row['wins'],losses=row['losses'],draws=row['draws'],unrated=row['unrated']))
    table='team_rating_values' if format=='pairs' else 'wall_rating_values'
    archive='team_rating_archives' if format=='pairs' else 'wall_rating_archives'
    season_table='team_rating_seasons' if format=='pairs' else 'wall_rating_seasons'
    has_tables=bool(db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone())
    season=db.execute('SELECT state FROM '+season_table+' WHERE season_id=?',(scope,)).fetchone() if has_tables and scope!=ALL_TIME else None
    archived=bool(season and season[0]=='archived')
    values_table=archive if archived else table
    column='season_id' if archived else 'scope'
    from .rating_visibility import excluded
    teams_table='team_rating_teams' if format=='pairs' else 'wall_rating_teams'
    total=sum(not any(excluded(db,owner) for owner in json.loads(members)) for (members,) in db.execute(
        'SELECT t.members FROM '+values_table+' v JOIN '+teams_table+' t ON t.team_id=v.team_id WHERE v.'+column+'=? AND v.wins+v.losses+v.draws>0',(scope,))) if has_tables else 0
    season_rows=rating_seasons.listing(db) if format=='pairs' else seasons(db)
    return dict(version=1,format=format,playersPerSide=2 if format=='pairs' else 4,
                soldiersPerPlayer=3 if format=='pairs' else 1,scope=scope,
                calendar='UTC calendar month',currentSeason=dict(id=current_id,startsAt=int(first),endsAt=int(last)),
                seasonState='all' if scope==ALL_TIME else (season[0] if season else 'not_created'),
                archived=archived,offset=offset,limit=limit,total=total,hasMore=offset+len(rows)<total,rows=rows,
                seasons=[dict(id=r['id'],startsAt=int(r['starts_at']),endsAt=int(r['ends_at']),state=r['state'],
                              archivedAt=None if r['archived_at'] is None else int(r['archived_at'])) for r in season_rows],
                rewards=[],historicalSeasonScheduleConfirmed=False,historicalSeasonRewardsConfirmed=False,
                ratingModel='Fixed squad Gaussian model; server policy')
