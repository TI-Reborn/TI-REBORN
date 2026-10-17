"""Original mine scenery with randomized reachable deposits and mutants."""
from collections import deque
from dataclasses import dataclass
from pathlib import Path
import json,random
from .arena_map import ArenaMap
from .protocol.battle_ground import BattleGround,GroundEntry


@dataclass(frozen=True)
class MineLayout:
    arena: ArenaMap
    deposits: tuple
    lift: frozenset
    raider_exits: frozenset
    resource: str


def generate(seed=None,*,role=1,shared=False):
    if type(role) is not int or role not in (1,2,3):raise ValueError('Invalid mining role')
    if type(shared) is not bool:raise ValueError('Invalid shared mining flag')
    rng=random.Random(seed)
    maps=json.loads((Path(__file__).resolve().parents[1]/'config/mine_maps.json').read_text())
    source=rng.choice(maps);w,h=source['width'],source['height']
    blocked={(x,y) for y in range(h) for x in range(w) if source['tiles'][y*w+x] in (2,3,4)}
    crates=tuple((x,y) for name,x,y in source['models'] if name=='item_steel_box_01b.t')
    if len(crates)!=1:raise ValueError('Expected one drill crate')
    blocked.update(crates)
    transparent=frozenset(p for p in blocked if source['tiles'][p[1]*w+p[0]]!=3)
    # Authored open boundary cells are the upper lift and three raid passages.
    edges={p for y in range(h) for x in range(w) if (x in (0,w-1) or y in (0,h-1)) and (p:=(x,y)) not in blocked}
    upper={p for p in edges if p[1]==0};other=edges-upper
    if not upper or not other:raise ValueError('Missing original mine exits')
    def flood(starts):
        distance={p:0 for p in starts};queue=deque(sorted(starts))
        while queue:
            x,y=queue.popleft()
            for p in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if not (0<=p[0]<w and 0<=p[1]<h) or p in blocked or p in distance:continue
                distance[p]=distance[(x,y)]+1;queue.append(p)
        return distance
    reachable=flood(upper)
    other.intersection_update(reachable)
    start=upper if role in (1,3) else {rng.choice(sorted(other))}
    distances=flood(start)
    spawn=tuple(sorted(distances,key=lambda p:(distances[p],p))[:3])
    choices=[p for p,d in reachable.items() if d>=15 and distances.get(p,0)>=12 and
             2<=p[0]<w-2 and 2<=p[1]<h-2 and all((p[0]+dx,p[1]+dy) in reachable for dx,dy in ((-1,0),(1,0),(0,-1),(0,1)))]
    rng.shuffle(choices)
    deposits=[]
    for p in choices:
        if all(abs(p[0]-q[0])+abs(p[1]-q[1])>=12 for q in deposits):deposits.append(p)
        if len(deposits)==3:break
    deposits=tuple(deposits[:rng.randint(2,3)])
    # Reserve every authored entry when the single shared scene is born. A
    # random mutant beside each raid passage previously made all late raider
    # admission cells unsafe. Live joins never move or regenerate mutants.
    lift=frozenset(p for p,d in flood(upper).items() if d<=2)
    exits=frozenset(p for p,d in flood(other).items() if d<=2)
    entry_distance=flood(lift|exits) if shared else {}
    mobs=tuple(p for p in choices if p not in deposits
               and (not shared or entry_distance.get(p,0)>9))[:10]
    if len(deposits)<2 or len(mobs)!=10:raise ValueError('Insufficient reachable mine cells')
    # Original ground.xml id5, original full .s scene registered by basename.
    ground=BattleGround(5,w,h,bytes(w*h),(GroundEntry(source['file'].encode(),0,0),),bytes(w*h))
    # Exit membership includes one-cell approach, avoiding edge camera traps.
    return MineLayout(ArenaMap(ground,frozenset(blocked),spawn,mobs,crates,transparent_obstacles=transparent),deposits,lift,exits,source['file'])


def spawn_positions(layout,role,count,*,occupied=(),mutants=()):
    """Allocate a joining squad near its authored exit, without sharing cells.

    Living mutants cannot start within nine walkable steps of a new squad.
    Existing positions and the original scene remain unchanged on admission.
    """
    if type(role) is not int or role not in (1,2,3) or type(count) is not int or not 1<=count<=3:
        raise ValueError('Invalid mining squad placement')
    arena=layout.arena;w,h=arena.ground.width,arena.ground.height
    def flood(starts,limit):
        distances={p:0 for p in starts};queue=deque(sorted(starts))
        while queue:
            x,y=queue.popleft()
            if distances[x,y]>=limit:continue
            for p in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if not (0<=p[0]<w and 0<=p[1]<h) or p in arena.blocked or p in distances:continue
                distances[p]=distances[x,y]+1;queue.append(p)
        return distances
    starts=layout.raider_exits if role==2 else layout.lift
    distances=flood(starts,6)
    unavailable=set(occupied)|set(flood(mutants,9))|set(layout.deposits)
    cells=sorted(set(distances)-unavailable,key=lambda p:(distances[p],min(p[0],w-1-p[0],p[1],h-1-p[1]),p))
    if len(cells)<count:raise ValueError('No safe mine entrance cells for this squad')
    return tuple(cells[:count])
