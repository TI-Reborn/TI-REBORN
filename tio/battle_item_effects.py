"""Authoritative item effects, staged inventory writes and battle-only timers.

Integration entry points are listed in BATTLE_ITEM_EFFECTS.md. State contains
only snapshot-supported primitives; neither a client option nor a client clock
selects duration, damage, scatter, recipients or booster magnitude. Native33
and49 are existing envelopes. The original binocular GUI route still requires
the separate client adapter described in the catalog extension specification.
"""
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from functools import lru_cache
import json
from pathlib import Path
import time

from .combat_distance import combat_distance
from .protocol.action_points import encode_action_points
from .protocol.battle_attack import AttackResult, AttackHit, encode_attack_result
from .protocol.battle_item_status import encode_sight
from .protocol.health import encode_health
from .protocol.item_list import decode_item_list, encode_item_list
from .visibility import clear_sight, field_sight

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def rules():
    data = json.loads((ROOT / 'config/battle_item_effects.json').read_text(encoding='utf-8'))
    if data['version'] != 1:
        raise ValueError('Unsupported battle item policy')
    required = {'smoke', 'flash', 'binocular', 'suicide', 'champagne', 'vision', 'flare', 'night_vision'}
    if set(data['bindings']) != required or len(set(data['bindings'].values())) != len(required):
        raise ValueError('Ambiguous item bindings')
    for template, row in data['items'].items():
        if not template.isdecimal() or not 1 <= int(template) < 65500:
            raise ValueError('Invalid item template')
        for key in ('ap', 'radius', 'range', 'spread', 'turns', 'cooldown', 'seconds', 'wear'):
            if key in row and (type(row[key]) is not int or row[key] < 1):
                raise ValueError('Invalid item effect rule')
        if row['kind'] == 'booster' and (row['family'] not in ('trainer', 'advisor', 'block_xp')
                                       or type(row['value']) is not int or not 1 <= row['value'] <= 100):
            raise ValueError('Invalid booster')
    return data


def initialize(combat):
    if not hasattr(combat, 'item_effects'):
        combat.item_effects = dict(version=1, sequence=1, base_sight={}, last_sight={},
            flash={}, vision={}, vision_cooldown={}, night_vision={}, areas={},
            recon={}, recon_selection={}, rank_bonus={}, owner_turns={}, last_owner_end={})
    state = combat.item_effects
    if state['version'] != 1:
        raise ValueError('Unsupported saved item effects')
    state.setdefault('owner_turns', {}); state.setdefault('last_owner_end', {})
    state.setdefault('weekly_rank', {})
    for identity, actor in combat.field._actors.items():
        state['base_sight'].setdefault(identity, actor.sight_radius)
        state['last_sight'].setdefault(identity, actor.sight_radius)
    return state


def _atomic(combat, callback, *, views=()):
    """Join the shared journal SQL unit; also support direct atomic service use."""
    initialize(combat)
    from .db_transaction import transaction, key
    paths = {key(path): path for path, _ in combat.persistence.values()}
    if len(paths) > 1:
        raise ValueError('An item action must use one shared authoritative database')
    names = ('inventories', 'proficiencies', 'statistics', 'hazard_damage', 'rank_kills',
             'premium_wear_remainders', 'sight_kill_victims', 'item_effects')
    saved = {name: deepcopy(getattr(combat, name)) for name in names if hasattr(combat, name)}
    actors = dict(combat.field._actors)
    experience = deepcopy(vars(combat.experience))
    achievements = deepcopy(vars(combat.achievements))
    loot = getattr(combat.field, 'loot', None)
    loot_state = None if loot is None else {name: deepcopy(getattr(loot, name))
                                          for name in ('boxes', 'ground')}
    private_view = getattr(combat.field, 'result_view', None)
    all_views = {id(view): view for view in (*views, private_view) if view is not None}
    view_states = [(view, {name: deepcopy(getattr(view, name))
        for name in ('visible', 'hidden_living', 'resident_corpses', 'loot_states', 'door_states', 'templates')})
        for view in all_views.values()]
    rng = combat.rng.getstate() if hasattr(combat.rng, 'getstate') else None
    armor_before={identity:combat.displayed_armor(identity) for identity in combat.inventories if identity in combat.field._actors}
    try:
        with transaction(next(iter(paths.values()))) if paths else nullcontext():
            replies=callback()
            from .armor_display import encode_armor
            armor_updates=tuple(encode_armor(identity,combat.displayed_armor(identity))
                for identity,previous in armor_before.items()
                if identity in combat.field._actors and previous!=combat.displayed_armor(identity))
            return (*replies,*(packet for packet in armor_updates if packet not in replies))
    except BaseException:
        combat.field._actors = actors
        for name, value in saved.items():
            setattr(combat, name, value)
        vars(combat.experience).clear(); vars(combat.experience).update(experience)
        vars(combat.achievements).clear(); vars(combat.achievements).update(achievements)
        if loot_state is not None:
            for name, value in loot_state.items(): setattr(loot, name, value)
        for view, view_state in view_states:
            for name, value in view_state.items(): setattr(view, name, value)
        if rng is not None: combat.rng.setstate(rng)
        raise


def _actor(combat, owner, identity):
    actor = combat.field._actors.get(identity)
    if actor is None or actor.owner_id != owner or not actor.health or identity not in combat.inventories:
        raise ValueError('Living owned combat actor required')
    if not combat.human.get(identity) or combat.resources.get(identity) not in (1, 2, 6):
        raise ValueError('Human combat item user required')
    return actor


def _selected(combat, actor, instance):
    _, items, flag = decode_item_list(combat.inventories[actor.actor_id])
    item = next((i for i in items if i.instance_id == instance), None)
    if item is None or item.count < 1:
        raise ValueError('Owned usable item required')
    return item, items, flag


def _consume(identity, selected, items, flag):
    return encode_item_list(identity, tuple(replace(i, unknown_u32_01=i.count - 1) if i == selected else i
        for i in items if i != selected or i.count > 1), flag)


def _worn_out(identity, selected, items, flag, amount):
    if selected.count != 1 or selected.unknown_words[0] <= 0:
        raise ValueError('Working unstacked optical device required')
    current, maximum, limit = selected.unknown_words
    changed = replace(selected, unknown_words=(max(0, current - amount), maximum, limit))
    special = selected.unknown_bytes_03[2] == 1
    if changed.unknown_words[0] == 0:
        changed = replace(changed, unknown_u8_01=0, location_raw=0) if special else None
    return encode_item_list(identity, tuple(changed if i == selected else i for i in items
        if i != selected or changed is not None), flag)


def _pay(combat, actor, cost, inventory=None, *, trained=None):
    if actor.action_points < cost:
        raise ValueError('Insufficient action points')
    changes = {} if inventory is None else {actor.actor_id: inventory}
    combat._persist_batch(changes, trained=None if trained is None else {actor.actor_id: trained})
    state = replace(actor, action_points=actor.action_points - cost)
    if inventory is not None:
        combat.inventories[actor.actor_id] = inventory
        state = replace(state, weapons=combat.catalog.equipped(inventory,
            human=combat.human[actor.actor_id], resource=combat.resources[actor.actor_id]))
    combat.field._actors[actor.actor_id] = state
    if trained is not None: combat.proficiencies[actor.actor_id] = trained
    return (encode_action_points(actor.actor_id, state.action_points),
            *((combat.inventory_packet(actor.actor_id, inventory),) if inventory is not None else ()))


def is_dark(combat):
    return bool(getattr(combat.field, 'item_darkness', False))


def normal_sight(combat, identity):
    state = initialize(combat)
    value = state['base_sight'][identity]
    if identity in state['vision']: value += rules()['items']['35']['sight_bonus']
    if identity in state['night_vision'] and is_dark(combat): value += 2
    if identity in state['flash']: value = min(value, 4)
    return max(0, min(255, value))


def effective_sight(combat, identity):
    value = normal_sight(combat, identity)
    if is_dark(combat):
        penalty = getattr(combat.field, 'item_dark_sight_penalty', rules()['policy']['dark_sight_penalty'])
        if type(penalty) is not int or not 0 <= penalty <= 255:
            raise ValueError('Invalid authoritative darkness penalty')
        value = max(0, value - penalty)
        # Flash is the final cap; darkness does not reduce that cap itself.
        state = combat.item_effects
        original = state['base_sight'][identity] + int(identity in state['vision'])
        if identity in state['night_vision']: original += 2
        value = max(0, min(255, original - penalty))
        if identity in state['flash']: value = min(value, 4)
    return value


def refresh_sight(combat):
    """Call after kill/equipment deltas, before projecting their packets.

    Existing Combat stages deltas against current sight. Fold that delta into
    the retained base, then reapply blindness/temporary bonuses; expiration
    never loses a kill or equipment change made while sight was capped.
    """
    state = initialize(combat); replies = []
    for identity, actor in sorted(combat.field._actors.items()):
        delta = actor.sight_radius - state['last_sight'][identity]
        if delta:
            state['base_sight'][identity] = max(0, min(255, state['base_sight'][identity] + delta))
        sight = effective_sight(combat, identity)
        if actor.sight_radius != sight:
            combat.field._actors[identity] = replace(actor, sight_radius=sight)
            replies.append(encode_sight(identity, sight))
        state['last_sight'][identity] = sight
    return tuple(replies)


def armor_bonus(combat, identity):
    actor = combat.field._actors.get(identity)
    return 20 if actor is not None and actor.health and identity in initialize(combat)['night_vision'] else 0


def clear_item_sight(combat, start, end):
    """Dynamic smoke only; the caller also applies static field/door geometry."""
    state = initialize(combat); opaque = set()
    for area in state['areas'].values():
        if area['kind'] != 'smoke': continue
        x, y = area['center']; radius = area['radius']
        opaque.update((px, py) for py in range(max(0, y-radius), min(combat.field.height, y+radius+1))
                      for px in range(max(0, x-radius), min(combat.field.width, x+radius+1))
                      if (px-x)**2 + (py-y)**2 <= radius**2)
    if start == end: return True
    return start not in opaque and clear_sight(start, end, opaque)


def can_observe(combat, observer, target, *, field=None):
    """Ordinary sight + illuminated cells within normal sight + coalition recon."""
    if not observer.health: return False
    field = combat.field if field is None else field
    end = (target.x, target.y); start = (observer.x, observer.y)
    if not clear_item_sight(combat, start, end): return False
    state = initialize(combat); distance = (observer.x-target.x)**2 + (observer.y-target.y)**2
    # Long LOS rays are expensive on dense maps. Reject impossible ordinary
    # ranges before tracing, retaining the separate allied recon path below.
    ordinary = distance <= observer.sight_radius**2
    illuminated = (not ordinary and is_dark(combat)
        and distance <= normal_sight(combat, observer.actor_id)**2
        and any(a['kind'] == 'flare' and (target.x-a['center'][0])**2 + (target.y-a['center'][1])**2 <= a['radius']**2
                for a in state['areas'].values()))
    if (ordinary or illuminated) and field_sight(field, start, end): return True
    for recon in state['recon'].values():
        source = field._actors.get(recon['source'])
        if source is None or not source.health or not field.allied(source.owner_id, observer.owner_id): continue
        x, y = recon['center']
        if ((target.x-x)**2 + (target.y-y)**2 <= recon['radius']**2
            and clear_item_sight(combat, (x, y), end) and field_sight(field, (x, y), end)):
            return True
    return False


def visible_actors(combat, owner, *, field=None):
    # Movement projection uses a shallow field copy with replayed coordinates.
    # Its combat reference still points to the live field; use the supplied
    # field rather than silently revealing the actor's final position.
    field = combat.field if field is None else field
    own = [a for a in field._actors.values() if field.allied(a.owner_id, owner)]
    return frozenset(a.actor_id for a in field._actors.values() if a in own
        or any(can_observe(combat, observer, a, field=field) for observer in own))


def attack_template(combat, identity):
    """Suicide jacket takes precedence, including the existing fists fallback."""
    packet = combat.inventories.get(identity)
    if packet is None: return None
    items = decode_item_list(packet)[1]
    jacket = next((i for i in items if i.template_id == 334 and i.equipped and i.client_slot == 4), None)
    if jacket is not None: return 334
    primary = [i for i in items if i.equipped and i.client_slot == 16]
    if len(primary) > 1: raise ValueError('Ambiguous primary weapon')
    if primary and str(primary[0].template_id) in rules()['items']:
        row = rules()['items'][str(primary[0].template_id)]
        if row['kind'] in ('smoke', 'flash', 'flare'): return primary[0].template_id
    return None


def attack(combat, owner, request, *, view=None):
    """Return None for ordinary weapons; parent routes before normal49 damage."""
    template = attack_template(combat, request.actor_id)
    if template is None: return None
    return _atomic(combat, lambda: _attack(combat, owner, request, template, view), views=(view,))


def _attack(combat, owner, request, template, view):
    actor = _actor(combat, owner, request.actor_id); field = combat.field
    if not field.inside(request.x, request.y): raise ValueError('Target outside map')
    row = rules()['items'][str(template)]
    items = decode_item_list(combat.inventories[actor.actor_id])[1]
    selected = next(i for i in items if i.template_id == template and i.equipped
                    and i.client_slot == (4 if template == 334 else 16))
    _, items, flag = _selected(combat, actor, selected.instance_id)
    if selected.unknown_words[0] == 0: raise ValueError('Broken item cannot be used')
    if actor.action_points < row['ap']: raise ValueError('Insufficient action points')
    if template == 334:
        if any(i.equipped and i.client_slot == 16 for i in items):
            raise ValueError('Remove the primary weapon before using a suicide jacket')
        if combat_distance((actor.x, actor.y), (request.x, request.y)) > row['radius']:
            raise ValueError('Suicide activation target is outside its native range')
        if getattr(field, 'practice', None) is not None: raise ValueError('Suicide is unavailable in shooting practice')
        return _suicide(combat, actor, request, selected, items, flag, row, view)
    distance = combat_distance((actor.x, actor.y), (request.x, request.y))
    if not 1 <= distance <= row['range']:
        raise ValueError('Target outside item range')
    if (request.x, request.y) in field.blocked: raise ValueError('Landing cell is blocked')
    accuracy_bonus = combat.weapon_accuracy_bonuses.get(actor.actor_id, {}).get('Throwing', 0)
    accuracy = combat.catalog.accuracy(template, distance, accuracy_bonus) if template in combat.catalog.weapons else max(0, min(95, row['accuracy'] + accuracy_bonus))
    impact = _scatter(combat, (request.x, request.y), {**row, 'accuracy': accuracy})
    inventory = _consume(actor.actor_id, selected, items, flag)
    replies = _pay(combat, actor, row['ap'], inventory, trained=_train_throwing(combat, actor, row['ap']))
    state = combat.item_effects; hits = []
    if row['kind'] == 'flash':
        for victim in field._actors.values():
            if not victim.health or (victim.x-impact[0])**2 + (victim.y-impact[1])**2 > row['radius']**2: continue
            if not clear_sight(impact, (victim.x, victim.y), field.blocked): continue
            state['flash'][victim.actor_id] = max(state['flash'].get(victim.actor_id, 0), field._ability_turns[victim.actor_id] + 1)
            hits.append(AttackHit(victim.actor_id, 0, victim.health))
    else:
        identity = state['sequence']; state['sequence'] += 1
        state['areas'][identity] = dict(kind=row['kind'], center=impact, radius=row['radius'],
            source=actor.actor_id, owner=actor.owner_id,
            expiry=state['owner_turns'].get(actor.owner_id, 0) + row['turns'])
    result = encode_attack_result(AttackResult(actor.actor_id, (actor.x, actor.y),
        (request.x, request.y), template, tuple(hits), impact=impact))
    packets = (result, *replies, *refresh_sight(combat))
    return _equipment_refresh(combat, actor.actor_id, view, packets)


def _train_throwing(combat, actor, ap):
    profile = combat.proficiencies.get(actor.actor_id)
    if profile is None or getattr(combat, 'wager', False): return None
    from .premium import current
    kind = current(*combat.persistence[actor.actor_id])[0] if actor.actor_id in combat.persistence else 0
    multiplier = 1.5 if kind == 1 else 1
    return combat.proficiency_rules.train(profile, True,
        'Throwing', ap, hit=True, multiplier=multiplier)


def _equipment_refresh(combat, identity, view, packets):
    if view is None: return packets
    from .durability import refresh_template
    refresh_template(combat, view, identity)
    if combat.field.actor(identity).health: packets += view.snapshot_packets(identity)
    return (*packets, *view.refresh())


def _scatter(combat, target, row):
    if combat.rng.randrange(100) < row['accuracy']: return target
    field = combat.field; x, y = target; radius = row['spread']
    cells = [(px, py) for py in range(max(0, y-radius), min(field.height, y+radius+1))
             for px in range(max(0, x-radius), min(field.width, x+radius+1))
             if (px, py) != target and (px-x)**2 + (py-y)**2 <= radius**2 and (px, py) not in field.blocked]
    return cells[combat.rng.randrange(len(cells))] if cells else target


def _suicide(combat, actor, request, selected, items, flag, row, view):
    from .battle_hazards import initialize as hazards_initialize, apply_damage
    hazards_initialize(combat)
    inventory = _consume(actor.actor_id, selected, items, flag)
    replies = _pay(combat, actor, row['ap'], inventory, trained=_train_throwing(combat, actor, row['ap']))
    origin = (actor.x, actor.y)
    victims = [a for a in combat.field._actors.values() if a.health
        and (a.x-actor.x)**2 + (a.y-actor.y)**2 <= row['radius']**2
        and clear_sight(origin, (a.x, a.y), combat.field.blocked)]
    def damage(victim):
        if victim.actor_id == actor.actor_id:
            # Inverse of the existing declared armor policy guarantees death.
            return (victim.health * (100 + combat.defense(victim.actor_id)) + 99) // 100
        return row['damage_base'] + combat.rng.randint(0, row['damage_random'])
    damage_packets = apply_damage(combat, actor, 334, origin, victims, damage)
    # apply_damage emitted a centered result. Keep requested coords and actual
    # self-centered impact separate, as with other authoritative projectiles.
    from .protocol.battle_attack import decode_attack_result
    result = decode_attack_result(damage_packets[0])
    result = replace(result, target=(request.x, request.y), impact=origin)
    packets = (encode_attack_result(result), *replies, *damage_packets[1:], *refresh_sight(combat))
    return _equipment_refresh(combat, actor.actor_id, view, packets)


def handles_use(template):
    row = rules()['items'].get(str(template))
    return row is not None and row['kind'] in ('champagne', 'vision', 'night_vision', 'binocular', 'booster')


def use(combat, owner, action, *, now=None):
    return _atomic(combat, lambda: _use(combat, owner, action, time.time() if now is None else now))


def _use(combat, owner, action, now):
    if action.option != 255: raise ValueError('Item use requires unspecified native33 target')
    actor = _actor(combat, owner, action.pet_id)
    selected, items, flag = _selected(combat, actor, action.instance_id)
    row = rules()['items'].get(str(selected.template_id))
    if row is None or not handles_use(selected.template_id): raise ValueError('Unsupported item use')
    state = combat.item_effects; identity = actor.actor_id; generation = combat.field._ability_turns[identity]
    kind = row['kind']
    if kind == 'champagne':
        if actor.health >= actor.max_health: raise ValueError('Health is already full')
        replies = _pay(combat, actor, row['ap'], _consume(identity, selected, items, flag))
        changed = replace(combat.field.actor(identity), health=min(actor.max_health, actor.health + row['heal']))
        combat.field._actors[identity] = changed
        return (encode_health(identity, changed.health), *replies)
    if kind == 'binocular':
        if combat.resources[identity] == 6: raise ValueError('Miner cannot use binoculars')
        if selected.count != 1 or selected.unknown_words[0] <= 0: raise ValueError('Working binocular required')
        state['recon_selection'][identity] = selected.instance_id
        return ()
    if kind == 'vision':
        if generation < state['vision_cooldown'].get(identity, 0): raise ValueError('Vision injection is cooling down')
        replies = _pay(combat, actor, row['ap'], _consume(identity, selected, items, flag))
        state['vision'][identity] = generation + row['turns'] - 1
        state['vision_cooldown'][identity] = generation + row['cooldown']
        return (*replies, *refresh_sight(combat))
    if kind == 'night_vision':
        if identity in state['night_vision']:
            del state['night_vision'][identity]
            return refresh_sight(combat)
        if combat.rank_profiles[identity][0] < row['level']: raise ValueError('Night vision requires level4')
        if not is_dark(combat): raise ValueError('Night vision requires a dark battle')
        replies = _pay(combat, actor, row['ap'], _worn_out(identity, selected, items, flag, row['wear']))
        # The final paid use works for this turn even if its wear destroys the
        # device. The next generation disables the now-missing device.
        state['night_vision'][identity] = dict(instance=selected.instance_id, generation=generation)
        return (*replies, *refresh_sight(combat))
    if getattr(combat, 'wager', False): raise ValueError('Boosters are unavailable in wager battles')
    if identity not in combat.persistence: raise ValueError('Booster requires a persistent owned fighter')
    from .item_boosters import activate
    path, account = combat.persistence[identity]
    from .db_transaction import connect
    db = connect(path)
    try:
        activate(db, account, combat.storage_ids.get(identity, identity), selected.template_id,
                 combat.rank_profiles[identity][0], now)
        return _pay(combat, actor, 0, _consume(identity, selected, items, flag))
    finally: db.close()


def recon_target(combat, owner, request):
    return _atomic(combat, lambda: _recon_target(combat, owner, request))


def _recon_target(combat, owner, request):
    actor = _actor(combat, owner, request.actor_id); state = combat.item_effects
    if not combat.field.inside(request.x, request.y) or (request.x, request.y) in combat.field.blocked:
        raise ValueError('Recon cell is outside map or blocked')
    instance = state['recon_selection'].get(actor.actor_id)
    if instance is None: raise ValueError('Select owned binoculars first')
    selected, items, flag = _selected(combat, actor, instance)
    row = rules()['items'][str(selected.template_id)]
    if row['kind'] != 'binocular': raise ValueError('Selected device is not binoculars')
    replies = _pay(combat, actor, row['ap'], _worn_out(actor.actor_id, selected, items, flag, row['wear']))
    state['recon'][actor.actor_id] = dict(source=actor.actor_id, center=(request.x, request.y),
        radius=row['radius'], expiry=combat.field._ability_turns[actor.actor_id])
    del state['recon_selection'][actor.actor_id]
    return replies


def begin_turn(combat, owner, actor_ids):
    """After prepare_turn restores AP; each actor generation is charged once."""
    def run():
        state = combat.item_effects; replies = []
        for identity in sorted(set(actor_ids)):
            actor = combat.field._actors.get(identity)
            if actor is None or actor.owner_id != owner: raise ValueError('Owned turn actors required')
        for identity in sorted(set(actor_ids)):
            actor = combat.field.actor(identity); active = state['night_vision'].get(identity)
            if active is None: continue
            generation = combat.field._ability_turns[identity]
            if generation <= active['generation']: continue
            selected = next((i for i in decode_item_list(combat.inventories[identity])[1]
                             if i.instance_id == active['instance'] and i.template_id == 5002 and i.unknown_words[0] > 0), None)
            row = rules()['items']['5002']
            if selected is None or not actor.health or not is_dark(combat) or actor.action_points < row['ap']:
                del state['night_vision'][identity]; continue
            selected, items, flag = _selected(combat, actor, selected.instance_id)
            replies.extend(_pay(combat, actor, row['ap'], _worn_out(identity, selected, items, flag, row['wear'])))
            active['generation'] = generation
        return (*replies, *refresh_sight(combat))
    return _atomic(combat, run)


def end_turn(combat, owner, actor_ids):
    return _atomic(combat,lambda:_end_turn(combat,owner,actor_ids))


def _end_turn(combat, owner, actor_ids):
    """Run for ordinary end, timeout and skipped/dead turns before next owner."""
    state = initialize(combat); identities = set(actor_ids)
    for identity in identities:
        actor = combat.field._actors.get(identity)
        if actor is None or actor.owner_id != owner: raise ValueError('Owned turn actors required')
    # Advance once per real actor generation, even when the caster is dead but
    # another fighter of the same owner still receives turns. Duplicate end
    # notifications/timeouts do not shorten an area's lifetime.
    token = max((combat.field._ability_turns[identity] for identity in identities), default=-1)
    if token > state['last_owner_end'].get(owner, -1):
        state['last_owner_end'][owner] = token
        state['owner_turns'][owner] = state['owner_turns'].get(owner, 0) + 1
    for name in ('flash', 'vision'):
        for identity, expiry in tuple(state[name].items()):
            if identity in identities and combat.field._ability_turns[identity] >= expiry: del state[name][identity]
    for identity, effect in tuple(state['areas'].items()):
        source = combat.field._actors.get(effect['source'])
        source_owner = effect.get('owner', None if source is None else source.owner_id)
        living = any(a.owner_id == source_owner and a.health for a in combat.field._actors.values())
        if source_owner is None or not living or state['owner_turns'].get(source_owner, 0) >= effect['expiry']:
            del state['areas'][identity]
    for identity, effect in tuple(state['recon'].items()):
        source = combat.field._actors.get(effect['source'])
        if source is None or not source.health or (effect['source'] in identities and combat.field._ability_turns[effect['source']] >= effect['expiry']):
            del state['recon'][identity]
    for identity in identities:
        if not combat.field.actor(identity).health:
            for name in ('flash', 'vision', 'night_vision'): state[name].pop(identity, None)
    for identity in identities: state['recon_selection'].pop(identity, None)
    return refresh_sight(combat)


def freeze_experience(combat, before, *, now=None):
    """Scale new XP deltas at their event time, never the eventual settlement."""
    from .item_boosters import active
    now = time.time() if now is None else now
    for identity, total in tuple(combat.experience.totals.items()):
        delta = total - before.get(identity, Fraction(0))
        if delta <= 0 or identity not in combat.persistence: continue
        if getattr(combat, 'wager', False): factor = Fraction(0)
        else:
            path, account = combat.persistence[identity]
            boosts = active(path, account, combat.storage_ids.get(identity, identity), now)
            factor = Fraction(0) if 'block_xp' in boosts else Fraction(100 + boosts.get('trainer', {}).get('value', 0), 100)
        combat.experience.totals[identity] = before.get(identity, Fraction(0)) + delta * factor


def freeze_rank_kills(combat, kills, *, now=None):
    from .item_boosters import active
    state = initialize(combat); now = time.time() if now is None else now
    for killer, victim in kills:
        if victim in state['rank_bonus'] or killer not in combat.persistence: continue
        bonus = 0
        if not getattr(combat, 'wager', False) and combat.resources.get(victim) not in (100, 103):
            path, account = combat.persistence[killer]
            bonus = active(path, account, combat.storage_ids.get(killer, killer), now).get('advisor', {}).get('value', 0)
        state['rank_bonus'][victim] = (killer, bonus)
        # Freeze the badge at the accepted death, within the same action SQL
        # transaction. Recovery and delayed settlement never reread its TTL.
        weekly = 0
        if not getattr(combat, 'wager', False):
            from .clan_benefits import rank_per_kill
            from .db_transaction import connect
            from contextlib import closing
            path, account = combat.persistence[killer]
            with closing(connect(path)) as db:weekly = rank_per_kill(db, account, now=now)
        state['weekly_rank'][victim] = weekly


def rank_bonus(combat, killer, victim):
    saved = initialize(combat)['rank_bonus'].get(victim)
    return saved[1] if saved is not None and saved[0] == killer else 0
