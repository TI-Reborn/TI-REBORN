"""Bounded procedural assembly of original client fragments.

The assets are original; composition, density and per-mode dimensions are
explicit server policy. A seed reproduces a scene for debugging, not a save game.
"""
from collections import deque
from dataclasses import dataclass, replace
import json
from pathlib import Path
import random
import secrets
from .arena_map import ArenaMap, build_arena_map
from .arena_surroundings import add_arena_surroundings

ROOT = Path(__file__).resolve().parents[1]

# Published ground.xml: forest=3, urban=2, military=1. In particular 4 is
# the mixed Denver assault-base ground, not New York's urban terrain.
CITY_GROUND_BRUSH_IDS = {'denver': 3, 'new_york': 2, 'military_zone': 1}


def reservation_visuals(arena, ground_id):
    """Bind isolated client art after validating the original game layout."""
    policy = json.loads((ROOT/'config/reservation_visuals.json').read_text())
    if policy['version'] != 1:
        raise ValueError('Unsupported Reservation visuals version')
    brush = policy['ground_ids'][str(ground_id)]
    if type(brush) is not int or not 0 <= brush <= 255:
        raise ValueError('Invalid Reservation ground brush')
    entries = tuple(replace(e, name=policy['entries'][e.name.decode('ascii')].encode('ascii'))
                    for e in arena.ground.entries)
    return replace(arena, ground=replace(arena.ground, entries=entries,
                       first_layer=bytes([brush])*(arena.ground.width*arena.ground.height)))


@dataclass(frozen=True)
class GeneratedMap:
    arena: ArenaMap
    seed: int
    profile: str
    layout: dict
    patrol: tuple
    variant: str = 'classic'
    surroundings: dict | None = None


def reachable_cells(arena):
    start = arena.player_spawns[0]
    reached = {start}
    pending = deque([start])
    while pending:
        x, y = pending.popleft()
        for cell in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
            if (0 <= cell[0] < arena.ground.width and 0 <= cell[1] < arena.ground.height
                    and cell not in arena.blocked and cell not in reached):
                reached.add(cell)
                pending.append(cell)
    return reached


def connected(arena, reached):
    return (all(p in reached for p in arena.player_spawns + arena.bot_spawns)
            and all(any((x+dx,y+dy) in reached for dx,dy in ((-1,0),(1,0),(0,-1),(0,1)))
                    for x,y in arena.containers))


def generate_map(profile='reservation', *, seed=None, deployment_size=3, mode=0, variant=None,map_size=None,profiles_path=None,profiles_data=None):
    if profile=='detroit' and profiles_path is None and profiles_data is None:
        if variant is not None:
            raise ValueError('Detroit uses its original small/large map resources; custom variants are unavailable')
        from .world_completion import generate_world_map
        return generate_world_map(18,seed=seed,deployment_size=deployment_size,mode=mode,map_size=map_size)
    limit = 8 if profiles_path is not None or profiles_data is not None else 6
    if type(deployment_size) is not int or not 1 <= deployment_size <= limit:
        raise ValueError('Deployment size must be between one and ' + str(limit))
    if type(mode) is not int or mode not in (0,1,4,7):
        raise ValueError('Unsupported map battle mode')
    if profiles_path is not None and profiles_data is not None:
        raise ValueError('Supply one map profile source')
    profiles = (profiles_data if profiles_data is not None else json.loads(
        (Path(profiles_path) if profiles_path is not None else ROOT/'config/battle_map_profiles.json').read_text()))['profiles']
    policy = profiles.get(profile)
    if not policy or not policy['enabled']:
        raise ValueError('Battle map profile is unavailable')
    seed = secrets.randbits(64) if seed is None else seed
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError('Expected unsigned 64-bit map seed')
    rng = random.Random(seed)
    fragments = json.loads((ROOT/'config/arena_fragments.json').read_text())
    w, h = policy['width'], policy['height']
    large = mode in policy.get('large_modes',())
    if map_size is not None:
        if type(map_size) is not int or not 1 <= map_size <= 4:
            raise ValueError('Invalid custom battle map size')
        wager_policy=json.loads((ROOT/'config/wagers.json').read_text())
        numerator,denominator=wager_policy['map_scales'][str(map_size)]
        w,h=w*numerator//denominator,h*numerator//denominator
        large=map_size>=3
    elif large:
        numerator, denominator = policy['large_scale']
        w, h = w*numerator//denominator, h*numerator//denominator
    variants = policy.get('variants',())
    selected = next((v for v in variants if v['name']==variant),None) if variant is not None else (rng.choice(variants) if variants else None)
    if variant is not None and selected is None:
        raise ValueError('Unknown map variant')
    ground_id = rng.choice(policy['ground_ids']) if 'ground_ids' in policy else policy['ground_id']
    ground_id = CITY_GROUND_BRUSH_IDS.get(profile, ground_id)
    ground_brush = CITY_GROUND_BRUSH_IDS.get(profile, policy.get('ground_brush_id', ground_id))
    for attempt in range(64):
        # Opposite edges with a clear deployment pocket. Asset orientation is
        # selected via original variants; never rotate an unrotated .s model.
        horizontal = rng.choice((True, False))
        extent = h if horizontal else w
        margin = max(6, deployment_size)
        if extent <= 2*margin:
            raise ValueError('Map is too small for deployment')
        centers = (rng.randrange(margin, extent-margin), rng.randrange(margin, extent-margin))
        sides = []
        for edge, center in zip((2, (w if horizontal else h)-3), centers):
            offsets = (-2, 0, 2) if deployment_size == 3 else tuple(2*i-deployment_size+1 for i in range(deployment_size))
            sides.append(tuple((edge, center+d) if horizontal else (center+d, edge)
                               for d in offsets))
        if rng.choice((True, False)):
            sides.reverse()
        reserved = {(x+dx,y+dy) for side in sides for x,y in side
                    for dx in range(-2,3) for dy in range(-2,3)}
        names = []
        if selected:
            for category, counts in selected['counts'].items():
                count = rng.randint(*counts)
                # More scenery on larger fields; container rewards are not scaled.
                if large and category not in ('crates',):
                    count += count//2
                names.extend(rng.choice(policy['pools'][category]) for _ in range(count))
            if large:
                names.append(rng.choice(policy['pools']['large_walls']))
        else:
            for category, count_key in (('houses','house_count'), ('hangars','hangar_count'),
                                        ('walls','wall_count'), ('cover','cover_count'), ('crates','crate_count')):
                names.extend(rng.choice(policy[category]) for _ in range(rng.randint(*policy[count_key])))
        names.sort(key=lambda n: fragments[n]['width']*fragments[n]['height'], reverse=True)
        objects = []
        for name in names:
            fw, fh = fragments[name]['width'], fragments[name]['height']
            candidates = [(x,y) for x in range(1,w-fw) for y in range(1,h-fh)]
            rng.shuffle(candidates)
            for x,y in candidates:
                cells = {(i,j) for i in range(x,x+fw) for j in range(y,y+fh)}
                if cells & reserved:
                    continue
                objects.append(dict(file=name, x=x, y=y))
                # Leave at least one free cell between fragment reservations.
                reserved.update((i,j) for i in range(x-1,x+fw+1) for j in range(y-1,y+fh+1))
                break
            else:
                break
        if len(objects) != len(names):
            continue
        layout = dict(width=w, height=h, ground_id=ground_id, ground_brush_id=ground_brush,
                      player_spawns=sides[0], bot_spawns=sides[1], objects=objects)
        arena = build_arena_map(layout, fragments, max_deployment=limit)
        reached = reachable_cells(arena)
        if not connected(arena, reached):
            continue
        # Public scene waypoints, independent of hidden enemy positions.
        targets = ((w//2,h//2), (w//4,h//4), (3*w//4,h//4), (3*w//4,3*h//4), (w//4,3*h//4))
        ordered = sorted(reached)
        patrol = tuple(dict.fromkeys(min(ordered, key=lambda p: abs(p[0]-x)+abs(p[1]-y)) for x,y in targets))
        if profile == 'reservation':
            arena = reservation_visuals(arena, ground_id)
        # Decorative city panoramas are authored for 38/57 cells. Custom
        # wager maps still use the city's original terrain/building fragments;
        # attaching a panorama of another size would misalign its boundary.
        surroundings=None
        if map_size is None or w in (38,57) and h==w:
            arena, surroundings = add_arena_surroundings(arena, profile, seed, mode=mode,
                                                         config_path=ROOT/'config/arena_surroundings.json')
        return GeneratedMap(arena, seed, profile, layout, patrol,
                            selected['name'] if selected else 'classic', surroundings)
    raise ValueError('Could not generate a connected battle map within 64 attempts')
