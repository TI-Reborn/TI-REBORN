"""Authoritative staged equipment with one atomic confirmation per owner turn.

Pending records contain only primitive checkpoint-safe values. Stage packets
are private previews: no saved inventory, battle actor, AP, profile or template
changes until commit. A rejected stage/commit invalidates the whole batch.
"""
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
import json

from .protocol.item_list import decode_item_list, encode_item_list
from .protocol.action_points import encode_action_points


@lru_cache(maxsize=1)
def policy():
    result=json.loads((Path(__file__).resolve().parents[1]/'config/equipment_batch.json').read_text(encoding='utf-8'))
    if result.get('schema')!=1 or result.get('action_points_per_changed_actor')!=2:
        raise ValueError('Unsupported equipment batch policy')
    for key in ('maximum_staged_actions','maximum_staged_actors','recent_confirmations_per_owner'):
        if type(result.get(key)) is not int or not 1<=result[key]<=1024:raise ValueError('Invalid equipment batch limit')
    return result


class EquipmentBatchRejected(ValueError):
    def __init__(self,message,restores=()):
        super().__init__(message)
        self.restores=tuple(restores)


def initialize(combat):
    if not hasattr(combat,'equipment_batches'):combat.equipment_batches={}
    if not hasattr(combat,'equipment_batch_receipts'):combat.equipment_batch_receipts={}


def _actor(combat,owner,identity):
    if identity not in combat.inventories or identity not in combat.field._actors:
        raise ValueError('Неизвестный боец для смены экипировки')
    actor=combat.field.actor(identity)
    if actor.owner_id!=owner or not actor.health:raise ValueError('Недоступный боец для смены экипировки')
    return actor


def preview(combat,owner,action,inventory):
    """Validate original gear placement, without live/durable writes or AP cost."""
    actor=_actor(combat,owner,action.pet_id)
    if actor.action_points<2:raise ValueError('Для смены экипировки нужно 2 ОД')
    identity,items,unknown=decode_item_list(inventory)
    if identity!=actor.actor_id:raise ValueError('Неверный владелец инвентаря')
    selected=next((i for i in items if i.instance_id==action.instance_id),None)
    if selected is None or selected.count!=1:raise ValueError('Нужен собственный отдельный предмет')
    from .equipment import EquipmentStore,armor_rules
    armor=armor_rules()
    template=selected.template_id
    if template in armor:
        rules={template:(armor[template]['slot'],)}
        slot=action.target_mask or armor[template]['slot']
    elif template in combat.catalog.weapons and template not in (300,333,337):
        rules={template:(16,128)}
        from .equipment import weapon_slot
        slot=weapon_slot(items,action.target_mask)
    else:raise ValueError('Пакетная смена доступна только для оружия и брони')
    # EquipmentStore validates species/sex, level, enhancement and wear. The
    # saved proficiency packet supplies authoritative actor level/class.
    profile=combat.proficiencies.get(actor.actor_id)
    if profile is None:
        raise ValueError('Нет сохранённого профиля бойца')
    store=EquipmentStore.__new__(EquipmentStore)
    store.rules={template:frozenset(rules[template])}
    store.armor=armor;store.weapons_only=True
    updated=store.place(profile,combat.human[actor.actor_id],items,action.instance_id,slot,
                        toggle=action.option==255,is_broken=combat.item_is_broken)
    return encode_item_list(actor.actor_id,updated,unknown)


def _restores(combat,batch):
    return tuple(combat.inventory_packet(identity) for identity in sorted(batch.get('actors',{}))
                 if identity in combat.inventories)


def cancel(combat,owner,*,batch_id=None,forget_receipts=False):
    """Cancel on explicit cancel, turn end, reconnect, escape or item mutation."""
    initialize(combat)
    batch=combat.equipment_batches.get(owner)
    if batch is not None and (batch_id is None or batch_id==batch['batch_id']):
        combat.equipment_batches.pop(owner,None)
        restores=_restores(combat,batch)
    else:restores=()
    if forget_receipts:combat.equipment_batch_receipts.pop(owner,None)
    return restores


def _carry(record,current):
    """Staged placement re-applied to a changed inventory, or None if stale.

    Valid only while the change left every surviving item's own placement
    alone (a consumed stack, a looted item) and kept each staged item.
    """
    def placement(item):return (item.unknown_u8_01,item.location_raw)
    base={i.instance_id:placement(i) for i in decode_item_list(record['base'])[1]}
    staged={i.instance_id:placement(i) for i in decode_item_list(record['preview'])[1]}
    identity,items,unknown=decode_item_list(current)
    present={i.instance_id for i in items}
    if any(i.instance_id in base and placement(i)!=base[i.instance_id] for i in items):return None
    if any(staged[k]!=base[k] and k not in present for k in base):return None
    updated=[replace(i,unknown_u8_01=staged[i.instance_id][0],location_raw=staged[i.instance_id][1])
             if i.instance_id in staged else i for i in items]
    return encode_item_list(identity,updated,unknown)


def rebase(combat,owner):
    """Keep a preview across the owner's item use or loot; return what to show.

    Those actions answer with the authoritative inventory, so every staged
    actor's preview is sent again. A preview that no longer fits is cancelled.
    """
    initialize(combat)
    batch=combat.equipment_batches.get(owner)
    if batch is None:return ()
    records={}
    for identity,record in batch['actors'].items():
        current=combat.inventories.get(identity)
        preview=None if current is None else record['preview'] if current==record['base'] else _carry(record,current)
        if preview is None:return cancel(combat,owner)
        records[identity]={**record,'base':current,'preview':preview}
    combat.equipment_batches[owner]={**batch,'actors':records}
    return tuple(combat.inventory_packet(identity,records[identity]['preview']) for identity in sorted(records))


def shown_inventory(combat,owner,identity):
    """What the owner's window displays: a pending preview, else live state."""
    record=getattr(combat,'equipment_batches',{}).get(owner,{}).get('actors',{}).get(identity)
    return combat.inventory_packet(identity,None if record is None else record['preview'])


def pending(combat,owner):
    initialize(combat)
    return owner in combat.equipment_batches


def _reject(combat,owner,message):
    raise EquipmentBatchRejected(message,cancel(combat,owner))


def stage(combat,owner,request,turn_key):
    """Caller first validates current turn, selected actor and session identity."""
    initialize(combat);limits=policy()
    from .protocol.equipment_batch import STAGE
    if request.operation!=STAGE:_reject(combat,owner,'Нужна смена предмета')
    action=request.action
    batch=combat.equipment_batches.get(owner)
    try:
        from .protocol.equipment_batch import encode_equipment_batch
        encode_equipment_batch(request)
        actor=_actor(combat,owner,action.pet_id)
        receipts=combat.equipment_batch_receipts.get(owner,())
        if any(r['batch_id']==request.batch_id and r['turn_key']==turn_key for r in receipts):
            raise ValueError('Эта смена экипировки уже подтверждена')
        if batch is not None and (batch['batch_id']!=request.batch_id or batch['turn_key']!=turn_key):
            raise ValueError('Предыдущая смена экипировки потеряла актуальность')
        if batch is None:
            batch={'batch_id':request.batch_id,'turn_key':turn_key,'actors':{},'actions':0}
        if batch['actions']>=limits['maximum_staged_actions']:
            raise ValueError('Слишком много изменений в одном подтверждении')
        if actor.actor_id not in batch['actors'] and len(batch['actors'])>=limits['maximum_staged_actors']:
            raise ValueError('Слишком много бойцов в одном подтверждении')
        record=batch['actors'].get(actor.actor_id)
        if record is not None and combat.inventories[actor.actor_id]!=record['base']:
            raise ValueError('Инвентарь изменился во время выбора экипировки')
        base=combat.inventories[actor.actor_id] if record is None else record['base']
        inventory=preview(combat,owner,action,base if record is None else record['preview'])
        # Publish pending primitives only after the entire action is validated.
        prior=base if record is None else record['preview']
        records=dict(batch['actors']);records[actor.actor_id]={
            'base':base,'preview':inventory,
            'changed':inventory!=prior or (record is not None and record['changed']),
            'profile':combat.proficiencies[actor.actor_id]}
        batch={**batch,'actors':records,'actions':batch['actions']+1}
        combat.equipment_batches[owner]=batch
        return (combat.inventory_packet(actor.actor_id,inventory),)
    except ValueError as error:
        _reject(combat,owner,str(error))


def _packets(combat,identities):
    return tuple(packet for identity in sorted(identities) if identity in combat.inventories
                 for packet in (combat.inventory_packet(identity),
                                encode_action_points(identity,combat.field.actor(identity).action_points),
                                *combat.skill_packets(identity)))


def commit(combat,owner,request,turn_key,*,view=None):
    """Validate every actor first, persist one DB transaction, then publish all."""
    initialize(combat);limits=policy()
    from .protocol.equipment_batch import COMMIT
    if request.operation!=COMMIT:_reject(combat,owner,'Нужно подтверждение экипировки')
    from .protocol.equipment_batch import encode_equipment_batch
    try:encode_equipment_batch(request)
    except ValueError as error:_reject(combat,owner,str(error))
    batch=combat.equipment_batches.get(owner)
    if batch is None:
        receipt=next((r for r in combat.equipment_batch_receipts.get(owner,())
                      if r['batch_id']==request.batch_id and r['turn_key']==turn_key),None)
        if receipt is not None:return _packets(combat,receipt['actors'])
        _reject(combat,owner,'Нет изменений для подтверждения')
    try:
        if batch['batch_id']!=request.batch_id or batch['turn_key']!=turn_key:
            raise ValueError('Подтверждение экипировки потеряло актуальность')
        changes,states,templates,taxes={},{},{},{}
        from .equipment_bonuses import bonuses
        from .rental import rental_tax_units
        for identity,record in sorted(batch['actors'].items()):
            actor=_actor(combat,owner,identity)
            old,new=record['base'],record['preview']
            if combat.inventories[identity]!=old:raise ValueError('Инвентарь изменился во время выбора экипировки')
            if combat.proficiencies.get(identity)!=record['profile']:
                raise ValueError('Профиль бойца изменился во время выбора экипировки')
            if not record['changed']:continue
            if actor.action_points<2:raise ValueError('Для смены экипировки нужно 2 ОД')
            _,items,_=decode_item_list(new)
            weapons=combat.catalog.equipped(new,human=combat.human[identity],resource=combat.resources[identity])
            sight=actor.sight_radius+bonuses(new,combat.resources[identity])['sight']-bonuses(old,combat.resources[identity])['sight']
            if not 0<=sight<=255:raise ValueError('Недопустимый обзор после смены экипировки')
            states[identity]=replace(actor,weapons=weapons,action_points=actor.action_points-2,sight_radius=sight)
            if new!=old:changes[identity]=new
            taxes[identity]=max(combat.rental_tax_units.get(identity,0),rental_tax_units(new))
            if view is not None:
                template=view.templates[identity];fields=dict(template.fields)
                from .equipment_bonuses import project
                from .weapon_proficiency import battle_fields
                fields.update(battle_fields(project(combat.proficiencies[identity],combat.human[identity],new),combat.human[identity]))
                masks=((1,'0x8c525b'),(4,'0x8c531b'),(8,'0x8c5341'),(16,'0x8c52cf'),(128,'0x8c52f5')) if combat.human[identity] else ((4,'0x8c546e'),)
                for mask,key in masks:
                    fields[key]=next((i.template_id for i in items if i.equipped and i.client_slot==mask),0)
                templates[identity]=replace(template,fields=fields)
        # Replies and skill projections are staged too: a serializer failure
        # must happen before the durable transaction, never after its commit.
        from copy import copy
        projected=copy(combat);projected.inventories={**combat.inventories,**changes}
        projected.field=copy(combat.field);projected.field._actors={**combat.field._actors,**states}
        projected.skill_lists=dict(combat.skill_lists)
        replies=_packets(projected,batch['actors'])
        if view is not None:
            from .protocol.battle_soldier import encode_battle_soldier
            for template in templates.values():encode_battle_soldier(template)
        # Persistence uses all original packets as optimistic preconditions.
        # There are no live/profile/template changes before it succeeds.
        # Even a preview restored to its original slots must check all saved
        # preconditions before AP is charged. Include unchanged participants
        # so one stale actor cannot partially confirm another actor's gear.
        durable={identity:record['preview'] for identity,record in batch['actors'].items()}
        expected={identity:record['profile'] for identity,record in batch['actors'].items()}
        combat._persist_batch(durable,expected_profiles=expected)
        combat.inventories.update(changes);combat.field._actors.update(states)
        combat.rental_tax_units.update(taxes)
        combat.skill_lists=projected.skill_lists
        if view is not None:view.templates.update(templates)
        combat.equipment_batches.pop(owner,None)
        receipts=list(combat.equipment_batch_receipts.get(owner,()))
        receipts.append({'batch_id':request.batch_id,'turn_key':turn_key,'actors':tuple(batch['actors'])})
        combat.equipment_batch_receipts[owner]=receipts[-limits['recent_confirmations_per_owner']:]
        return replies
    except ValueError as error:
        _reject(combat,owner,str(error))
    except Exception:
        # Storage failures retain their type for the authoritative journal's
        # quarantine/rollback handling; the private preview must also vanish.
        cancel(combat,owner)
        raise
