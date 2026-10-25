"""Shared cosmetic weather; never grants visibility or mutates battle actors."""
from collections import deque
from functools import lru_cache
from pathlib import Path
import hashlib,json
from types import SimpleNamespace
from .protocol.weather import encode_weather,MAX_CELLS
from .visibility import field_sight

ROOT=Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def policy():
    p=json.loads((ROOT/'config/weather.json').read_text())
    if p['version']!=1 or p['snow_enabled'] is not False or not 0<=p['rain_percent']<=100:raise ValueError('Unsupported weather policy')
    return p


@lru_cache(maxsize=1)
def fragments():return json.loads((ROOT/'config/arena_fragments.json').read_text())


def raining(field):
    meta=getattr(field,'scene_metadata',{})
    seed=meta.get('seed')
    if meta.get('town_id')==3:return False
    if meta.get('profile') not in policy()['profiles'] or type(seed) is not int:return False
    # Stable across processes, reconnects, accounts and persisted snapshots.
    return int.from_bytes(hashlib.sha256(('rain:'+str(seed)).encode()).digest()[:4],'little')%100<policy()['rain_percent']


def sheltered(field):
    closed=set(field.blocked)|set(getattr(getattr(field,'doors',None),'states',{}))
    free={(x,y) for y in range(field.height) for x in range(field.width)}-closed
    outside={p for p in free if p[0] in (0,field.width-1) or p[1] in (0,field.height-1)};pending=deque(outside)
    while pending:
        x,y=pending.popleft()
        for p in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if p in free and p not in outside:outside.add(p);pending.append(p)
    result=free-outside
    for obj in getattr(field,'scene_metadata',{}).get('objects',()):
        name=obj['file'];f=fragments().get(name)
        if f and any(n in name.lower() for n in ('house','clinic','office','residential','supermarket','barrack','shed','hangar')):
            result.update((x,y) for x in range(obj['x'],obj['x']+f['width']) for y in range(obj['y'],obj['y']+f['height']))
    return result


def packet(field,owner):
    if not raining(field):return encode_weather(False,0,())
    from .battle_item_effects import can_observe
    observers=[a for a in field._actors.values() if a.health and field.allied(a.owner_id,owner)]
    roofs=sheltered(field);combat=getattr(field,'combat',None);cells=[]
    # Necessary condition of can_observe: ordinary/illuminated range of some
    # observer, or a recon footprint. Skips most cells without the full check.
    reach=[(a.x,a.y,a.sight_radius**2) for a in observers]
    recons=()
    if combat is not None:
        from .battle_item_effects import initialize,is_dark,normal_sight
        if is_dark(combat):
            reach=[(a.x,a.y,max(a.sight_radius,normal_sight(combat,a.actor_id))**2) for a in observers]
        recons=tuple(initialize(combat)['recon'].values())
    from .recon_geometry import contains
    for y in range(field.height):
        for x in range(field.width):
            if (x,y) in roofs or (x,y) in field.blocked or (x+2*y)%3:continue
            if (all((ox-x)**2+(oy-y)**2>r2 for ox,oy,r2 in reach)
                    and not any(contains(r,x,y) for r in recons)):continue
            target=SimpleNamespace(x=x,y=y)
            if any(can_observe(combat,a,target,field=field) if combat else
                   ((a.x-x)**2+(a.y-y)**2<=a.sight_radius**2 and field_sight(field,(a.x,a.y),(x,y)))
                   for a in observers):cells.append((x,y))
    thunder=sum(getattr(field,'_ability_turns',{}).values())//4
    return encode_weather(bool(cells),thunder if cells else 0,cells[:MAX_CELLS])
