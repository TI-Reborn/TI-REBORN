"""Two-side TrueSkill inference and transactional, match-wide rating receipts.

Microsoft's Gaussian model uses mu=25, sigma=25/3, beta=25/6,
tau=25/300. The 0..400 projection and league hysteresis are emulator policy.
Draws leave the rating unchanged, following the TIO administration's rules.
"""
from contextlib import closing
import json
import math
import time
from .db_transaction import connect

MU=25.0
SIGMA=25/3
BETA=25/6
TAU=25/300


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS ranked_players (
        account TEXT PRIMARY KEY, mu REAL NOT NULL, sigma REAL NOT NULL,
        skill INTEGER NOT NULL, league INTEGER NOT NULL, wins INTEGER NOT NULL,
        losses INTEGER NOT NULL, draws INTEGER NOT NULL, streak INTEGER NOT NULL,
        loss_streak INTEGER NOT NULL, updated_at REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS ranked_matches (
        match_id TEXT PRIMARY KEY, report TEXT NOT NULL, settled_at REAL NOT NULL)''')


def skill(mu,sigma):
    return min(400,max(0,math.floor(8*(mu-3*sigma))))


def league_for(points):
    return 3 if points<=100 else 2 if points<=200 else 1 if points<=300 else 0


def infer(teams,winner,*,average=False):
    """Closed-form EP update for two teams, equal player participation weights."""
    variances=[[s*s+TAU*TAU for m,s in team] for team in teams]
    weights=[1/len(t) if average else 1 for t in teams]
    c=math.sqrt(sum(weights[side]**2*(v+BETA*BETA) for side,vs in enumerate(variances) for v in vs))
    difference=weights[winner]*sum(m for m,s in teams[winner])-weights[1-winner]*sum(m for m,s in teams[1-winner])
    t=difference/c
    density=math.exp(-t*t/2)/math.sqrt(2*math.pi)
    probability=.5*math.erfc(-t/math.sqrt(2))
    # Mills ratio remains finite for very unlikely upsets.
    v=density/probability if probability>1e-280 else -t+1/max(1,-t)
    w=min(1,max(0,v*(v+t)))
    return tuple(tuple((m+(1 if side==winner else -1)*var*weights[side]/c*v,
                        math.sqrt(max(1e-9,var*(1-var*weights[side]**2/(c*c)*w))))
                       for (m,s),var in zip(team,variances[side]))
                 for side,team in enumerate(teams))


def snapshot(path,account):
    with closing(connect(path)) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='ranked_players'").fetchone():
            row=db.execute('SELECT mu,sigma FROM ranked_players WHERE account=?',(account,)).fetchone()
            if row:return tuple(row)
    return MU,SIGMA


def settle(db,match_id,report,*,now=None):
    """Both sides update together, even if only one reward job is replayed."""
    teams=report['teams'];winner=report['winner']
    if winner not in (None,0,1) or len(teams)!=2 or any(not t or len(t)>4 for t in teams):
        raise ValueError('Invalid ranked result')
    accounts=[p[0] for team in teams for p in team]
    if len(accounts)!=len(set(accounts)):raise ValueError('Repeated ranked account')
    for team in teams:
        for account,mu,sigma in team:
            if not isinstance(account,str) or not account or not math.isfinite(mu) or not math.isfinite(sigma) or sigma<=0:
                raise ValueError('Invalid ranked participant')
            if not db.execute('SELECT 1 FROM wallets WHERE account=?',(account,)).fetchone():
                raise ValueError('Ranked account missing')
    payload=json.dumps(report,sort_keys=True,allow_nan=False)
    schema(db)
    prior=db.execute('SELECT report FROM ranked_matches WHERE match_id=?',(match_id,)).fetchone()
    if prior:
        if prior[0]!=payload:raise ValueError('Conflicting ranked result')
        return
    # Average account participation prevents a side with more account owners
    # from being treated as stronger merely because its same four fighters
    # belong to several people. Equal-size historical matches are unchanged.
    model=tuple(tuple((m,s) for a,m,s in team) for team in teams)
    updated=infer(model,winner,average=True) if winner is not None else None
    forfeits=set(report.get('forfeits',()))
    if not forfeits.issubset(accounts):raise ValueError('Unknown ranked forfeit')
    now=time.time() if now is None else now
    for side,team in enumerate(teams):
        for index,(account,mu,sigma) in enumerate(team):
            old=db.execute('SELECT mu,sigma,skill,league,wins,losses,draws,streak,loss_streak FROM ranked_players WHERE account=?',(account,)).fetchone()
            if old is None:old=(MU,SIGMA,0,3,0,0,0,0,0)
            if not math.isclose(old[0],mu) or not math.isclose(old[1],sigma):raise ValueError('Ranked snapshot changed')
            _,_,points,league,wins,losses,draws,streak,loss_streak=old
            league_before=league
            outcome=None if winner is None else side==winner
            if account in forfeits:outcome=False
            if outcome is None:
                draws+=1;streak=loss_streak=0
            else:
                result=updated
                if account in forfeits and side==winner or winner is None:
                    result=infer(model,1-side,average=True)
                mu,sigma=result[side][index];points=skill(mu,sigma)
                if outcome:wins+=1;streak+=1;loss_streak=0
                else:losses+=1;loss_streak+=1;streak=0
                target=league_for(points)
                # Administration's May 3 correction supersedes April 28.
                if target<league and outcome:league=target
                elif target>league and loss_streak>=4:league+=1
            db.execute('INSERT OR REPLACE INTO ranked_players VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (account,mu,sigma,points,league,wins,losses,draws,streak,loss_streak,now))
            from .achievements import ranked_result
            ranked_result(db,account,match_id,result=2 if outcome is None else int(outcome),
                          league_before=league_before,league_after=league,streak=streak)
    db.execute('INSERT INTO ranked_matches VALUES (?,?,?)',(match_id,payload,now))


def profile(db,account):
    from .rating_visibility import excluded
    if excluded(db,account):return 0,3,0,0
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='ranked_players'").fetchone():return 0,3,0,0
    row=db.execute('SELECT skill,league,streak,wins+losses+draws FROM ranked_players WHERE account=?',(account,)).fetchone()
    if row is None or not row[3]:return 0,3,0,0
    points,league,streak,_=row
    # Competition ranking: equal displayed ratings share a place.
    place=1+sum(not excluded(db,owner) for (owner,) in db.execute('SELECT account FROM ranked_players WHERE skill>? AND wins+losses+draws>0',(points,)))
    return points,league,place,min(streak,65535)
