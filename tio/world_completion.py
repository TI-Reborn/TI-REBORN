"""Shared world rules, frozen coefficients, online prison and public top100.

Mutation helpers require the caller's transaction. Standings use one read-only
snapshot of real authenticated character owners and never modify game state.
New IDs/coordinates and fluctuation/spawn policies are explicit config policy.
"""
from collections import deque
from copy import deepcopy
from contextlib import closing
from dataclasses import replace
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import math
import random
import sqlite3
import time

ROOT=Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def policy():
    p=json.loads((ROOT/'config/world_completion.json').read_text(encoding='utf-8'))
    if p['version']!=1 or p['ranking']['limit']!=100 or p['coefficients']['period_seconds']!=3600:
        raise ValueError('Unsupported world policy')
    ids=[r['id'] for r in p['locations']]
    if len(ids)!=len(set(ids)) or any(type(i) is not int or not 1<=i<=65535 for i in ids):raise ValueError('Invalid world IDs')
    for r in p['locations']:
        b=r['bounds'];l=r['levels']
        if (len(b)!=4 or any(type(n) is not int or not -512<=n<=511 for n in b)
            or b[0]>=b[2] or b[1]>=b[3] or len(l)!=2 or not 1<=l[0]<=l[1]<=20):raise ValueError('Invalid world location')
    if any(not 0<Fraction(n)<=2 for n in p['coefficients']['rotation']):raise ValueError('Invalid coefficient rotation')
    return p


def location(town):
    if type(town) is not int:raise ValueError('Invalid location ID')
    return next((deepcopy(r) for r in policy()['locations'] if r['id']==town),None)


def location_bounds():return {r['id']:tuple(r['bounds']) for r in policy()['locations']}


def extra_cities():
    from .cities import City
    return {r['id']:City(r['name'],tuple(r['bounds']),tuple(r['levels']),r['profile'],
        'equipped' if r['carry_items'] else 'starter',4 if r['id']==18 else 1,1 if r['id']==18 else 0,10 if r['id']==18 else 0)
        for r in policy()['locations'] if r['arena']}


def require_location(town, levels, *, training=False):
    r=location(town)
    if r is None or (r['profile']!='assault_training' if training else not r['arena']):raise ValueError('Локация не поддерживает этот вид боя')
    levels=tuple(levels)
    if not levels or any(type(n) is not int or not r['levels'][0]<=n<=r['levels'][1] for n in levels):raise ValueError('Бойцы не соответствуют уровням локации')
    return r


def stamp(value):
    value=time.time() if value is None else value
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=2**53:raise ValueError('Invalid server timestamp')
    return value


def identity(value):
    if not isinstance(value,str) or not 1<=len(value)<=160 or any(ord(c)<32 for c in value):raise ValueError('Invalid operation identity')
    return value


def city_coefficients(town, *, now=None):
    """Primitive rational strings; safe for snapshot/journal and public views."""
    if type(town) is not int or not 1<=town<=65535:raise ValueError('Invalid city identity')
    p=policy()['coefficients'];epoch=int(stamp(now))//p['period_seconds']
    if town in p['dynamic_towns']:
        multiplier=Fraction(p['rotation'][(epoch+p['dynamic_towns'].index(town))%len(p['rotation'])])
        factors=dict(experience=str(multiplier),influence=str(multiplier),profit=str(4*multiplier),kill_bonus=10)
    else:factors=dict(p['fixed'].get(str(town),dict(experience='1',influence='1',profit='1',kill_bonus=0)))
    return dict(version=1,town_id=town,epoch=epoch,**factors)


def write(db):
    if not db.in_transaction:raise ValueError('World mutation requires caller transaction')


def freeze_city(db, match_id, town, *, now=None):
    """Call at real match admission, once, before any reward calculation."""
    write(db);identity(match_id);r=city_coefficients(town,now=now)
    db.execute('CREATE TABLE IF NOT EXISTS world_city_matches(match_id TEXT PRIMARY KEY,town INTEGER NOT NULL,body TEXT NOT NULL,digest TEXT NOT NULL)')
    row=db.execute('SELECT town,body FROM world_city_matches WHERE match_id=?',(match_id,)).fetchone()
    if row:
        if row[0]!=town:raise ValueError('Conflicting frozen match city')
        return json.loads(row[1])
    body=json.dumps(r,sort_keys=True,separators=(',',':'))
    digest=hashlib.sha256(json.dumps(policy(),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    db.execute('INSERT INTO world_city_matches VALUES (?,?,?,?)',(match_id,town,body,digest));return r


def frozen_city(db, match_id):
    identity(match_id)
    if not exists(db,'world_city_matches'):raise ValueError('Match has no admitted city coefficient snapshot')
    row=db.execute('SELECT body FROM world_city_matches WHERE match_id=?',(match_id,)).fetchone()
    if row is None:raise ValueError('Match has no admitted city coefficient snapshot')
    return json.loads(row[0])


def exists(db, table):return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone())


def public_owners(db: sqlite3.Connection) -> set[str]:
    """Authenticated, active character owners eligible for public standings."""
    from .character_identity import alias
    from .rating_visibility import excluded
    if not exists(db,'accounts'):return set()
    logins={r[0] for r in db.execute('SELECT login FROM accounts') if not excluded(db,r[0],include_retired=False)};owners=set(logins)
    if exists(db,'character_identities'):
        for login,slot,owner in db.execute('SELECT login,slot,owner FROM character_identities'):
            if login in logins:
                if owner!=alias(login,slot):raise ValueError('Corrupt public character identity')
                owners.add(owner)
    from .character_lifecycle import exists as has_revisions, valid_key
    if has_revisions(db):
        for login, slot, owner in db.execute('SELECT login,slot,owner FROM character_revisions WHERE deleted_at IS NULL'):
            if login in logins:
                if not valid_key(login, slot, owner):raise ValueError('Corrupt public character identity')
                owners.add(owner)
    owners = {owner for owner in owners if not excluded(db, owner)}
    return owners


def players(db, *, sort='rating', limit=100):
    """Internal rows include save-owner routing key; only public fields go wire."""
    if sort not in set(policy()['ranking']['sorts'])|{'kills','bronze','silver','gold'} or type(limit) is not int or not 1<=limit<=100:raise ValueError('Unsupported public rating query')
    if not exists(db,'characters') or not exists(db,'accounts'):return ()
    from .protocol.pet_info import decode_pet_info
    from .ranks import signed
    try:
        from .achievement_benefits import total_rating
    except ModuleNotFoundError as error:
        if error.name!='tio.achievement_benefits':raise
        total_rating=lambda db,account,base:base
    from .rating_visibility import excluded
    owners=public_owners(db)
    characters=list(db.execute('SELECT account,name,name_key FROM characters WHERE slot=1'))
    ratings=dict(db.execute('''SELECT s.account,SUM(s.rating) FROM soldier_ratings s
        JOIN owned_pets p ON p.account=s.account AND p.pet_id=s.pet_id GROUP BY s.account''')) if exists(db,'soldier_ratings') and exists(db,'owned_pets') else {}
    results={}
    if exists(db,'battle_rewards'):
        columns={r[1] for r in db.execute('PRAGMA table_info(battle_rewards)')}
        gate=" AND (calculation IS NULL OR CASE WHEN json_valid(calculation) THEN COALESCE(json_extract(calculation,'$.wager'),0)=0 ELSE 1 END)" if 'calculation' in columns else ''
        for account,result,count in db.execute('SELECT account,result,COUNT(*) FROM battle_rewards WHERE 1=1'+gate+' GROUP BY account,result'):
            results.setdefault(account,{})[result]=count
    statistics={}
    if exists(db,'player_battle_statistics'):
        columns={r[1] for r in db.execute('PRAGMA table_info(player_battle_statistics)')}
        fields=('damage_dealt','damage_received','kills','deaths')
        # Old saves may have fewer columns. Names are a fixed server whitelist.
        query=','.join('COALESCE(SUM('+f+'),0)' if f in columns else '0' for f in fields)
        statistics={r[0]:r[1:] for r in db.execute('SELECT account,'+query+' FROM player_battle_statistics GROUP BY account')}
    baseline=dict(db.execute('SELECT account,kills FROM player_statistics_baselines')) if exists(db,'player_statistics_baselines') else {}
    if exists(db,'achievement_counters'):
        for account,kills in db.execute("SELECT account,value FROM achievement_counters WHERE metric='kills'"):
            baseline.setdefault(account,kills)
    ranked={r[0]:r[1:] for r in db.execute('SELECT account,skill,league,wins+losses+draws FROM ranked_players')} if exists(db,'ranked_players') else {}
    rosters={}
    if exists(db,'owned_pets'):
        for owner,human,raw in db.execute('SELECT account,human,pet_packet FROM owned_pets ORDER BY account,pet_id'):
            if owner in owners:rosters.setdefault(owner,[]).append(decode_pet_info(bytes(raw),human_equipment=bool(human)).fields)
    rows=[]
    for owner,name,key in characters:
        if owner not in owners or excluded(db,owner):continue
        fields=rosters.get(owner,());levels=[f['0x8c4aef'] for f in fields]
        points=[signed(f['0x8c4bd0']) if 1<=f['0x8c4bbc']<=29 else 0 for f in fields]
        top=set(sorted(range(len(fields)),key=lambda i:(-levels[i],i))[:3])
        rank=int(sum((Fraction(p,3 if i in top or p<0 else 15) for i,p in enumerate(points)),Fraction(0)))
        dealt,received,kills,deaths=statistics.get(owner,(0,0,0,0))
        skill,league,games=ranked.get(owner,(0,3,0))
        if not games:skill,league=0,3
        rows.append(dict(owner=owner,name=bytes(name),level=max(levels,default=0),soldiers=len(fields),
            rank=rank,military_rank=min(14,max(0,(rank-1)//2500)),
            rating=min(0x7fffffff,max(-(1<<31),total_rating(db,owner,ratings.get(owner,0)))),
            wins=results.get(owner,{}).get(1,0),losses=results.get(owner,{}).get(0,0),
            damage=dealt,damage_received=received,kills=kills+baseline.get(owner,0),deaths=deaths,
            experience=sum(f['0x8c4b05'] for f in fields),skill=skill,league=league,ranked_games=games,_key=key.casefold()))
        from .clans import membership
        from .alliances import alliance_for_clan
        clan=membership(db,owner)
        alliance=alliance_for_clan(db,clan['id']) if clan else None
        rows[-1].update(clan_name=clan['name'] if clan else b'',
                        clan_crest_id=clan.get('crest_id',0) if clan else 0,
                        alliance_crest_id=alliance.get('crest_id',0) if alliance else 0)
    # Native selectors6..8 filter existing earned leagues and sort real skill.
    # League thresholds/hysteresis belong to the existing emulator ranked rules.
    league={'bronze':3,'silver':2,'gold':1}.get(sort)
    if league is not None:rows=[r for r in rows if r['ranked_games']>0 and r['league']==league]
    rows.sort(key=lambda r:(-r['skill' if league is not None else sort],r['_key'],r['owner']))
    for place,row in enumerate(rows[:limit],1):row.pop('_key');row['place']=place
    return tuple(rows[:limit])


def player_top100(path, *, sort='rating'):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('BEGIN');return players(db,sort=sort)


def prison_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS world_prison(account TEXT PRIMARY KEY,remaining REAL NOT NULL,
        token TEXT,last_tick REAL,return_town INTEGER NOT NULL,return_x REAL NOT NULL,return_y REAL NOT NULL)''')
    db.execute('CREATE TABLE IF NOT EXISTS world_prison_operations(identity TEXT PRIMARY KEY,account TEXT NOT NULL,seconds INTEGER NOT NULL)')


def prison_state(db, account):
    if not exists(db,'world_prison'):return None
    row=db.execute('SELECT remaining,return_town FROM world_prison WHERE account=?',(account,)).fetchone()
    return None if row is None else dict(remaining=math.ceil(row[0]),town_id=10 if row[0]>0 else row[1])


def sentence(db, account, seconds, operation):
    """Trusted moderation only; no client request or auto-penalty is invented."""
    write(db);identity(account);identity(operation)
    if type(seconds) is not int or not 1<=seconds<=policy()['prison']['max_sentence_seconds']:raise ValueError('Invalid online prison sentence')
    if not db.execute('SELECT 1 FROM characters WHERE account=? AND slot=1',(account,)).fetchone():raise ValueError('Unknown prisoner character')
    prison_schema(db);old=db.execute('SELECT account,seconds FROM world_prison_operations WHERE identity=?',(operation,)).fetchone()
    if old:
        if old!=(account,seconds):raise ValueError('Conflicting prison sentence retry')
        return prison_state(db,account)
    for table in ('battle_checkpoint_members','battle_settlement_jobs'):
        if exists(db,table) and db.execute('SELECT 1 FROM '+table+' WHERE account=?',(account,)).fetchone():
            raise ValueError('Finish or recover the authoritative battle before sentencing')
    from .locations import TOWNS
    places={**TOWNS,**location_bounds()}
    prior=db.execute('SELECT town_id,x,y FROM character_locations WHERE account=?',(account,)).fetchone()
    town=prior[0] if prior and prior[0] in places and prior[0]!=10 else 3
    x,y=prior[1:] if prior and prior[1] is not None and prior[2] is not None else ((places[town][0]+places[town][2])//2,(places[town][1]+places[town][3])//2)
    held=db.execute('SELECT remaining FROM world_prison WHERE account=?',(account,)).fetchone()
    remaining=(held[0] if held else 0)+seconds
    if remaining>policy()['prison']['max_sentence_seconds']:raise ValueError('Prison sentence limit exceeded')
    db.execute('''INSERT INTO world_prison VALUES (?,?,NULL,NULL,?,?,?) ON CONFLICT(account) DO UPDATE SET
        return_town=CASE WHEN world_prison.remaining>0 THEN world_prison.return_town ELSE excluded.return_town END,
        return_x=CASE WHEN world_prison.remaining>0 THEN world_prison.return_x ELSE excluded.return_x END,
        return_y=CASE WHEN world_prison.remaining>0 THEN world_prison.return_y ELSE excluded.return_y END,
        remaining=excluded.remaining''', (account,remaining,town,x,y))
    if exists(db,'map_journeys'):db.execute('DELETE FROM map_journeys WHERE account=?',(account,))
    db.execute('INSERT INTO character_locations(account,town_id,x,y) VALUES (?,10,-317,72) ON CONFLICT(account) DO UPDATE SET town_id=10,x=-317,y=72',(account,))
    db.execute('INSERT INTO world_prison_operations VALUES (?,?,?)',(operation,account,seconds));return prison_state(db,account)


def prison_online(db, account, token, *, now=None, active=True):
    """Server session heartbeat/disconnect; same token only, offline gaps unpaid."""
    write(db);identity(account);identity(token);now=stamp(now)
    if type(active) is not bool:raise ValueError('Invalid session heartbeat')
    if not exists(db,'world_prison'):return None
    row=db.execute('SELECT remaining,token,last_tick,return_town,return_x,return_y FROM world_prison WHERE account=?',(account,)).fetchone()
    if row is None:return None
    remaining,previous,last,town,x,y=row
    if remaining<=0:return prison_state(db,account)
    if not active and previous!=token:return prison_state(db,account)
    charge=now-last if previous==token and last is not None and 0<=now-last<=policy()['prison']['max_online_heartbeat_gap'] else 0
    remaining=max(0,remaining-charge)
    tick=max(last or 0,now) if previous==token else now
    db.execute('UPDATE world_prison SET remaining=?,token=?,last_tick=? WHERE account=?',(remaining,token if active and remaining else None,tick if active and remaining else None,account))
    if not remaining:db.execute('UPDATE character_locations SET town_id=?,x=?,y=? WHERE account=?',(town,x,y,account))
    return prison_state(db,account)


class TravelRestriction(ValueError):
    """A known prison restriction on entering another location or activity."""


def require_travel(
    db: sqlite3.Connection, account: str, destination: int | None = None,
) -> None:
    state = prison_state(db, account)
    if state and state['remaining'] > 0:
        raise TravelRestriction('Наказание отбывается онлайн в Prison')
    if destination == 10:
        raise TravelRestriction('В Prison попадают только по приговору')


def _detroit_dimensions(width,height,map_size):
    if map_size is None:return width,height
    if type(map_size) is not int or not 1<=map_size<=4:raise ValueError('Invalid custom battle map size')
    wager_policy=json.loads((ROOT/'config/wagers.json').read_text(encoding='utf-8'))
    if wager_policy.get('version')!=1:raise ValueError('Unsupported wager map policy')
    scale=wager_policy.get('map_scales',{}).get(str(map_size))
    if (not isinstance(scale,list) or len(scale)!=2 or any(type(n) is not int or n<=0 for n in scale)
        or scale[0]<scale[1]):raise ValueError('Invalid Detroit wager map scale')
    numerator,denominator=scale;w,h=width*numerator//denominator,height*numerator//denominator
    if not width<=w<=128 or not height<=h<=128:raise ValueError('Detroit wager canvas exceeds native bounds')
    return w,h


def detroit_wager_dimensions(mode,map_size):
    """Read-only admission preflight; fail before escrow, without making a map."""
    if type(mode) is not int or mode not in (0,1,4,7):raise ValueError('Invalid Detroit wager mode')
    if map_size is None:raise ValueError('A Detroit wager requires an explicit map size')
    record=location(18)
    fragments=json.loads((ROOT/'config/world_completion_maps.json').read_text(encoding='utf-8'))['fragments']
    fragment=fragments[record['maps'][int(mode in (1,4))]]
    return _detroit_dimensions(fragment['width'],fragment['height'],map_size)


def generate_world_map(town, *, seed=None, deployment_size=3, mode=0,map_size=None):
    """Original whole maps; selectable Detroit wager sizes use a larger canvas.

    Ordinary Detroit keeps its exact original38/50 layout. Wager sizes reuse
    config/wagers.json scales, centering the intact resource on urban brush6;
    art is never stretched and authored obstacles/doors/boxes are translated.
    Canvas composition and its integer-floor dimensions are server policy.
    """
    r=location(town)
    if r is None or r['profile'] is None:raise ValueError('No world battle map')
    if map_size is not None and r['profile']!='detroit':raise ValueError('Selectable world-map canvas is supported only in Detroit')
    if r['profile'].startswith('assault'):
        from .assault_map import generate
        return generate(seed,deployment_size=deployment_size)
    from .map_generation import generate_map,GeneratedMap,reachable_cells,connected
    if r['profile']=='military_zone':return generate_map(r['profile'],seed=seed,deployment_size=deployment_size,mode=mode)
    if type(deployment_size) is not int or not 1<=deployment_size<=6 or type(mode) is not int or mode not in (0,1,4,7):raise ValueError('Invalid world map deployment/mode')
    seed=random.SystemRandom().getrandbits(64) if seed is None else seed
    if type(seed) is not int or not 0<=seed<2**64:raise ValueError('Invalid map seed')
    from .arena_map import build_arena_map
    fragments=json.loads((ROOT/'config/world_completion_maps.json').read_text(encoding='utf-8'))['fragments']
    name=r['maps'][int(mode in (1,4))];f=fragments[name];fw,fh=f['width'],f['height']
    w,h=_detroit_dimensions(fw,fh,map_size)
    dx,dy=(w-fw)//2,(h-fh)//2
    blocked={(x+dx,y+dy) for y in range(fh) for x in range(fw) if f['tiles'][y*fw+x] in (2,3,4)}
    doors={(x+dx,y+dy) for x,y,_ in f['doors']};blocked-=doors
    blocked.update((x+dx,y+dy) for x,y in f['containers'])
    free={(x,y) for y in range(h) for x in range(w)}-blocked;components=[]
    while free:
        first=min(free);group={first};queue=deque([first]);free.remove(first)
        while queue:
            x,y=queue.popleft()
            for p in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if p in free:free.remove(p);group.add(p);queue.append(p)
        components.append(group)
    group=max(components,key=lambda c:(len(c),-min(c)[0],-min(c)[1]));sides=[]
    for tx,ty in ((2,h//2),(w-3,h//2)):
        chosen={p for side in sides for p in side};choices=sorted(group-doors-chosen,key=lambda p:((p[0]-tx)**2+(p[1]-ty)**2,p))
        sides.append(tuple(choices[:deployment_size]))
    if any(len(s)!=deployment_size for s in sides):raise ValueError('Insufficient original map spawn cells')
    layout=dict(width=w,height=h,ground_id=2,ground_brush_id=r['ground_brush'],player_spawns=sides[0],bot_spawns=sides[1],objects=[dict(file=name,x=dx,y=dy)])
    arena=build_arena_map(layout,fragments);reached=reachable_cells(arena)
    if not connected(arena,reached):raise ValueError('Original map containers/deployment not connected')
    patrol=tuple(sorted(reached,key=lambda p:((p[0]-w//2)**2+(p[1]-h//2)**2,p))[:5])
    variant='original_whole_map' if (w,h)==(fw,fh) else 'original_centered_wager_v1'
    return GeneratedMap(arena,seed,'detroit',layout,patrol,variant,None)
