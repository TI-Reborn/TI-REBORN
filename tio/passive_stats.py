"""Derived city PetInfo stats; stored pet packet remains the base snapshot.

8c4a07 -> native maxHP+6008; 8c4ab1 -> currentHP+6006. Learning
increases capacity only, not current health. Conditional miner defense uses
the authoritative inventory rather than stale equipment fields in PetInfo.
"""
import json
from pathlib import Path
from .abilities import AbilityCatalog,AbilityLevel
from .protocol.pet_info import PetInfo,decode_pet_info,encode_pet_info
from .protocol.abilities import decode_abilities


def project_health(packet,human,learned,catalog):
    pet=decode_pet_info(packet,human_equipment=human)
    resource=pet.fields['0x8c446f']
    ability=20 if human and resource==6 else 1 if human and resource in (1,2) else 16 if not human and resource in (3,4,5) else None
    entries=[e for e in learned if e.ability_id==ability]
    if len(entries)>1:raise ValueError('Duplicate health ability')
    if not entries:return packet
    definition=catalog.get(ability,entries[0].level)
    bonus=definition.number('value')
    if bonus is None or bonus<0:raise ValueError('Missing health bonus')
    maximum=pet.fields['0x8c4a07']+bonus
    if maximum>65535:raise ValueError('Maximum health exceeds native field')
    return encode_pet_info(PetInfo(human,{**pet.fields,'0x8c4a07':maximum}))


def project_saved_pet(db,account,owner,packet,human):
    from .weapon_proficiency import ProficiencyRules
    packet=ProficiencyRules().normalize(packet,human)
    inventory=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()[0]
    from .weight import project_base_weight
    from .equipment_bonuses import project
    # Older databases need no migration just to read their baseline roster.
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ability_states'").fetchone() is None:return project(project_base_weight(packet,human,inventory),human,inventory)
    row=db.execute('SELECT packet FROM ability_states WHERE account=? AND pet_id=?',(account,owner)).fetchone()
    if row is None:return project(project_base_weight(packet,human,inventory),human,inventory)
    actor,learned,learning=decode_abilities(row[0])
    if actor!=owner or learning:raise ValueError('Invalid saved skill profile')
    source=json.loads((Path(__file__).resolve().parents[1]/'config/abilities.json').read_text())
    catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
    return project_passives(packet,human,learned,catalog,inventory=inventory)


def project_passives(packet,human,learned,catalog,*,inventory=None):
    from .weight import project_base_weight
    packet=project_base_weight(packet,human,inventory)
    packet=project_health(packet,human,learned,catalog)
    from .equipment_bonuses import project
    packet=project(packet,human,inventory)
    pet=decode_pet_info(packet,human_equipment=human)
    resource=pet.fields['0x8c446f']
    from .miner_abilities import naked
    defense_id=24 if human and resource==6 and naked(inventory) else 6 if human and resource in (1,2) else 15 if not human and resource in (3,4,5) else None
    defense=[e for e in learned if e.ability_id==defense_id]
    if len(defense)>1:raise ValueError('Duplicate defense ability')
    if defense:
        bonus=catalog.get(defense_id,defense[0].level).number('value')
        if bonus is None or bonus<0:raise ValueError('Missing defense bonus')
        armor=pet.fields['0x8c4ac5']+bonus
        if armor>65535:raise ValueError('Armor exceeds native field')
        # RTTI ArmorClass+6010, populated directly by reader8c4ac5.
        # p15d explicitly describes dog defense as an additional armor bonus.
        packet=encode_pet_info(PetInfo(human,{**pet.fields,'0x8c4ac5':armor}))
        pet=decode_pet_info(packet,human_equipment=human)
    # RTTI a80e42 names +6024 max_weight; 8c4b57 reads its u16.
    if not human or pet.fields['0x8c446f'] not in (1,2,6):return packet
    carry_id=21 if resource==6 else 2
    entries=[e for e in learned if e.ability_id==carry_id]
    if len(entries)>1:raise ValueError('Duplicate carry ability')
    if not entries:return packet
    bonus=catalog.get(carry_id,entries[0].level).number('value')
    if bonus is None or bonus<0:raise ValueError('Missing carry bonus')
    maximum=pet.fields['0x8c4b57']+bonus
    if maximum>65535:raise ValueError('Maximum weight exceeds native field')
    return encode_pet_info(PetInfo(human,{**pet.fields,'0x8c4b57':maximum}))
