"""Manual p56 wear; native ItemList current/max/calculated-max words.

Repair integer rounding is explicit emulator policy, calibrated to 50/350
->341/341 and 600->309 in the manual. No floating point or random wear.
"""
from dataclasses import replace
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
import xml.etree.ElementTree as ET
from .inventory_capacity import validate_capacity
from .protocol.item_list import ItemRecord, decode_item_list, encode_item_list

KITS = {17:600, 18:1200, 19:3600}


@lru_cache(maxsize=1)
def definitions():
    return {int(n.get('id')):{v.get('key'):v.get('val') for v in n.findall('value')}
            for n in ET.parse(Path(__file__).resolve().parents[1]/'evidence/items_diagnostic.xml').getroot()}


def durable(item):
    d=definitions().get(item.template_id,{})
    return (item.template_id not in (*KITS,300,333,337) and int(d.get('durability',0))>1
            and (d.get('itype')=='armor' or 'weaponType' in d or item.template_id in (24,5002)))


def special(item):
    return definitions().get(item.template_id,{}).get('special')=='1' or item.unknown_bytes_03[2]==1


def broken(item):
    return durable(item) and item.unknown_words[0]==0


def wear(item, amount):
    if not durable(item) or amount<=0:return item
    current,maximum,limit=item.unknown_words
    current=max(0,current-amount)
    if current==0 and not special(item):return None
    return replace(item,unknown_words=(current,maximum,limit),
                   unknown_u8_01=item.equipped if current else 0,
                   location_raw=item.slot if current else 0)


def wear_inventory(packet, *, weapon=None, weapon_ap=0, armor_damage=0,half_wear=False,remainders=None):
    owner,items,flag=decode_item_list(packet)
    updated=[]
    for item in items:
        amount=weapon_ap if item.instance_id==weapon else 0
        if item.equipped and definitions().get(item.template_id,{}).get('itype')=='armor':
            amount+=armor_damage*2//5
        if half_wear and amount>0:
            # Carry odd units within the battle; round cumulative wear upward.
            key=(owner,item.instance_id)
            numerator=amount+(remainders.get(key,1) if remainders is not None else 1)
            amount=numerator//2
            if remainders is not None:remainders[key]=numerator%2
        changed=wear(item,amount)
        if changed is not None:updated.append(changed)
    return encode_item_list(owner,tuple(updated),flag)


def repair_item(item, kit):
    if not durable(item) or item.count!=1 or item.optional_u32 is not None or item.unknown_bytes_02[3]:
        raise ValueError('Предмет нельзя ремонтировать этим набором')
    if kit.template_id not in KITS or kit.count!=1 or kit.equipped or kit.unknown_words[0]<=0:
        raise ValueError('Ремкомплект отсутствует или израсходован')
    current,maximum,limit=item.unknown_words
    if current>=maximum:raise ValueError('Предмет не нуждается в ремонте')
    # 3% of spent resource, integer nearest rounding. For a full repair
    # solve restored * 1.03 = deficit and assign the remainder to max loss.
    resource=kit.unknown_words[0]
    full=(100*(maximum-current)+51)//103
    restored=min(resource,full)
    loss=maximum-current-restored if restored==full else (restored*3+50)//100
    if restored<=0:raise ValueError('Недостаточно ресурса для ремонта')
    repaired=replace(item,unknown_words=(current+restored,maximum-loss,limit))
    remaining=resource-restored
    used=replace(kit,unknown_words=(remaining,*kit.unknown_words[1:])) if remaining else None
    return repaired,used,restored,loss


def spending_order(kit: ItemRecord) -> tuple[bool, int]:
    """Spend partially used kits first, so stacks leave at most one remainder."""
    return (kit.unknown_words[0]>=KITS[kit.template_id],kit.instance_id)


def repair_inventory(packet: bytes, target: int, kit_id: int | None = None, *,
                     allocate: Callable[[], int] | None = None) -> tuple[bytes, dict[str, int]]:
    """Spend one kit; a partial use of a stack splits it off under allocate()."""
    owner,items,flag=decode_item_list(packet)
    item=next((i for i in items if i.instance_id==target),None)
    if item is None:raise ValueError('Предмет не принадлежит бойцу')
    kits=sorted((i for i in items if i.template_id in KITS and i.unknown_words[0]>0 and not i.equipped
                 and (kit_id is None or i.instance_id==kit_id)),key=spending_order)
    if not kits:raise ValueError('У этого бойца нет ремкомплекта')
    kit=kits[0]
    fixed,remaining,spent,loss=repair_item(item,replace(kit,unknown_u32_01=1))
    split=()
    if kit.count>1:
        if remaining is not None:
            if allocate is None:raise ValueError('Item ID allocator required to split a kit stack')
            split=(replace(remaining,instance_id=allocate()),)
        remaining=replace(kit,unknown_u32_01=kit.count-1)
    changed=tuple(fixed if i.instance_id==target else remaining if i.instance_id==kit.instance_id else i for i in items)
    updated=tuple(i for i in changed if i is not None)+split
    validate_capacity(items,updated)
    return encode_item_list(owner,updated,flag),dict(
        target=target,kit=kit.instance_id,spent=spent,loss=loss,template=kit.template_id)


def refresh_template(combat,view,identity):
    template=view.templates[identity];fields=dict(template.fields)
    items=decode_item_list(combat.inventories[identity])[1]
    slots=((1,'0x8c525b'),(4,'0x8c531b'),(8,'0x8c5341'),(16,'0x8c52cf'),(128,'0x8c52f5')) if combat.human[identity] else ((4,'0x8c546e'),)
    for mask,key in slots:fields[key]=next((i.template_id for i in items if i.equipped and i.client_slot==mask),0)
    fields['0x8c567f']=combat.field.actor(identity).sight_radius
    fields['0x8c5731']=combat.displayed_armor(identity)
    # Actual stat projection is also sent as native attribute9; keep the
    # original template's unrelated base/skill fields intact.
    view.templates[identity]=replace(template,fields=fields)
