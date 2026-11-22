"""Rank affordable arena turn plans using the bot's current observation."""
from collections.abc import Callable
from copy import copy
from dataclasses import dataclass, replace
from functools import cache
from heapq import nlargest, nsmallest

from .armor import mitigate
from .battle_item_effects import can_observe
from .battle_state import BattleActor, BattleField
from .bot_finishing import forecast, MAX_ATTACKS
from .combat import MEDICAL_ITEMS
from .combat_distance import combat_distance, rounded_radius_squared
from .control_points import ControlPoints
from .protocol.item_list import ItemRecord
from .tactical_bot import can_fire, items_for, medical_item, path_to, routes, weapon_for
from .visibility import field_sight

Cell = tuple[int, int]
NOMINAL_REPLY_AP = 15
REPLY_MOVE_STEPS = 7
REPLY_POSITIONS = 12
FIRING_POSITIONS = 10
AP_COST = .0002
DAMAGE_WEIGHT = 1.5
KILL_WEIGHT = 1.4
REPLY_WEIGHT = .7
EXPOSURE_COST = .28
HIDDEN_REPLY_WEIGHT = .55
GUARD_RADIUS = 6


@dataclass(frozen=True)
class TurnObjective:
    points: ControlPoints
    seconds_left: float
    recent_enemies: tuple[BattleActor, ...] = ()


@dataclass(frozen=True)
class TurnPlan:
    before: tuple[Cell, ...]
    target: int | None = None
    shots: int = 0
    after: tuple[Cell, ...] = ()
    medical: ItemRecord | None = None


def expected_reply(field: BattleField, identity: int, known: frozenset[int],
                   recent_enemies: tuple[BattleActor, ...] = ()) -> Callable[[Cell], dict[int, float]]:
    actor = field.actor(identity)
    combat = field.combat
    catalog = combat.catalog
    defense = combat.defense(identity)
    opponents = []
    observed = [field.actor(i) for i in sorted(known)]
    remembered = [enemy for enemy in recent_enemies if enemy.actor_id not in known]
    for enemy in (*observed, *remembered):
        if not enemy.health or field.allied(actor.owner_id, enemy.owner_id):
            continue
        enemy_id = enemy.actor_id
        weapon = enemy.weapons[0] if enemy.weapons else catalog.weapons[300]
        budget = min(REPLY_MOVE_STEPS, (NOMINAL_REPLY_AP - weapon.attack_ap) // field.step_cost)
        _, depth = routes(field, enemy_id, known - {identity}, max(0, budget), start=(enemy.x, enemy.y))
        positions = tuple((position, (NOMINAL_REPLY_AP - steps * field.step_cost) // weapon.attack_ap)
                          for position, steps in depth.items())
        opponents.append((enemy, weapon, positions, 1 if enemy_id in known else .85))

    # shortcut: approximate one reply with the visible weapon and standard AP; model more actions if replays show systematic errors.
    @cache
    def shot_damage(template: int, distance: int) -> float:
        low, high = catalog.distance_damage(template, distance)
        return mitigate((low + high) // 2, defense)[0] * catalog.accuracy(template, distance) / 100

    @cache
    def relative_distance(dx: int, dy: int) -> int:
        return combat_distance((0, 0), (dx, dy))

    @cache
    def estimate(cell: Cell) -> dict[int, float]:
        target = replace(actor, x=cell[0], y=cell[1])
        incoming = {}
        for enemy, weapon, positions, confidence in opponents:
            enemy_id = enemy.actor_id
            limit = min(weapon.max_range, enemy.sight_radius)
            if not limit:
                incoming[enemy_id] = 0.0
                continue
            origin = (enemy.x, enemy.y)
            distance = combat_distance(origin, cell)
            direct = (NOMINAL_REPLY_AP // weapon.attack_ap * shot_damage(weapon.template_id, distance)
                      if 0 < distance <= limit and can_fire(field, origin, target, weapon) else 0.0)
            sight_limit = rounded_radius_squared(limit)
            options = []
            for position, shots in positions:
                dx, dy = abs(position[0]-cell[0]), abs(position[1]-cell[1])
                if shots and 0 < dx*dx + dy*dy <= sight_limit:
                    damage = shots * shot_damage(weapon.template_id, relative_distance(dx, dy))
                    if damage > direct:
                        options.append((damage, position))
            best = nlargest(REPLY_POSITIONS, options)
            reachable = next((damage for damage, cell_from in best if can_fire(field, cell_from, target, weapon)), direct)
            incoming[enemy_id] = confidence * reachable
        return incoming

    return estimate


def choose_plan(field: BattleField, identity: int, known: frozenset[int], objective: TurnObjective) -> TurnPlan | None:
    actor = field.actor(identity)
    weapon = weapon_for(field, identity)
    if weapon is None or weapon.template_id in (300, 337):
        return None
    budget = actor.action_points
    step = field.step_cost
    origin = (actor.x, actor.y)
    previous, depth = routes(field, identity, known, budget // step)
    enemies = tuple(field.actor(i) for i in sorted(known)
                    if field.actor(i).health and not field.allied(actor.owner_id, field.actor(i).owner_id))
    points = objective.points
    side = field.teams[actor.owner_id]
    (flag,) = points.positions
    (flag_owner,) = points.owners
    lead = points.scores[side] - points.scores[1-side]
    # Reverse reachability rewards routes around walls even when the next step moves away from the flag.
    _, flag_steps = routes(field, identity, frozenset(), field.width + field.height, start=flag)
    reply = expected_reply(field, identity, known, objective.recent_enemies)
    allies = tuple(field.actor(i) for i in known if i != identity and field.actor(i).health
                   and field.allied(actor.owner_id, field.actor(i).owner_id))
    flag_held = any(abs(a.x-flag[0])+abs(a.y-flag[1]) <= points.radius for a in allies)
    urgency = 0.34 + (0.25 if lead < 0 and objective.seconds_left < 150 else 0)
    secure = flag_owner == side or flag_held
    if secure:
        urgency *= .15
    if lead > 0 and objective.seconds_left < 90:
        urgency *= .35
    health_scale = max(1, actor.max_health)
    health_fraction = actor.health / health_scale
    recent = tuple(a for a in objective.recent_enemies if a.actor_id not in known and a.health)
    observers = enemies + recent
    sight_field = copy(field)
    sight_field._actors = {a.actor_id: a for a in observers}

    # Use public approaches to pick a covered post before the enemy is seen.
    approaches = ()
    if secure and not observers:
        outer = tuple(cell for cell, distance in flag_steps.items() if 6 <= distance <= 10)
        if outer:
            x, y = flag
            goals = ((x-8, y), (x+8, y), (x, y-8), (x, y+8))
            approaches = tuple(dict.fromkeys(min(outer, key=lambda cell: combat_distance(cell, goal))
                                             for goal in goals))
    flag_cells = tuple(cell for cell, distance in flag_steps.items()
                       if 0 < distance <= points.radius and abs(cell[0]-flag[0])+abs(cell[1]-flag[1]) <= points.radius)

    @cache
    def exposure(cell: Cell) -> frozenset[int]:
        target = replace(actor, x=cell[0], y=cell[1])
        return frozenset(enemy.actor_id for enemy in observers
                         if can_observe(field.combat, enemy, target, field=sight_field))

    @cache
    def guard_value(cell: Cell) -> float:
        if not approaches or flag_steps.get(cell, GUARD_RADIUS+1) > GUARD_RADIUS:
            return 0.0
        if not any(field_sight(field, cell, point) for point in flag_cells):
            return 0.0
        return .16 * sum(not field_sight(field, start, cell) for start in approaches) / len(approaches)

    @cache
    def position_value(cell: Cell, target: int | None = None, kill_chance: float = 0) -> float:
        watching = exposure(cell)
        exposed = max((1 - kill_chance if enemy_id == target else 1 for enemy_id in watching), default=0)
        danger = sum(damage * (1 - kill_chance if enemy_id == target else 1)
                     for enemy_id, damage in reply(cell).items()) / health_scale
        on_flag = abs(cell[0]-flag[0])+abs(cell[1]-flag[1]) <= points.radius
        distance = flag_steps.get(cell, field.width + field.height)
        lethal = max(0, danger - health_fraction * .8)
        # shortcut: fog reduces the chance of a aimed reply; use replayed pursuit if players reliably predict hidden endpoints.
        response = danger * (HIDDEN_REPLY_WEIGHT + (1 - HIDDEN_REPLY_WEIGHT) * exposed)
        cover_cost = EXPOSURE_COST * exposed * min(1, danger / .25)
        progress = float(on_flag and not secure) + .7 / (1 + distance / 5)
        return urgency * progress + guard_value(cell) - REPLY_WEIGHT * response - cover_cost - lethal

    def move_value(cell):
        # A recalled position is a place to look, never an authorized target.
        scouting = not enemies and depth[cell]*step+weapon.attack_ap <= budget and any(
            can_fire(field, cell, opponent, weapon) for opponent in recent)
        return position_value(cell) + .18 * scouting - AP_COST * depth[cell]

    move = max(depth, key=move_value)
    best = TurnPlan(path_to(previous, move))
    best_value = move_value(move)
    medicine = medical_item(field, identity)
    if medicine is not None:
        amount, ap = MEDICAL_ITEMS[medicine.template_id][:2]
        cell = max((cell for cell in depth if depth[cell]*step+ap <= budget), key=position_value)
        value = position_value(cell) + min(amount, actor.max_health-actor.health) / health_scale
        if value > best_value:
            best, best_value = TurnPlan(path_to(previous, cell), medical=medicine), value

    ammo = MAX_ATTACKS
    if weapon.ammo_id is not None:
        ammo = min(ammo, sum(i.count for i in items_for(field, identity) if i.template_id == weapon.ammo_id)
                   // weapon.bullets_count)
    for target in enemies:
        cells = (cell for cell in depth if depth[cell]*step + weapon.attack_ap <= budget)
        # Choose both low-cost and promising firing positions before checking sight rays.
        positions = nsmallest(48, cells,
                              key=lambda cell: (depth[cell] + combat_distance(cell, (target.x,target.y)), cell))
        firing = tuple(cell for cell in positions if can_fire(field, cell, target, weapon))[:FIRING_POSITIONS]
        distributions = {}
        for cell in firing:
            distance = combat_distance(cell, (target.x,target.y))
            if distance not in distributions:
                distributions[distance] = forecast(field, identity, cell, target, weapon)
            distribution = distributions[distance]
            mean_damage = sum(min(damage, target.health)*chance for damage, chance in distribution)
            if not mean_damage:
                continue
            left = budget - depth[cell]*step
            maximum = min(ammo, left // weapon.attack_ap)
            after_prev, after_depth = routes(field, identity, known, (left - weapon.attack_ap)//step, start=cell)
            for shots in dict.fromkeys((1, (1+maximum)//2, maximum)):
                # Lower bound: every shot reaches its share of the remaining HP.
                kill_chance = sum(chance for damage,chance in distribution if damage*shots >= target.health)**shots
                cost = shots * weapon.attack_ap
                end = max((end for end in after_depth if after_depth[end]*step+cost <= left),
                          key=lambda end: (position_value(end, target.actor_id, kill_chance), -after_depth[end]))
                damage = min(target.health, mean_damage * shots) / max(health_scale, target.max_health)
                value = position_value(end, target.actor_id, kill_chance) + DAMAGE_WEIGHT*damage + KILL_WEIGHT*kill_chance
                value -= AP_COST * (depth[cell] + cost + after_depth[end])
                if value > best_value:
                    best_value = value
                    best = TurnPlan(path_to(previous, cell), target.actor_id, shots, path_to(after_prev, end))
    return best
