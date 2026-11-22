"""Weapon skill9: manual p40/59, native target_riflescope (enum5).

The original selector8b6335 uses primary weapon min/maxRange, not actor sight.
The user-requested footprint is a 3x3 square including diagonals (2026-10-19).
Visibility lasts through the owner's current turn, as binocular recon.
"""
from .protocol.item_list import decode_item_list

from .sniper_rifles import SVD

WEAPONS = frozenset((312, 313, SVD))  # Each rifle uses its own catalog range.
AP = 3
RADIUS = 1


def cast(combat, owner, request, *, view=None):
    from .battle_item_effects import _atomic, _actor, _pay, clear_item_sight
    from .visibility import field_sight
    from .combat_distance import combat_distance
    from .durability import wear_inventory

    def run():
        if request.ability_id != 9 or request.unknown_u32 != 0:
            raise ValueError('Invalid sniper scope request')
        actor = _actor(combat, owner, request.actor_id)
        old = combat.inventories[actor.actor_id]
        primary = [i for i in decode_item_list(old)[1] if i.equipped and i.client_slot == 16]
        if len(primary) != 1 or primary[0].template_id not in WEAPONS:
            raise ValueError('Прицел требует AWP, SVD или HK G3SG/1 в первом слоте')
        weapon = primary[0]
        if weapon.count != 1 or combat.item_is_broken(weapon):
            raise ValueError('Working unstacked sniper rifle required')
        field = combat.field; target = request.x, request.y
        if not field.inside(*target) or target in field.blocked:
            raise ValueError('Scope cell is outside map or blocked')
        rule = combat.catalog.weapons[weapon.template_id]
        if not rule.min_range <= combat_distance((actor.x, actor.y), target) <= rule.max_range:
            raise ValueError('Точка прицеливания вне дальности винтовки')
        if not field_sight(field, (actor.x, actor.y), target) or not clear_item_sight(combat, (actor.x, actor.y), target):
            raise ValueError('Линия прицеливания перекрыта')
        if actor.action_points < AP:
            raise ValueError('Insufficient action points')
        from .premium import current
        premium = current(*combat.persistence[actor.actor_id])[0] if actor.actor_id in combat.persistence else 0
        inventory = wear_inventory(old, weapon=weapon.instance_id, weapon_ap=AP,
            half_wear=premium == 3, remainders=combat.premium_wear_remainders,
            deferred_breaks=getattr(combat, 'deferred_weapon_breaks', None))
        replies = _pay(combat, actor, AP, inventory)
        state = combat.item_effects
        key = ('scope', actor.actor_id, state['sequence']); state['sequence'] += 1
        state['recon'][key] = dict(source=actor.actor_id, center=target, radius=RADIUS, shape='square',
            expiry=field._ability_turns[actor.actor_id])
        from .protocol.ability_status import AbilityStatus, encode_ability_status
        used = encode_ability_status(actor.actor_id, (AbilityStatus(9, 1, 0, 0),))
        return (*replies, *combat.skill_packets(actor.actor_id), used,
                *(view.refresh() if view is not None else ()))

    return _atomic(combat, run, views=() if view is None else (view,))
