"""Mine hunters with personal perception and journal-compatible memory.

This is emulator policy, not a recovered original server algorithm. Decisions
use only observed enemies, last seen cells and the actor's current AP/weapon.
All movement and damage still pass through the authoritative arena APIs.
"""
from collections import deque

MEMORY_TURNS = 3


def _waypoints(region, home, distances=None):
    distances = distances or {p: abs(p[0]-home[0])+abs(p[1]-home[1]) for p in region}
    selected = [max(region, key=lambda p: (distances[p], p))]
    for _ in range(2):
        candidates = set(region) - set(selected) - {home}
        if not candidates:break
        point = max(candidates, key=lambda p: (
            min(abs(p[0]-q[0])+abs(p[1]-q[1]) for q in (*selected, home)), distances[p], p))
        if min(abs(point[0]-q[0])+abs(point[1]-q[1]) for q in (*selected, home)) < 2:break
        selected.append(point)
    return tuple(p for p in selected if p != home) + (home,)


def _new_state():
    return dict(mode='patrol', target_id=None, last_seen=None, last_seen_turn=None, search_index=0)


def configure_patrols(field, actor_ids, *, radius=6):
    """Give each mutant its own connected neighbourhood around its spawn."""
    field.individual_bot_sight = frozenset(actor_ids)
    field.bot_patrol_waypoints = {}
    field.bot_patrol_regions = {}
    field.mine_hunter_state = {}
    field.patrol_progress = {}
    for identity in field.individual_bot_sight:
        actor = field.actor(identity)
        home = (actor.x, actor.y)
        distances = {home: 0}
        queue = deque([home])
        while queue:
            x, y = queue.popleft()
            if distances[x, y] >= radius:
                continue
            for cell in ((x-1, y), (x, y-1), (x, y+1), (x+1, y)):
                if cell in distances or cell in field.blocked or not field.inside(*cell):
                    continue
                distances[cell] = distances[x, y] + 1
                queue.append(cell)
        field.bot_patrol_regions[identity] = frozenset(distances)
        field.bot_patrol_waypoints[identity] = _waypoints(distances, home, distances)
        field.mine_hunter_state[identity] = _new_state()


def ensure_hunters(field, actor_ids):
    """Upgrade old saved mines in place, retaining spawn regions and bonuses."""
    if not hasattr(field, 'mine_hunter_state'):
        field.mine_hunter_state = {}
        for identity, points in getattr(field, 'bot_patrol_waypoints', {}).items():
            region = field.bot_patrol_regions.get(identity)
            if region and points:
                field.bot_patrol_waypoints[identity] = _waypoints(region, points[-1])
    for identity in actor_ids:field.mine_hunter_state.setdefault(identity, _new_state())
    updates = ()
    mine = getattr(field, 'mining', None)
    if (getattr(mine, 'shared', False) and
            not getattr(field, 'mine_mutant_sight_version', 0)):
        from .battle_item_effects import initialize, refresh_sight, rules
        state = initialize(field.combat)
        penalty = getattr(field, 'item_dark_sight_penalty', rules()['policy']['dark_sight_penalty'])
        for identity in field.individual_bot_sight:
            if identity in state['base_sight']:
                state['base_sight'][identity] = min(255, state['base_sight'][identity] + penalty)
        updates = refresh_sight(field.combat)
        field.mine_mutant_sight_version = 1
    return updates


def _route(field, actor_id, known, goals, *, allowed=None, unavailable=()):
    actor = field.actor(actor_id);start = (actor.x, actor.y)
    occupied = {(field.actor(i).x, field.actor(i).y) for i in known
                if i != actor_id and field.actor(i).health != 0}
    blocked = field.blocked | occupied | frozenset(unavailable)
    goals = set(goals) - blocked
    if start in goals:return ()
    if not goals:return None
    previous = {start: None};queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for cell in ((x-1,y), (x,y-1), (x,y+1), (x+1,y)):
            if cell in previous or cell in blocked or not field.inside(*cell):continue
            if allowed is not None and cell not in allowed:continue
            previous[cell] = (x,y)
            if cell in goals:
                path = []
                while cell != start:
                    path.append(cell);cell = previous[cell]
                return tuple(reversed(path))
            queue.append(cell)
    return None


def _attack_cells(field, actor, target, weapon):
    from .combat_distance import combat_distance
    from .visibility import field_sight
    from .battle_item_effects import clear_item_sight
    span = weapon.max_range
    for x in range(max(0,target.x-span), min(field.width,target.x+span+1)):
        for y in range(max(0,target.y-span), min(field.height,target.y+span+1)):
            if (1 <= combat_distance((x,y),(target.x,target.y)) <= span and
                    field_sight(field,(x,y),(target.x,target.y)) and
                    clear_item_sight(field.combat,(x,y),(target.x,target.y))):
                yield (x,y)


def _choose_target(field, actor_id, enemies, known, state, unavailable):
    actor = field.actor(actor_id)
    weapon = actor.weapons[0] if actor.weapons else None
    if weapon is None:return None
    choices = []
    for target in enemies:
        path = _route(field,actor_id,known,_attack_cells(field,actor,target,weapon),unavailable=unavailable)
        if path is None:continue
        cost = len(path)*field.step_cost
        hits = max(0,actor.action_points-cost)//weapon.attack_ap
        choices.append(((-hits, cost, target.actor_id != state['target_id'], target.health, target.actor_id), target, path))
    return min(choices, key=lambda c:c[0])[1:] if choices else None


def _attack(arena, owner, actor_id, target, view):
    from .protocol.battle_attack import AttackRequest
    from .training_bot import attack_for_view
    replies = attack_for_view(arena, owner, AttackRequest(actor_id, target.x, target.y), view)
    return (False, ()) if replies is None else (True, replies)


def play_hunter(arena, room_id, owner, actor_id, *, view=None):
    """Replan after each action, without spending AP on failed plans."""
    from .training_bot import bot_known
    from .protocol.battle_move import BattleMove, encode_move_request
    from .protocol.action_points import encode_action_points
    field = arena._fields[room_id];state = field.mine_hunter_state[actor_id]
    generation = field._ability_turns[actor_id]
    packets = [];unavailable = set();visited = set()
    # AP is byte-sized. The cap also bounds blocked routes/search transitions.
    for _ in range(512):
        turn = arena._turns.get(room_id)
        if turn is None or turn[0] != owner or arena._clock() >= turn[2]:break
        actor = field.actor(actor_id)
        if not actor.health or actor.action_points <= 0:break
        known = bot_known(field,owner,actor_id)
        enemies = [field.actor(i) for i in sorted(known) if field.actor(i).health and
                   not field.allied(field.actor(i).owner_id,owner)]
        choice = _choose_target(field,actor_id,enemies,known,state,unavailable)
        if choice is not None:
            target, path = choice
            state.update(target_id=target.actor_id,last_seen=(target.x,target.y),
                         last_seen_turn=generation,search_index=0,mode='pursuit' if path else 'attack')
            if not path:
                if actor.action_points < actor.weapons[0].attack_ap:break
                success, updates = _attack(arena,owner,actor_id,target,view)
                if not success:break
                packets.extend(updates)
                if field.actor(target.actor_id).health == 0:
                    state.update(target_id=None,last_seen=None,last_seen_turn=None,mode='return')
                continue
        else:
            # An observed but unreachable opponent still leaves honest memory.
            if enemies:
                target = next((e for e in enemies if e.actor_id == state['target_id']), enemies[0])
                state.update(target_id=target.actor_id,last_seen=(target.x,target.y),
                             last_seen_turn=generation,search_index=0)
                # No reachable attack position exists. Keep the observation,
                # rather than pacing around an enemy we cannot reach.
                state['mode'] = 'pursuit'
                break
            age = None if state['last_seen_turn'] is None else generation-state['last_seen_turn']
            if age is not None and age <= MEMORY_TURNS:
                x,y = state['last_seen'];state['mode'] = 'search'
                points = ((x,y),(x-1,y),(x,y-1),(x+1,y),(x,y+1),
                          (x-2,y),(x,y-2),(x+2,y),(x,y+2))
                path = None
                while state['search_index'] < len(points):
                    goal = points[state['search_index']]
                    if field.inside(*goal):path = _route(field,actor_id,known,(goal,),unavailable=unavailable)
                    if path:break
                    state['search_index'] += 1
                if not path:break
            else:
                if state['target_id'] is not None:
                    state.update(target_id=None,last_seen=None,last_seen_turn=None,search_index=0,mode='return')
                waypoints = getattr(field,'bot_patrol_waypoints',{}).get(actor_id,())
                if not waypoints:break
                region = getattr(field,'bot_patrol_regions',{}).get(actor_id)
                if region is not None and (actor.x,actor.y) not in region:
                    state['mode'] = 'return'
                    path = _route(field,actor_id,known,(waypoints[-1],),unavailable=unavailable)
                else:
                    state['mode'] = 'patrol'
                    if not hasattr(field,'patrol_progress'):field.patrol_progress = {}
                    index = field.patrol_progress.get(actor_id,0)%len(waypoints)
                    path = None
                    while index not in visited:
                        path = _route(field,actor_id,known,(waypoints[index],),allowed=region,unavailable=unavailable)
                        if path:break
                        visited.add(index);index = (index+1)%len(waypoints)
                    field.patrol_progress[actor_id] = index
                if not path:break
        if actor.action_points < field.step_cost:break
        cell = path[0]
        actors_before = dict(field._actors) if view is not None else None
        visible_before = None if view is None else view.visible
        try:
            packet = arena.move(owner,encode_move_request(BattleMove(actor_id,(cell,))))
        except ValueError:
            # Collision is a local observation, never a query of hidden actors.
            unavailable.add(cell)
            continue
        replies = (packet,) if isinstance(packet,bytes) else tuple(packet)
        if view is None:
            packets.extend((*replies,encode_action_points(actor_id,field.actor(actor_id).action_points)))
        else:
            from server.battle_events import project_action
            packets.extend(project_action(view,owner,actors_before,visible_before,replies))
    return tuple(packets)
