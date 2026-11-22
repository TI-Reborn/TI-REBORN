"""Atomic exchange of loose items between adjacent living mercenaries of ONE owner."""
from dataclasses import replace
from .protocol.action_points import encode_action_points
from .visibility import clear_sight


def refresh(combat,owner,identities):
    replies=[]
    for identity in dict.fromkeys(identities):
        actor=combat.field._actors.get(identity)
        if actor is None or actor.owner_id!=owner or identity not in combat.inventories:continue
        replies.extend((combat.inventory_packet(identity),encode_action_points(identity,actor.action_points)))
        weight=combat.weight_packet(identity)
        if weight is not None:replies.append(weight)
    return tuple(replies)


def exchange(combat,owner,request,generation):
    field=combat.field;ids=(request.actor_id,request.target_id)
    actors=[field._actors.get(i) for i in ids]
    if ids[0]==ids[1] or any(a is None or a.owner_id!=owner or not a.health for a in actors):
        raise ValueError('Обмен возможен только между двумя своими живыми бойцами')
    if any(not combat.human.get(i) or i not in combat.inventories for i in ids):
        raise ValueError('Для обмена нужны два наёмника')
    a,b=actors;positions=((a.x,a.y),(b.x,b.y))
    if max(abs(a.x-b.x),abs(a.y-b.y))!=1 or not clear_sight(*positions,field.blocked):
        raise ValueError('Подведите бойцов вплотную друг к другу без препятствия между ними')
    if a.action_points<1:raise ValueError('Для обмена нужен 1 ОД у активного бойца')
    old=tuple(combat.inventories[i] for i in ids)
    snapshot=(ids,generation,positions,old)
    sessions=combat.exchange_sessions
    if not request.withdrawals and not request.deposits:
        sessions[owner]=snapshot
        return refresh(combat,owner,ids)
    opened=sessions.pop(owner,None)
    if opened!=snapshot:raise ValueError('Окно обмена устарело. Откройте его заново')
    # Native opening is local. The explicit empty6E hook binds a confirmation
    # to these inventories, positions and the actor's current turn generation.
    from .item_exchange import exchange_items
    loot = field.loot
    changes, next_id, temporary = exchange_items(
        *old, request, loot.allocation_floor(), temporary=combat.temporary_items,
        limit=loot.policy['inventory_slots'])
    # Prepare every reply before persistence; no DB failure can partially move
    # an item, spend AP, reserve an ID or change temporary-item ownership.
    replies=[]
    for identity,packet in changes.items():
        replies.append(combat.inventory_packet(identity,packet))
        weight=combat.weight_packet(identity,packet)
        if weight is not None:replies.append(weight)
    replies.append(encode_action_points(a.actor_id,a.action_points-1))
    combat._persist_batch(changes,temporary_ids=temporary)
    combat.inventories.update(changes);combat.temporary_items=temporary;loot.next_id=next_id
    field._actors[a.actor_id]=replace(a,action_points=a.action_points-1)
    return tuple(replies)
