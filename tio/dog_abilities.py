"""Dog rules: manual eligibility, CFG effects, explicit compatibility defaults."""
import json
from pathlib import Path
from .abilities import AbilityCatalog, AbilityLevel


def rules():
    return json.loads((Path(__file__).resolve().parents[1]/'config/dog_abilities.json').read_text())


def catalog_for_play(catalog):
    result=[]
    cooldowns=rules()['cooldowns']
    for row in catalog.records:
        fields=dict(row.fields); rank=row.level
        if row.ability_id in (14,19):
            rank=1; fields.update(level='1',value='1')
        if str(row.ability_id) in cooldowns:
            fields['Cooldown']=str(cooldowns[str(row.ability_id)])
        # Range is rank-dependent; the original XML castRange is shared.
        # Scent targets self, so range0 is sufficient for the UI. The server
        # uses the explicit rank's value as detection radius.
        if row.ability_id==12:fields['Range']='0'
        result.append(AbilityLevel(row.ability_id,rank,fields))
    return AbilityCatalog(result)


def required_level(ability,rank):
    return rules()['required_levels'][str(ability)][rank-1]


def configure(field,owner,actor_id,resource,learned,catalog):
    if resource not in (3,4,5):raise ValueError('Dog resource required')
    if field.actor(actor_id).owner_id!=owner or field._ability_turns[actor_id]!=0:
        raise ValueError('Configure owned dog before battle')
    catalog=catalog_for_play(catalog)
    for e in learned:
        if e.ability_id in (12,26):
            row=catalog.get(e.ability_id,e.level)
            field._dog_rules[(actor_id,e.ability_id)]=(row.number('value'),row.number('AP'),row.number('Cooldown'),e.level)
        elif e.ability_id==23:
            field.configure_dog_healing(owner,actor_id,resource,learned,catalog)
    bonuses={e.ability_id:catalog.get(e.ability_id,e.level).number('value') for e in learned if e.ability_id in (4,15,18)}
    field.combat.dog_bonuses[actor_id]=bonuses


def cast_scent(field,owner,request):
    """Presence-only scent through walls; never disclose unseen enemy cells."""
    from dataclasses import replace
    from .protocol.battle_attack import AttackResult,AttackHit,encode_attack_result
    from .protocol.action_points import encode_action_points
    from .protocol.ability_status import AbilityStatus,encode_ability_status
    a=field._actors.get(request.actor_id)
    rule=field._dog_rules.get((request.actor_id,12))
    if a is None or a.owner_id!=owner or not a.health or rule is None:
        raise ValueError('Living dog with learned scent required')
    if request.ability_id!=12 or request.unknown_u32!=0 or (request.x,request.y)!=(a.x,a.y):
        raise ValueError('Scent targets the dog itself')
    key=(a.actor_id,12);turn=field._ability_turns[a.actor_id]
    if turn<field._cooldowns.get(key,0):raise ValueError('Ability is cooling down')
    if a.action_points<rule[1]:raise ValueError('Insufficient action points')
    detected=any(not field.allied(v.owner_id,owner) and v.health and
                 (v.x-a.x)**2+(v.y-a.y)**2<=rule[0]**2 for v in field._actors.values())
    # Original Skill12 Attack = dog_alarm_near; result2 selects Evade =
    # dog_alarm_fail. The self entry carries no damage or enemy information.
    hits=() if detected else (AttackHit(a.actor_id,0,a.health,flags=2),)
    replies=(encode_attack_result(AttackResult(a.actor_id,(a.x,a.y),(a.x,a.y),333,hits,skill_id=12)),
             encode_action_points(a.actor_id,a.action_points-rule[1]),
             encode_ability_status(a.actor_id,[AbilityStatus(12,rule[3],3,rule[2])]))
    field._actors[a.actor_id]=replace(a,action_points=a.action_points-rule[1])
    field._cooldowns[key]=turn+rule[2]
    return replies
