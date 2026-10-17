"""Battle-only original Skill28 radio; the absent AP rule is explicit policy."""
from dataclasses import replace
from .protocol.abilities import AbilityEntry,decode_abilities,encode_abilities

def configure(field,owner,packets=()):
    mine=field.mining;combat=field.combat;eligible=mine.roles[owner] in (1,2)
    identities=set(field.actor_ids(owner));output=[]
    for identity in identities:
        if not eligible or not combat.human.get(identity) or combat.resources.get(identity) not in (1,2,6):continue
        entries=combat.learned.get(identity,())
        if not any(e.ability_id==28 for e in entries):entries=(*entries,AbilityEntry(28,1,0,1))
        combat.learned[identity]=tuple(entries)
        from .weapon_effects import battle_skills
        combat.skill_lists[identity]=battle_skills(entries,combat.inventories[identity],combat.human[identity])
    present=set()
    for packet in packets:
        if packet[:1]==b'\x80':
            identity,entries,_=decode_abilities(packet)
            if identity in identities and identity in combat.skill_lists:
                packet=encode_abilities(identity,combat.skill_lists[identity]);present.add(identity)
        output.append(packet)
    output.extend(encode_abilities(identity,combat.skill_lists[identity]) for identity in sorted(identities-present)
        if any(e.ability_id==28 for e in combat.skill_lists.get(identity,())))
    return tuple(output)

def request(field,owner,cast):
    """Return requested role; client never selects the recipient or queue."""
    actor=field._actors.get(cast.actor_id)
    if cast.ability_id!=28 or cast.unknown_u32!=0 or actor is None or actor.owner_id!=owner or not actor.health:
        raise ValueError('Требуется живой собственный наёмник')
    if not field.combat.human.get(actor.actor_id) or field.combat.resources.get(actor.actor_id) not in (1,2,6):
        raise ValueError('Для вызова помощи требуется человек или шахтёр')
    if (cast.x,cast.y)!=(actor.x,actor.y):raise ValueError('Радио применяется к своему наёмнику')
    mine=field.mining;role=mine.roles.get(owner)
    entries=mine.layout.raider_exits if role==2 else mine.layout.lift
    if role not in (1,2) or (actor.x,actor.y) not in entries:raise ValueError('Вызов доступен добытчику или рейдеру в зоне входа')
    return 2 if role==2 else 3
