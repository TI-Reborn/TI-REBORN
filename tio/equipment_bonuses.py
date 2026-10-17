"""Original equipment effects: manual pp66/72/74 and items.cfg effect values.

Only equipped items in their correct slots grant bonuses. Shield protection
requires the active hand (16), not the reserve weapon slot (128).
Permanent training/base snapshots must never include these temporary bonuses.
"""
from dataclasses import replace
from .protocol.item_list import decode_item_list
from .protocol.pet_info import decode_pet_info,encode_pet_info
from .weapon_proficiency import SAVED,BASE,number,bits

# template: (slot, eligible resources, stat, value)
RULES={254:(4,(1,2),'melee',25),256:(4,(1,2),'melee',25),
       262:(1,(6,),'sight',1),263:(4,(2,),'carry',200),264:(4,(2,),'carry',200),
       341:(16,(6,),'armor',85)}


def bonuses(inventory,resource):
    result=dict(melee=0,sight=0,carry=0,armor=0)
    if inventory is None:return result
    occupied=set()
    for item in decode_item_list(inventory)[1]:
        rule=RULES.get(item.template_id)
        if not rule or item.equipped!=1 or item.count!=1:continue
        slot,resources,stat,value=rule
        if item.client_slot!=slot or resource not in resources:continue
        if slot in occupied:raise ValueError('Multiple bonus items in one slot')
        occupied.add(slot);result[stat]+=value
    return result


def project(packet,human,inventory):
    pet=decode_pet_info(packet,human_equipment=human);f=dict(pet.fields)
    b=bonuses(inventory,f['0x8c446f'])
    f['0x8c4a1b']=min(255,f['0x8c4a1b']+b['sight'])
    f['0x8c4b57']=min(65535,f['0x8c4b57']+b['carry'])
    # BASE is unmodified training; SAVED is the effective displayed skill.
    if b['melee']:f[SAVED[0]]=bits(min(200,number(f[SAVED[0]])+b['melee']))
    return encode_pet_info(replace(pet,fields=f))


def training_profile(packet,human):
    pet=decode_pet_info(packet,human_equipment=human)
    f=dict(pet.fields)
    for effective,base in zip(SAVED,BASE):f[effective]=f[base]
    return encode_pet_info(replace(pet,fields=f))
