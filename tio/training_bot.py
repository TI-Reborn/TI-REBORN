"""Deterministic training movement through the same authoritative move API.

Ordinary arena bots use tactical inventory/combat planning. Mine hunters retain
their individual patrol policy. Every action uses the authoritative services.
"""
from collections import deque
from typing import TYPE_CHECKING

from .combat_distance import rounded_radius_squared
from .protocol.battle_attack import (
    AttackRequest, decode_attack_result, encode_attack_request, encode_attack_result,
)
from .protocol.battle_move import BattleMove, encode_move_request
from .protocol.action_points import encode_action_points
from .protocol.battle_turn import encode_end_turn
from .protocol.health import encode_health
from .visibility import VisibilityView, field_sight, visible_actors, visible_attack

if TYPE_CHECKING:
    from .arena_service import ArenaService


def bot_known(field, owner, actor_id):
    if actor_id not in getattr(field, 'individual_bot_sight', ()):
        return visible_actors(field, owner)
    observer = field.actor(actor_id)
    combat = getattr(field, 'combat', None)
    if combat is not None:
        from .battle_item_effects import can_observe
        return frozenset(a.actor_id for a in field._actors.values()
                         if field.allied(a.owner_id, owner) or
                         (a.health != 0 and can_observe(combat, observer, a)))
    return frozenset(a.actor_id for a in field._actors.values()
                     if field.allied(a.owner_id, owner) or
                     (observer.health != 0 and a.health != 0 and
                      (observer.x-a.x)**2 + (observer.y-a.y)**2 <= rounded_radius_squared(observer.sight_radius) and
                      field_sight(field, (observer.x, observer.y), (a.x, a.y))))


def approach_path(field, actor_id, targets, known, *, destination=None, allowed=None):
    """Find the nearest reachable attack-adjacent cell using known occupancy.

    Cardinal movement avoids corner cutting. Unseen actors are not consulted
    here; the authoritative movement API still rejects any occupied cell.
    The range of one cell is a local approach policy, not weapon ballistics.
    """
    actor=field.actor(actor_id)
    start=(actor.x,actor.y)
    occupied={(field.actor(i).x,field.actor(i).y) for i in known
              if i!=actor_id and field.actor(i).health!=0}
    blocked=field.blocked | occupied
    doors=getattr(field,'doors',None)
    if doors is not None and True in doors.permissions.get(actor_id,()):
        blocked=(blocked-frozenset(doors.states))|occupied
    goals={(t.x+dx,t.y+dy) for t in targets for dx,dy in ((-1,0),(0,-1),(0,1),(1,0))
           if field.inside(t.x+dx,t.y+dy) and (t.x+dx,t.y+dy) not in blocked}
    if destination is not None:
        goals={destination} if destination not in blocked else set()
    if start in goals or not goals:return ()
    previous={start:None}
    queue=deque([start])
    while queue:
        x,y=queue.popleft()
        for cell in ((x-1,y),(x,y-1),(x,y+1),(x+1,y)):
            if cell in previous or cell in blocked or not field.inside(*cell):continue
            if allowed is not None and cell not in allowed:continue
            previous[cell]=(x,y)
            if cell in goals:
                path=[]
                while cell!=start:
                    path.append(cell);cell=previous[cell]
                return tuple(reversed(path))
            queue.append(cell)
    return ()


def attack_for_view(arena: 'ArenaService', owner: int, request: AttackRequest,
                    view: VisibilityView | None) -> tuple[bytes, ...] | None:
    """Run a bot attack and project its private scene replies, or return None if rejected."""
    if view is not None:
        visible_before = view.visible
        registered_hidden = view.hidden_living.keys() | view.resident_corpses
        shooter_visible = request.actor_id in visible_before
        health_before = {i: view.field.actor(i).health for i in visible_before} if not shooter_visible else {}
    try:
        replies = arena.attack(owner, encode_attack_request(request), view=view)
    except ValueError:
        return None
    if view is None:
        return replies
    packets = []
    hit_updates = set()
    for reply in replies:
        if reply[0] == 0x4b:
            shown = visible_attack(decode_attack_result(reply), visible_before, registered_hidden)
            if shown is not None:
                packets.append(encode_attack_result(shown))
                hit_updates.update(hit.actor_id for hit in shown.hits)
        elif reply[0] in (0x3b, 0x43, 0x44) or (reply[0] == 0x4e and shooter_visible):
            packets.append(reply)
    packets.extend(encode_health(i, view.field.actor(i).health) for i, hp in health_before.items()
                   if i in view.visible and i not in hit_updates and view.field.actor(i).health != hp)
    packets.extend(view.refresh())
    return tuple(packets)


def play_turn(arena, room_id, bot_owner, *, view=None, objective=None):
    field = arena._fields[room_id]
    room = next(r for r in arena.rooms.snapshot() if r.room_id == room_id)
    actors = field.living_actor_ids(bot_owner)
    hunters = tuple(i for i in actors if i in getattr(field, 'individual_bot_sight', ()))
    hunter_updates = ()
    if hunters:
        from .mining_ai import ensure_hunters
        hunter_updates = ensure_hunters(field, hunters)
    updates=arena.begin_turn_packets(bot_owner,actors,40)[:-1]
    packets=list(updates) if view is None else list(view.refresh())
    packets.extend(p for p in hunter_updates if view is None or int.from_bytes(p[1:5],'little') in view.visible)
    if view is not None:
        packets.extend(encode_action_points(i,field.actor(i).action_points) for i in actors if i in view.visible)
    for actor_id in actors:
        actor = field.actor(actor_id)
        if actor.health == 0: continue
        if actor_id in hunters:
            from .mining_ai import play_hunter
            packets.extend(play_hunter(arena, room_id, bot_owner, actor_id, view=view))
            if room_id not in arena._turns:return tuple(packets)
            continue
        if getattr(field,'combat',None) is not None:
            from .tactical_bot import play_actor
            packets.extend(play_actor(arena, room_id, bot_owner, actor_id, view=view, objective=objective))
            if room_id not in arena._turns:return tuple(packets)
            continue
        known=bot_known(field,bot_owner,actor_id)
        enemies = [field.actor(i) for member in room.members if not field.allied(member,bot_owner)
                   for i in field.actor_ids(member) if field.actor(i).health != 0 and i in known]
        if enemies:
            path=approach_path(field,actor_id,enemies,known)
        else:
            waypoints=getattr(field,'bot_patrol_waypoints',{}).get(actor_id,getattr(field,'patrol_waypoints',()))
            region=getattr(field,'bot_patrol_regions',{}).get(actor_id)
            # A pursuer outside its patrol area returns by an ordinary route.
            if region is not None and (actor.x,actor.y) not in region:region=None
            if not waypoints:continue
            if not hasattr(field,'patrol_progress'):field.patrol_progress={}
            index=field.patrol_progress.get(actor_id,0)
            path=()
            for _ in waypoints:
                target=waypoints[index % len(waypoints)]
                path=approach_path(field,actor_id,(),known,destination=target,allowed=region)
                if path:break
                index+=1
            field.patrol_progress[actor_id]=index
        for x,y in path[:actor.action_points//field.step_cost]:
            # Mine mutants only pursue enemies they personally see.
            now=bot_known(field,bot_owner,actor_id)
            if enemies and not any(e.actor_id in now for e in enemies):break
            if not enemies and any(not field.allied(field.actor(i).owner_id,bot_owner) for i in now):break
            doors=getattr(field,'doors',None)
            if doors is not None and doors.states.get((x,y)) is False:
                from .protocol.battle_door import DoorRequest,encode_door_request
                try:
                    updates=arena.door_action(bot_owner,encode_door_request(DoorRequest(actor_id,True,x,y)))
                except ValueError:break
                if view is None:packets.extend(updates)
                else:packets.extend(view.refresh())
            try: packet = arena.move(bot_owner,encode_move_request(BattleMove(actor_id,((x,y),))))
            except ValueError: break
            before=None if view is None else view.visible
            transitions=() if view is None else view.refresh()
            packets.extend(transitions)
            if view is None or actor_id in before & view.visible:
                packets.extend((packet,encode_action_points(actor_id,field.actor(actor_id).action_points)))
        if getattr(field,'battle_mode',0):
            # New team bots use the same ammo, range, LOS, armour and AP rules
            # as a human. No synthetic damage, teleport or free refill.
            for _ in range(32):
                known=bot_known(field,bot_owner,actor_id)
                targets=sorted((v for v in field._actors.values() if v.health and
                                not field.allied(v.owner_id,bot_owner) and v.actor_id in known),
                               key=lambda v:(abs(v.x-field.actor(actor_id).x)+abs(v.y-field.actor(actor_id).y),v.actor_id))
                for target in targets:
                    replies=attack_for_view(arena,bot_owner,AttackRequest(actor_id,target.x,target.y),view)
                    if replies is None:continue
                    packets.extend(replies)
                    break
                else:break
                if room_id not in arena._turns:return tuple(packets)
    if view is not None:packets.extend(view.refresh())
    if room_id in arena._turns:arena.end_turn(bot_owner,encode_end_turn(actors[0]))
    return tuple(packets)
