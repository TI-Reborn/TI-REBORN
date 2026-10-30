"""Atomic exchange of loose items between adjacent living mercenaries of ONE owner."""
from dataclasses import replace
from .protocol.item_list import decode_item_list,encode_item_list
from .protocol.action_points import encode_action_points
from .item_stacking import merge_stacks
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
    bags=[];flags=[]
    for packet in old:
        _,items,flag=decode_item_list(packet)
        bag={i.instance_id:i for i in items}
        if len(bag)!=len(items):raise ValueError('Duplicate exchange item identity')
        bags.append(bag);flags.append(flag)
    if set(bags[0])&set(bags[1]):raise ValueError('Duplicate exchange ownership')
    loot=field.loot;next_id=loot.allocation_floor();temporary=set(combat.temporary_items)
    for selection,source,target in ((request.withdrawals,bags[1],bags[0]),(request.deposits,bags[0],bags[1])):
        for identity,count in selection:
            item=source.get(identity)
            if item is None or not (0<count<=item.count or item.template_id==52 and count==item.count==0):
                raise ValueError('Предмет или его количество изменились')
            if item.equipped or item.slot:raise ValueError('Сначала снимите передаваемое снаряжение')
            if item.template_id==52 and count!=item.count:raise ValueError('Бур с кристаллами передаётся целиком')
            if count==item.count:source.pop(identity)
            else:
                if next_id>0xffffffff:raise ValueError('Item identity space exhausted')
                source[identity]=replace(item,unknown_u32_01=item.count-count)
                item=replace(item,instance_id=next_id,unknown_u32_01=count)
                if identity in temporary:temporary.add(next_id)
                next_id+=1
            # Same account: preserve durability, upgrade, marker and rental data.
            target[item.instance_id]=item
    changes={}
    for index,bag in enumerate(bags):
        values=tuple(bag.values())
        merged=(*merge_stacks(i for i in values if i.instance_id not in temporary),
                *merge_stacks(i for i in values if i.instance_id in temporary))
        from .inventory_capacity import validate_capacity
        validate_capacity(decode_item_list(old[index])[1],merged,limit=loot.policy['inventory_slots'],
                          error=lambda _:ValueError('В инвентаре бойца недостаточно места'))
        changes[ids[index]]=encode_item_list(ids[index],merged,flags[index])
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
