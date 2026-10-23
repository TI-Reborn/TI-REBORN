"""Approved emulator cone; damage and recipient-visible stream share geometry.

Five cells long, one-cell half-width at its end, independent of aim distance.
No terrain fire is created. Original direct damage, armor, burn and wear remain
in Combat. The animation event is transient and never stored in checkpoints.
"""
from copy import copy
from math import ceil, hypot, sin
from types import SimpleNamespace
from .combat_distance import combat_distance
from .visibility import field_sight

RANGE = 5
HALF_WIDTH = 1


def cells(field, actor, target):
    dx, dy = target[0]-actor.x, target[1]-actor.y
    if not (dx or dy):
        return frozenset()
    result = set()
    for y in range(max(0, actor.y-RANGE), min(field.height, actor.y+RANGE+1)):
        for x in range(max(0, actor.x-RANGE), min(field.width, actor.x+RANGE+1)):
            vx, vy = x-actor.x, y-actor.y
            dot, cross = vx*dx+vy*dy, vx*dy-vy*dx
            if (dot > 0 and cross*cross*RANGE*RANGE <= HALF_WIDTH*HALF_WIDTH*dot*dot
                    and combat_distance((actor.x, actor.y), (x, y)) <= RANGE
                    and field_sight(field, (actor.x, actor.y), (x, y))):
                result.add((x, y))
    return frozenset(result)


def victims(field, actor, target):
    area = cells(field, actor, target)
    return sorted((v for v in field._actors.values() if v.health and (v.x, v.y) in area),
                  key=lambda v: (combat_distance((actor.x, actor.y), (v.x, v.y)), v.actor_id))


def visual_packet(view, before, attack):
    from .battle_item_effects import can_observe
    from .protocol.flame_stream import encode_flame_stream
    actor = before.get(attack.actor_id)
    if actor is None:
        return None
    field = copy(view.field)
    field._actors = before
    # Rendering follows a continuous plume. Damage cells above remain the sole
    # combat authority; only walls and recipient visibility constrain the art.
    area = {(x,y) for y in range(max(0,actor.y-RANGE-2),min(field.height,actor.y+RANGE+3))
            for x in range(max(0,actor.x-RANGE-2),min(field.width,actor.x+RANGE+3))
            if (x,y) not in field.blocked and field_sight(field,(actor.x,actor.y),(x,y))}
    observers = [v for v in before.values() if v.health and field.allied(v.owner_id, view.owner)]
    combat = getattr(field, 'combat', None)
    if combat is not None:
        area = {p for p in area if any(can_observe(combat, o, SimpleNamespace(x=p[0], y=p[1]), field=field)
                                       for o in observers)}
    else:
        area = {p for p in area if any((o.x-p[0])**2+(o.y-p[1])**2 <= o.sight_radius**2
                                       and field_sight(field, (o.x,o.y), p) for o in observers)}
    dx, dy = attack.target[0]-actor.x, attack.target[1]-actor.y
    length = hypot(dx, dy)
    if not length:
        return None
    generation = field._ability_turns.get(actor.actor_id, 0)
    token = ((generation & 65535) << 16) | (view.field.actor(actor.actor_id).action_points & 65535)
    phase = ((token ^ actor.actor_id) & 255) * .0245436926
    points = []
    for step in range(1, 25):
        d = .16 + (RANGE-.16) * (step-1) / 23
        for lane in (-1, 0, 1):
            offset = (lane*.72 + .22*sin(phase+step*.51+lane*1.7)) * d/RANGE
            distance = d + .06*sin(phase+step*.83+lane*2.1)
            px = round((actor.x+.5 + (dx*distance-dy*offset)/length)*32)
            py = round((actor.y+.5 + (dy*distance+dx*offset)/length)*32)
            cell = px//32, py//32
            if cell not in area:
                continue
            # A billboard may cross any internal cell edge. Its entire motion
            # envelope must remain within the UNION of visible, unobstructed
            # cells. Inverse isometric projection maps a screen square's half
            # extent to at most 3/4 of its size on either ground axis.
            for size in range(min(32,20+step//2),3,-1):
                radius=ceil(size*.75)
                footprint={(x,y) for y in range((py-radius)//32,(py+radius)//32+1)
                           for x in range((px-radius)//32,(px+radius)//32+1)}
                if footprint <= area:
                    points.append((px,py,size,step))
                    break
    points = tuple(dict.fromkeys(points))
    if not points:
        return None
    return encode_flame_stream(actor.actor_id, token, points)
