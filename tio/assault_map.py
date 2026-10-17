"""Original three-flag assault scenes with connected symmetric admission zones."""
from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
import random

from .arena_map import ArenaMap
from .protocol.battle_ground import BattleGround,GroundEntry


@dataclass(frozen=True)
class AssaultLayout:
    arena: ArenaMap
    flags: tuple
    resource: str


def generate(seed=None,*,deployment_size=12):
    if type(deployment_size) is not int or not 1<=deployment_size<=12:
        raise ValueError('An assault admits one to twelve actors per group')
    scenes=json.loads((Path(__file__).resolve().parents[1]/'config/assault_maps.json').read_text())
    source=random.Random(seed).choice(scenes)
    w,h=source['width'],source['height']
    blocked={(x,y) for y in range(h) for x in range(w) if source['tiles'][y*w+x] in (2,3,4)}
    doors=tuple((x,y,closed) for x,y,closed in source['doors'])
    for x,y,closed in doors:
        if not closed:blocked.discard((x,y))
    flags=tuple(map(tuple,source['flags']))
    transparent=frozenset(p for p in blocked if source['tiles'][p[1]*w+p[0]]!=3)
    free={(x,y) for y in range(h) for x in range(w) if (x,y) not in blocked}
    # Spawn allocation is emulator policy. Both squads use the same component;
    # all authored flags remain reachable without modifying the native scenery.
    reached=set();components=[]
    for initial in sorted(free):
        if initial in reached:continue
        group={initial};queue=deque([initial]);reached.add(initial)
        while queue:
            x,y=queue.popleft()
            for p in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if p in free and p not in reached:
                    reached.add(p);group.add(p);queue.append(p)
        if all(any(abs(x-p[0])+abs(y-p[1])<=2 for p in group) for x,y in flags):components.append(group)
    if not components:raise ValueError('Assault flags have no common reachable component')
    group=max(components,key=len)
    sides=[]
    for target in ((2,h//2),(w-3,h//2)):
        occupied={p for side in sides for p in side}
        choices=sorted(group-occupied,key=lambda p:((p[0]-target[0])**2+(p[1]-target[1])**2,p))
        sides.append(tuple(choices[:deployment_size]))
    if any(len(v)!=deployment_size for v in sides):raise ValueError('Insufficient assault spawn cells')
    ground=BattleGround(4,w,h,bytes(w*h),(GroundEntry(source['file'].encode(),0,0),),bytes(w*h))
    return AssaultLayout(ArenaMap(ground,frozenset(blocked),*sides,(),doors,
        transparent_obstacles=transparent),flags,source['file'])
