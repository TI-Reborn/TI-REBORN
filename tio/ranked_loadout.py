"""Battle-only C6 selections, level normalization and fractional gear bonuses.

Rules: TIO administration, 2012-04-28 (see RANKED_BATTLES.md). The
client's unowned replacement previews are +10; they never become saved items.
"""
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
import xml.etree.ElementTree as ET
from .protocol.item_list import decode_item_list,encode_item_list,ItemRecord
from .protocol.pet_info import decode_pet_info,encode_pet_info
from .ranked_party import RankedRejection
from .item_catalog import items_root

SLOTS={0:1,2:4,3:8,4:16,7:128}


@lru_cache(maxsize=1)
def metadata():
    from .arena_gears import catalogue_packet
    from .protocol.ranked import decode_gears
    from .equipment import armor_rules
    from .weapons import WeaponCatalog
    source=Path(__file__).resolve().parents[1]/'evidence/items_diagnostic.xml'
    durability={int(n.get('id')):int(next((v.get('val') for v in n.findall('value') if v.get('key')=='durability'),'0')) for n in items_root()}
    return frozenset(decode_gears(catalogue_packet())),armor_rules(),WeaponCatalog(),durability


@lru_cache(maxsize=1)
def _durability_per_level():
    from .enhancement import EnhancementRules
    return EnhancementRules().config['durability_per_level']


def validate(packet,inventory,human,equipment):
    from .durability import broken
    allowed,armor,weapons,_=metadata()
    fields=decode_pet_info(packet,human_equipment=human).fields
    resource=fields['0x8c446f']
    occupied={}
    for item in decode_item_list(inventory)[1]:
        if item.equipped:
            rule=armor.get(item.template_id,{})
            for slot in rule.get('covers',(item.client_slot,)):occupied[slot]=item
    for wire_slot,template in equipment:
        slot=SLOTS[wire_slot]
        if template not in allowed:raise RankedRejection('Неизвестный предмет TrueSkill')
        rule=armor.get(template)
        if rule:
            if slot!=rule['slot'] or bool(rule['dog'])==human or bool(rule.get('miner'))!=(resource==6) or rule.get('female') and resource!=2:
                raise RankedRejection('Предмет TrueSkill не подходит бойцу или слоту')
            if fields['0x8c4aef'] < rule['level']:
                raise RankedRejection(f"Для этой брони нужен уровень {rule['level']}")
        elif template not in weapons.weapons or slot not in (16,128) or not human or (weapons.sources[template].get('freaks_only')=='1')!=(resource==6):
            raise RankedRejection('Оружие TrueSkill не подходит бойцу или слоту')
        covers=rule.get('covers',(slot,)) if rule else (slot,)
        if any(s in occupied for s in covers):raise RankedRejection('Слот TrueSkill уже занят: обновите выбор экипировки')
        for s in covers:occupied[s]=template
    # A broken owned piece must be repaired, not silently replaced by a loan.
    if any(i.equipped and broken(i) for i in decode_item_list(inventory)[1]):
        raise RankedRejection('Перед боем отремонтируйте экипировку')


def band(level):
    return next(i for i,maximum in enumerate((6,10,15,20)) if level<=maximum)


def gear_bonus(inventory,human,catalog):
    _,armor,_,_=metadata();pieces={};weapons=[]
    for item in decode_item_list(inventory)[1]:
        if not item.equipped:continue
        upgrade=min(25,item.unknown_bytes_03[0])
        if item.template_id in armor:
            for slot in armor[item.template_id].get('covers',(item.client_slot,)):
                if slot in (1,4,8):pieces[slot]=upgrade
        elif item.template_id in catalog.weapons:
            kind=catalog.weapons[item.template_id].weapon_type
            if not human or kind not in ('Melee','Throwing'):weapons.append(upgrade)
    return min(100,sum(pieces.values())+max(weapons,default=0))


def apply(field,templates,seats):
    """Called once before publishing a scene; persistent packets stay intact."""
    from .enhancement_limits import enhancement_cap
    from .weapon_proficiency import SAVED,BASE,CAPS,number,bits
    from tools.battle_actor_fixture import actor_packet
    from .protocol.battle_soldier import decode_battle_soldier
    from .equipment_bonuses import bonuses
    combat=field.combat;ceiling=(6,10,15,20)[min(band(l) for s in seats for l in s[4].levels)]
    choices={owner:{i:(e,b) for i,e,b in getattr(ticket,'selections',())} for owner,side,path,account,ticket,bot in seats}
    upgrades={owner:25 if getattr(ticket,'flags',(0,0))[0] else 10 for owner,side,path,account,ticket,bot in seats}
    combat.ranked_limits={};combat.ranked_bonuses={};combat.ranked_remainders={};combat.ranked_health={}
    # Loans live in the match ID namespace (see battle_loot.match_id_floor);
    # a reused saved ID made the client dim the loaned active weapon.
    from .battle_loot import match_id_floor
    next_id=match_id_floor(combat)
    per_level=_durability_per_level()
    for identity,actor in tuple(field._actors.items()):
        human=combat.human[identity];original=combat.proficiencies[identity]
        pet=decode_pet_info(original,human_equipment=human);f=dict(pet.fields)
        saved_id=combat.storage_ids[identity];equipment,kind=choices[actor.owner_id].get(saved_id,((),0))
        inventory=combat.inventories[identity];_,items,flag=decode_item_list(inventory)
        validate(original,inventory,human,equipment)
        additions=[]
        upgrade=upgrades[actor.owner_id]
        durability=metadata()[3]
        for wire_slot,template in equipment:
            additions.append(ItemRecord(next_id,template,bytes(2),1,1,SLOTS[wire_slot],(durability[template]+upgrade*per_level,)*3,bytes((upgrade,0,0,0)),None,bytes((upgrade,0,0))))
            combat.temporary_items.add(next_id);next_id+=1
        # Loaned firearms need battle-only ammunition to be usable. One source
        # catalogue pack per ammo type is an explicit server supply policy.
        for ammo in sorted({combat.catalog.weapons[i.template_id].ammo_id for i in additions if i.template_id in combat.catalog.weapons}-{None}):
            if not any(i.template_id==ammo for i in items):
                amount=combat.catalog.ammunition[ammo]['pack_amount']
                additions.append(ItemRecord(next_id,ammo,bytes(2),amount,0,0,(1,1,1),bytes(4),None,bytes(3)))
                combat.temporary_items.add(next_id);next_id+=1
        inventory=encode_item_list(identity,(*items,*additions),flag)
        old_b=bonuses(combat.inventories[identity],combat.resources[identity]);new_b=bonuses(inventory,combat.resources[identity])
        combat.inventories[identity]=inventory
        combat.enhancement_caps[identity]=min(combat.enhancement_caps[identity],enhancement_cap(ceiling))
        # April 20 developer diary explicitly gives106 for the4..6 bracket.
        # Higher brackets retain the existing server progression caps.
        single=106 if ceiling==6 else combat.proficiency_rules.caps(ceiling,human)[0]
        combat.ranked_limits[identity]=single
        for key in (*SAVED,*BASE):f[key]=bits(min(number(f[key]),single))
        f[SAVED[0]]=bits(min(single,number(f[SAVED[0]])+new_b['melee']))
        f[CAPS[0]]=f[CAPS[2]]=single
        # Retain higher-band carry capacity, perks and total proficiency cap.
        level=f['0x8c4aef'];difference=max(0,band(level)-band(ceiling))
        maximum=max(1,actor.max_health-max(0,level-ceiling)*5+5*difference)
        units=gear_bonus(inventory,human,combat.catalog)
        combat.ranked_bonuses[identity]=(kind,units)
        if kind==0:maximum+=maximum*units//1000
        combat.ranked_health[identity]=(actor.max_health,maximum)
        combat.rank_profiles[identity]=(min(level,ceiling),combat.rank_profiles[identity][1])
        state=replace(actor,max_health=maximum,health=maximum,weapons=combat.catalog.equipped(inventory,human=human,resource=f['0x8c446f']),sight_radius=actor.sight_radius+new_b['sight']-old_b['sight'])
        field._actors[identity]=state
        from .weight import inventory_weight
        f.update({'0x8c43eb':identity,'0x8c4a07':maximum,'0x8c4ab1':maximum,
                  '0x8c4b6d':min(65535,inventory_weight(inventory)),
                  '0x8c4b57':combat.weight_capacity(identity),
                  '0x8c4ac5':combat.displayed_armor(identity)})
        packet=encode_pet_info(replace(pet,fields=f))
        old=templates[identity]
        fresh=decode_battle_soldier(actor_packet(packet,actor.owner_id,inventory,human=human,actor_id=identity,x=actor.x,y=actor.y,team=field.teams[actor.owner_id],color=old.fields['0x8c5173']),human_equipment=human)
        templates[identity]=fresh


def extra(combat,identity,kind,amount,remainders):
    selected,units=getattr(combat,'ranked_bonuses',{}).get(identity,(-1,0))
    if kind!=selected or amount<=0 or not units:return 0
    key=(identity,kind);whole,remainder=divmod(amount*units+remainders.get(key,0),1000)
    remainders[key]=remainder
    return whole


def limit_display(fields,cap):
    from .weapon_proficiency import BATTLE_SAVED,BATTLE_BASE,number,bits
    fields=dict(fields)
    for key in (*BATTLE_SAVED,*BATTLE_BASE):fields[key]=bits(min(number(fields[key]),cap))
    fields['0x8c561c']=fields['0x8c5646']=cap
    return fields
