"""Powered implant battle effects, kept in the existing snapshot/transaction state."""
from __future__ import annotations
from collections.abc import Iterable
from dataclasses import replace
from fractions import Fraction
from typing import TYPE_CHECKING

from .implants import active, extra_effect, health_maximum, policy, powered
from .protocol.health import encode_health
from .protocol.item_list import decode_item_list
from .protocol.pet_info import decode_pet_info

if TYPE_CHECKING:
    from .combat import Combat
    from .visibility import VisibilityView


def state(combat: Combat) -> dict:
    from .battle_item_effects import initialize
    result = initialize(combat)
    result.setdefault('implants', {})
    return result['implants']


def fields(combat: Combat, identity: int) -> dict:
    packet = combat.proficiencies.get(identity)
    return decode_pet_info(packet, human_equipment=combat.human[identity]).fields if packet else {}


def extras(combat: Combat, identity: int) -> frozenset[int]:
    profile = fields(combat, identity)
    if not profile:
        return frozenset()
    return frozenset(effect for item in powered(profile, combat.inventories[identity])
                     if (effect := extra_effect(item.template_id)) is not None)


def register(combat: Combat, identity: int, health: tuple[int, int] | None) -> None:
    actor = combat.field._actors.get(identity)
    if actor is None:
        return
    profile = fields(combat, identity)
    percent = active(profile, combat.inventories[identity]).get('health', 0) if profile else 0
    if health is None:
        if percent:
            raise ValueError('Unprojected implant health is required by the battle scene')
        health = (actor.max_health, 0)
    base, bonus = health
    applied = health_maximum(profile, base, percent, bonus)-base if percent else 0
    state(combat)[identity] = dict(base=base, health_bonus=bonus, applied=applied,
        energy_remainder=Fraction(0), ended=-1, regenerated=-1, shot=-1)


def refresh(combat: Combat, identities: Iterable[int], *, view: VisibilityView | None = None) -> tuple[bytes, ...]:
    from .combat_completion import encode_max_health, initialize as health_state
    from .equipment_bonuses import project
    from .weapon_proficiency import battle_fields
    from .durability import refresh_template
    replies = []
    private = getattr(combat.field, 'result_view', None)
    views = {id(v): v for v in (view, private) if v is not None}
    for identity in sorted(set(identities)):
        saved = state(combat).get(identity)
        profile = fields(combat, identity)
        if saved is None or not profile:
            continue
        actor = combat.field.actor(identity)
        percent = active(profile, combat.inventories[identity]).get('health', 0)
        applied = health_maximum(profile, saved['base'], percent, saved['health_bonus'])-saved['base'] if percent else 0
        delta = applied-saved['applied']
        if delta:
            injection = health_state(combat)['health_capacity'].get(identity)
            maximum = max(1, actor.max_health+delta)
            if injection is not None:
                injection['base'] += delta
                from .combat_completion import rules
                maximum = injection['base']*(100+rules()['health']['bonus_percent'])//100
                injection['maximum'] = maximum
            current = min(actor.health, maximum)
            combat.field._actors[identity] = replace(actor, health=current, max_health=maximum)
            replies.append(encode_max_health(identity, maximum))
            if current != actor.health:
                replies.append(encode_health(identity, current))
            saved['applied'] = applied
        weight = combat.weight_packet(identity)
        if weight is not None:
            replies.append(weight)
        for target in views.values():
            if identity not in target.templates:
                continue
            template = target.templates[identity]
            projected = project(combat.proficiencies[identity], combat.human[identity], combat.inventories[identity])
            target.templates[identity] = replace(template, fields={**template.fields,
                **battle_fields(projected, combat.human[identity])})
            refresh_template(combat, target, identity)
        if view is not None and identity in view.visible and actor.health:
            replies.extend(view.snapshot_packets(identity))
    return tuple(replies)


def begin_turn(combat: Combat, identities: Iterable[int]) -> tuple[bytes, ...]:
    from .implant_power import batteries, energy
    from .protocol.implant_energy import encode_energy
    replies = []
    for identity in sorted(set(identities)):
        saved = state(combat).get(identity)
        actor = combat.field.actor(identity)
        generation = combat.field._ability_turns[identity]
        if saved is None or generation <= saved['regenerated']:
            continue
        saved['regenerated'] = generation
        inventory = combat.inventories[identity]
        if batteries(inventory):
            replies.append(encode_energy(identity, *energy(inventory)))
        if actor.health and 9 in extras(combat, identity):
            row = policy()['extra']['effects']['9']
            health = max(actor.health, min(actor.health+row['health'], actor.max_health*row['ceiling_percent']//100))
            if health != actor.health:
                combat.field._actors[identity] = replace(actor, health=health)
                replies.append(encode_health(identity, health))
    return tuple(replies)


def end_turn(combat: Combat, owner: int, identities: Iterable[int], seconds: float) -> tuple[bytes, ...]:
    from .implant_power import spend, energy
    from .protocol.implant_energy import encode_energy
    changes = {}
    for identity in sorted(set(identities)):
        actor = combat.field.actor(identity)
        if actor.owner_id != owner:
            raise ValueError('Owned implant turn required')
        saved = state(combat).get(identity)
        generation = combat.field._ability_turns[identity]
        if saved is None or generation <= saved['ended']:
            continue
        profile = fields(combat, identity)
        count = len(powered(profile, combat.inventories[identity])) if profile and actor.health else 0
        packet, remainder = spend(combat.inventories[identity], count, seconds, saved['energy_remainder'])
        saved.update(ended=generation, energy_remainder=remainder)
        if packet != combat.inventories[identity]:
            changes[identity] = packet
    combat._persist_batch(changes)
    combat.inventories.update(changes)
    return tuple(packet for i,p in changes.items()
                 for packet in (combat.inventory_packet(i,p), encode_energy(i,*energy(p))))


def damage_percent(combat: Combat, identity: int, weapon: str) -> int:
    return sum(row.get('percent', 0) for effect in extras(combat, identity)
               if (row := policy()['extra']['effects'][str(effect)])['kind'] == 'damage' and row['weapon'] == weapon)


def turn_penalty(combat: Combat, identity: int) -> int:
    effect = combat.item_effects.get('implant_concussion', {}).get(identity)
    return effect['ap'] if effect and combat.field._ability_turns[identity] <= effect['expiry'] else 0


def on_hits(combat: Combat, source: int, victims: Iterable[int], *,
            effects: frozenset[int] | None = None) -> tuple[bytes, ...]:
    from .battle_item_effects import initialize, refresh_sight
    from .protocol.action_points import encode_action_points
    status = initialize(combat)
    replies = []
    effects = extras(combat, source) if effects is None else effects
    for identity in victims:
        actor = combat.field.actor(identity)
        if not actor.health:
            continue
        for effect in sorted(effects & {14, 15}):
            row = policy()['extra']['effects'][str(effect)]
            if combat.rng.randrange(100) >= row['chance_percent']:
                continue
            expiry = combat.field._ability_turns[identity]+row['turns']
            if effect == 14:
                status['flash'][identity] = max(status['flash'].get(identity, 0), expiry)
            else:
                status.setdefault('implant_concussion', {})[identity] = dict(expiry=expiry, ap=row['ap'])
                current = min(actor.action_points, max(0, combat.field._turn_points[identity]-row['ap']))
                combat.field._actors[identity] = replace(actor, action_points=current)
                if current != actor.action_points:
                    replies.append(encode_action_points(identity, current))
    return (*replies, *refresh_sight(combat))
