"""Read-only native clan/alliance standings by influence and clan TrueSkill.

The native client requests three consecutive pages of one hundred clans.
The optional level filter is an emulator query, independent of those pages. An
alliance sums its current clans; viewing never generates points or applies fees.
"""
from contextlib import closing
from fractions import Fraction
from pathlib import Path
import sqlite3


def clans(db: sqlite3.Connection,*,level: int | None=None,offset: int=0,limit: int=100,
          trueskill: bool=False) -> tuple[dict,...]:
    if level is not None and (type(level) is not int or level not in (0,1,2)):
        raise ValueError('Invalid clan rating level')
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
        raise ValueError('Invalid rating page')
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='clans'").fetchone():return ()
    from .rating_visibility import exclusion_filter
    hidden_owner=exclusion_filter(db)
    where='' if level is None else ' WHERE c.level=?'
    args=() if level is None else (level,)
    rows=db.execute('''SELECT c.id,c.name,c.level,c.influence,
        (SELECT COUNT(*) FROM clan_members m WHERE m.clan_id=c.id),
        (SELECT name FROM characters WHERE account=c.leader ORDER BY slot LIMIT 1),c.leader
        FROM clans c'''+where+' ORDER BY c.influence DESC,c.id',args).fetchall()
    records=[dict(id=i,name=bytes(name),level=lvl,influence=points,members=count,
                  leader_name=bytes(leader) if leader else b'')
             for i,name,lvl,points,count,leader,owner in rows if not hidden_owner(owner)]
    if trueskill:
        averages=_trueskill_averages(db,{r['id'] for r in records})
        records.sort(key=lambda r:(-averages[r['id']],r['id']))
        for row in records:row['rating']=int(averages[row['id']])
    return tuple({**row,'place':offset+index+1} for index,row in enumerate(records[offset:offset+limit]))


def _trueskill_averages(db: sqlite3.Connection, clan_ids: set[int]) -> dict[int,Fraction]:
    from .rating_visibility import exclusion_filter
    hidden_owner=exclusion_filter(db)
    scores={clan_id:[] for clan_id in clan_ids}
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='ranked_players'").fetchone():
        return dict.fromkeys(clan_ids,Fraction(0))
    rows=db.execute('''SELECT m.clan_id,m.account,COALESCE(p.skill,0) FROM clan_members m
        LEFT JOIN ranked_players p ON p.account=m.account''')
    for clan_id,account,skill in rows:
        if clan_id in scores and not hidden_owner(account):scores[clan_id].append(skill)
    return {clan_id:Fraction(sum(points),len(points) or 1) for clan_id,points in scores.items()}


def alliances(db,*,offset=0,limit=100):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
        raise ValueError('Invalid rating page')
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='alliances'").fetchone():return ()
    from .alliances import alliance_for_clan
    from .rating_visibility import exclusion_filter
    hidden_owner=exclusion_filter(db)
    # Query through the active-membership helper so dissolving alliances never
    # retain a phantom rank or defense privilege during their restore window.
    records={};hidden=set()
    for (clan_id,) in db.execute('SELECT clan_id FROM alliance_members'):
        leader=db.execute('SELECT leader FROM clans WHERE id=?',(clan_id,)).fetchone()
        item=alliance_for_clan(db,clan_id)
        if item is not None:
            if leader and hidden_owner(leader[0]):hidden.add(item['id'])
            records[item['id']]=item
    records={key:value for key,value in records.items() if key not in hidden}
    ordered=sorted(records.values(),key=lambda a:(-a['influence'],a['id']))
    return tuple({**row,'place':index+1} for index,row in enumerate(ordered)
                 if offset<=index<offset+limit)


def standings(path,*,kind='clans',level=None,offset=0,limit=100):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('BEGIN')
        if kind=='clans':return clans(db,level=level,offset=offset,limit=limit)
        if kind=='clan_trueskill':return clans(db,level=level,offset=offset,limit=limit,trueskill=True)
        if kind=='alliances':return alliances(db,offset=offset,limit=limit)
        raise ValueError('Invalid rating kind')
