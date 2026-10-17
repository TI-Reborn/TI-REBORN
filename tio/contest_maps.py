"""Original whole TrueSkill contest scenes; spawn selection is server policy."""
from collections import deque
from functools import lru_cache
from dataclasses import replace
from pathlib import Path
import json,random,secrets
from .arena_map import build_arena_map
from .map_generation import GeneratedMap,connected,reachable_cells


@lru_cache(maxsize=1)
def catalogue():
    p=json.loads((Path(__file__).resolve().parents[1]/'config/contest_maps.json').read_text())
    if p['version']!=1 or len(p['maps'])!=9:raise ValueError('Invalid contest catalogue')
    return p['maps']


def generate(*,seed=None,deployment_size=3):
    if type(deployment_size) is not int or not 1<=deployment_size<=6:raise ValueError('Invalid ranked deployment')
    seed=secrets.randbits(64) if seed is None else seed
    if type(seed) is not int or not 0<=seed<2**64:raise ValueError('Invalid contest seed')
    rng=random.Random(seed);row=rng.choice(catalogue());f=row['fragment'];w,h=f['width'],f['height']
    flags=tuple(map(tuple,row['flags']))
    doors={tuple(d[:2]) for d in f['doors']};boxes=set(map(tuple,f['containers']))
    blocked={(i%w,i//w) for i,t in enumerate(f['tiles']) if t in (2,3,4)}-doors
    blocked|=boxes|set(flags)
    free={(x,y) for y in range(h) for x in range(w)}-blocked
    # All three flags need reachable capture neighbours in one component.
    groups=[]
    while free:
        start=min(free);free.remove(start);group={start};queue=deque([start])
        while queue:
            x,y=queue.popleft()
            for cell in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if cell in free:free.remove(cell);group.add(cell);queue.append(cell)
        if all(any(abs(x-a)+abs(y-b)<=2 for x,y in group) for a,b in flags):groups.append(group)
    if not groups:raise ValueError('Contest control points disconnected')
    group=max(groups,key=lambda g:(len(g),-min(g)[0],-min(g)[1]))
    if rng.getrandbits(1):flags=(flags[1],flags[0],flags[2])
    sides=[]
    for tx,ty in flags[:2]:
        used={p for side in sides for p in side}
        choices=sorted(group-doors-used,key=lambda p:((p[0]-tx)**2+(p[1]-ty)**2,p))
        side=tuple(choices[:deployment_size])
        if len(side)!=deployment_size:raise ValueError('Contest deployment lacks safe cells')
        sides.append(side)
    layout=dict(width=w,height=h,ground_id=0,ground_brush_id=row['ground_brush_id'],
        player_spawns=sides[0],bot_spawns=sides[1],objects=[dict(file=row['file'],x=0,y=0)],control_points=flags)
    arena=build_arena_map(layout,{row['file']:f})
    # Existing ranked battles reserve occupied checkpoint cells as class2:
    # impassable to movement, transparent to sight. Some authored grids omit
    # these reservations even though their flag models are present.
    arena=replace(arena,blocked=arena.blocked|frozenset(flags),
        transparent_obstacles=arena.transparent_obstacles|frozenset(flags))
    reached=reachable_cells(arena)
    if not connected(arena,reached):raise ValueError('Contest boxes or spawns disconnected')
    return GeneratedMap(arena,seed,'trueskill_contest',layout,(),row['file'],None)
