"""Pure route planning for the three-owned-account mining verifier.

Consumes a fresh read-only checkpoint snapshot. It sends no packets, mutates no
field and never relaxes collision or normal mutant sight to manufacture a route.
Patrol envelopes are conservative: absence of a route is an expected refusal.
"""
from collections import OrderedDict,deque
from copy import deepcopy
from dataclasses import dataclass
from math import isqrt
import time

from tio.shot_geometry import clear_shot


class UnsafeRouteError(ValueError):
    """The bounded no-contact planner cannot provide a route."""


@dataclass(frozen=True)
class RoutePlan:
    actor_id: int
    start: tuple
    goal: tuple
    path: tuple
    safety_model: str
    unsafe_cells: int

    @property
    def steps(self):
        return len(self.path)

    def prefix(self, action_points, *, reserve=0):
        """Return an AP-bounded prefix, excluding the origin like native3C."""
        if (type(action_points) is not int or not 0 <= action_points <= 255
                or type(reserve) is not int or not 0 <= reserve <= action_points):
            raise ValueError('Invalid action-point budget')
        return self.path[:action_points-reserve]


class RouteCache:
    """Bounded process-local immutable danger cache; no actor positions cached."""
    def __init__(self, *, max_entries=8, ttl_seconds=1200, clock=time.monotonic):
        self.max_entries=_integer(max_entries,1,32)
        self.ttl_seconds=_integer(ttl_seconds,1,1200)
        self.clock=clock;self._entries=OrderedDict()

    def danger(self,state,*,npc_margin=1,patrol_radius=6):
        npc_margin=_integer(npc_margin,1,8);patrol_radius=_integer(patrol_radius,0,20)
        width,height,blocked,opaque=_geometry(state);regions=state.get('bot_patrol_regions',{})
        metadata=[]
        for actor in state['actors']:
            if actor['account'] is not None or actor['hp']==0:continue
            identity=_integer(actor['id'],1,0xffffffff)
            position=(_integer(actor['x'],0,width-1),_integer(actor['y'],0,height-1))
            values=regions.get(identity,regions.get(str(identity)))
            cells=None if values is None else frozenset(_cells(values,width,height))
            if cells is not None and position not in cells:
                raise UnsafeRouteError('Mutant has left its patrol region; pursuit cannot be bounded')
            metadata.append((identity,actor['team'],_integer(actor['sight'],0,32),cells if cells is not None else position))
        key=(width,height,frozenset(blocked),None if opaque is None else frozenset(opaque),
             tuple(sorted(metadata)),npc_margin,patrol_radius)
        now=self.clock();cached=self._entries.get(key)
        if cached is not None and 0<=now-cached[0]<=self.ttl_seconds:
            self._entries.move_to_end(key);return cached[1]
        danger=unsafe_cells(state,npc_margin=npc_margin,patrol_radius=patrol_radius)
        self._entries[key]=(now,danger);self._entries.move_to_end(key)
        while len(self._entries)>self.max_entries:self._entries.popitem(last=False)
        return danger


def _integer(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError('Invalid mining snapshot integer')
    return value


def _cells(values, width, height):
    cells=set()
    for value in values:
        if not isinstance(value,(list,tuple)) or len(value)!=2:
            raise ValueError('Invalid mining snapshot cell')
        cells.add((_integer(value[0],0,width-1),_integer(value[1],0,height-1)))
    return cells


def _geometry(state):
    width=_integer(state['width'],1,255);height=_integer(state['height'],1,255)
    blocked=_cells(state['blocked'],width,height)
    if 'transparent_obstacles' in state:
        transparent=_cells(state['transparent_obstacles'],width,height)
        if not transparent <= blocked:raise ValueError('Transparent cells must be blocked')
        opaque=blocked-transparent
    else:
        opaque=None # No assumed opaque walls: geometric exclusion is stricter.
    return width,height,blocked,opaque


def unsafe_cells(state, *, npc_margin=1, patrol_radius=6):
    """All cells detectable from any living mutant's persisted patrol region.

    LOS uses the same recovered nine-ray geometry as the server when exact
    transparent cells are supplied. Without patrol regions, exclusion radius
    is sight+2*patrol_radius+margin: a mutant at one patrol extreme could visit
    the opposite extreme. Already pursuing mutants are grounds to abort below.
    """
    npc_margin=_integer(npc_margin,1,8);patrol_radius=_integer(patrol_radius,0,20)
    width,height,blocked,opaque=_geometry(state)
    regions=state.get('bot_patrol_regions',{});danger=set()
    for actor in state['actors']:
        if actor['account'] is not None or actor['hp']==0:continue
        if actor['team']!=2:raise ValueError('Unexpected nonhuman mining side')
        identity=_integer(actor['id'],1,0xffffffff)
        position=(_integer(actor['x'],0,width-1),_integer(actor['y'],0,height-1))
        sight=_integer(actor['sight'],0,32)
        values=regions.get(identity,regions.get(str(identity)))
        if values is None:
            sources={position};radius=sight+2*patrol_radius+npc_margin
        else:
            sources=_cells(values,width,height);radius=sight+npc_margin
            if not sources or sources & blocked:raise ValueError('Invalid mutant patrol region')
            if position not in sources:
                raise UnsafeRouteError('Mutant has left its patrol region; pursuit cannot be bounded')
        for x,y in sorted(sources):
            for dx in range(-radius,radius+1):
                span=isqrt(radius*radius-dx*dx)
                for dy in range(-span,span+1):
                    cell=(x+dx,y+dy)
                    if (cell in danger or cell in blocked or not 0<=cell[0]<width
                            or not 0<=cell[1]<height):continue
                    if opaque is not None:
                        nearby={p for p in opaque if min(x,cell[0])<=p[0]<=max(x,cell[0])
                                and min(y,cell[1])<=p[1]<=max(y,cell[1])}
                        if nearby and not clear_shot((x,y),cell,nearby):continue
                    danger.add(cell)
    return frozenset(danger)


def plan_route(state, owner, goals, *, interaction_radius=0, max_steps=240,
               npc_margin=1, patrol_radius=6, cache=None):
    """Choose a shortest safe cardinal path for exactly one living owned actor.

    Goals are crate/deposit cells (interaction_radius=1) or exit cells (0).
    The verifier must fetch fresh state after each movement prefix/turn, verify
    its authoritative endpoint, and replan. No route predicts future PvP input.
    """
    owner=_integer(owner,1,0xffffffff)
    interaction_radius=_integer(interaction_radius,0,1);max_steps=_integer(max_steps,0,600)
    width,height,blocked,_=_geometry(state);goals=_cells(goals,width,height)
    if not goals:raise UnsafeRouteError('No requested mining destination')
    owned=[a for a in state['actors'] if a['owner']==owner and a['account'] is not None and a['hp']]
    if len(owned)!=1:raise ValueError('Route verifier requires one living owned fighter')
    actor=owned[0];start=(_integer(actor['x'],0,width-1),_integer(actor['y'],0,height-1))
    identity=_integer(actor['id'],1,0xffffffff)
    if cache is not None and not isinstance(cache,RouteCache):raise ValueError('Expected bounded route cache')
    danger=(unsafe_cells(state,npc_margin=npc_margin,patrol_radius=patrol_radius) if cache is None
            else cache.danger(state,npc_margin=npc_margin,patrol_radius=patrol_radius))
    # All fixture humans must remain outside the patrol envelope; an unsafe
    # teammate could cause a mutant to pursue beyond its normal patrol area.
    if any((a['x'],a['y']) in danger for a in state['actors'] if a['account'] is not None and a['hp']):
        raise UnsafeRouteError('Living owned fighter may trigger mutant pursuit')
    occupied={(a['x'],a['y']) for a in state['actors'] if a['id']!=identity and a['hp']}
    unavailable=blocked|occupied|danger
    if start in blocked:raise ValueError('Owned fighter starts in a blocked cell')
    targets={}
    for goal in sorted(goals):
        for dx in range(-interaction_radius,interaction_radius+1):
            for dy in range(-interaction_radius,interaction_radius+1):
                cell=(goal[0]+dx,goal[1]+dy)
                if 0<=cell[0]<width and 0<=cell[1]<height and cell not in unavailable:
                    targets.setdefault(cell,goal)
    if not targets:raise UnsafeRouteError('No safe interaction or exit cell')
    previous={start:None};distance={start:0};queue=deque((start,))
    endpoint=None
    while queue:
        cell=queue.popleft()
        if cell in targets:endpoint=cell;break
        if distance[cell]>=max_steps:continue
        x,y=cell
        for nxt in ((x-1,y),(x,y-1),(x,y+1),(x+1,y)):
            if (nxt in previous or nxt in unavailable or not 0<=nxt[0]<width
                    or not 0<=nxt[1]<height):continue
            previous[nxt]=cell;distance[nxt]=distance[cell]+1;queue.append(nxt)
    if endpoint is None:raise UnsafeRouteError('No safe route within the step bound')
    path=[];cell=endpoint
    while cell!=start:path.append(cell);cell=previous[cell]
    model='persisted_patrol_envelope' if state.get('bot_patrol_regions') else 'current_position_conservative_radius'
    return RoutePlan(identity,start,targets[endpoint],tuple(reversed(path)),model,len(danger))


@dataclass(frozen=True)
class MissionPlan:
    crate: RoutePlan
    deposit: RoutePlan
    exit: RoutePlan
    completed_rounds_to_wait: int

    @property
    def steps(self):return self.crate.steps+self.deposit.steps+self.exit.steps


def plan_mission(state,owner,*,max_steps=240,npc_margin=1,cache=None):
    """Read-only crate -> unoccupied deposit -> own exit preflight.

    Only an in-memory planning copy changes the owned actor's hypothetical
    position. These paths are not commands; actual state must be checked and
    replanned before every native move. This never predicts PvP opponents.
    """
    max_steps=_integer(max_steps,1,600)
    projected=deepcopy(state)
    kwargs=dict(max_steps=max_steps,npc_margin=npc_margin,cache=cache)
    def stage(goals,radius):
        plan=plan_route(projected,owner,goals,interaction_radius=radius,**kwargs)
        actor=next(a for a in projected['actors'] if a['id']==plan.actor_id)
        actor['x'],actor['y']=plan.path[-1] if plan.path else plan.start
        return plan
    crate=stage(projected['crates'],1)
    deposits=[(d['x'],d['y']) for d in projected['mining']['deposits'] if not d['installed'] and d['left']>0]
    deposit=stage(deposits,1)
    mining=projected['mining'];roles=mining['roles'];role=roles.get(owner,roles.get(str(owner)))
    if role not in (1,2,3):raise ValueError('Missing admitted mining role')
    exit=stage(mining['raider_exits'] if role==2 else mining['lift'],0)
    deadlines=mining['owner_deadlines'];deadline=deadlines.get(owner,deadlines.get(str(owner)))
    deadline=_integer(deadline,0,0x7fffffff);round=_integer(mining['round'],0,0x7fffffff)
    mission=MissionPlan(crate,deposit,exit,max(0,deadline-round))
    if mission.steps>max_steps:raise UnsafeRouteError('Mining mission exceeds total step bound')
    return mission
