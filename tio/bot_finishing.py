"""Read-only, bounded kill forecasts for currently visible arena opponents.

Use the current combat rules and known HP, never the combat RNG or a future
roll. A forecast is a probability, so every committed hit/miss is replanned.
"""
from collections import defaultdict
from copy import copy
from dataclasses import replace
from functools import lru_cache

from .combat_distance import combat_distance

FINISH_CHANCE=0.80
MAX_ATTACKS=8


@lru_cache(maxsize=256)
def damage_distribution(low,high,accuracy,projectiles,critical,defense):
    """Exact ordinary burst distribution, including misses and integer shares.

    Critical chance belongs to the attacker. Armor is applied to the complete
    burst, exactly as Combat does, rather than once per consumed projectile.
    This calculation does not consume or inspect the combat random stream.
    """
    from .armor import mitigate
    full={0:1.0};hit=accuracy/100;crit=critical/100
    for index in range(projectiles):
        projectile=defaultdict(float);projectile[0]+=1-hit
        probability=hit/(high-low+1)
        for raw in range(low,high+1):
            share=raw*(index+1)//projectiles-raw*index//projectiles
            projectile[share]+=probability*(1-crit)
            projectile[share*2]+=probability*crit
        combined=defaultdict(float)
        for damage,p in full.items():
            for share,q in projectile.items():
                if q:combined[damage+share]+=p*q
        full=combined
    result=defaultdict(float)
    for raw,p in full.items():result[mitigate(raw,defense)[0]]+=p
    return tuple(sorted((damage,p) for damage,p in result.items() if p))


def forecast(field,identity,cell,target,weapon):
    """Own equipped weapon/proficiency and a visible target's worn protection."""
    from .tactical_bot import items_for
    from .weapon_proficiency import damage_endpoint
    combat=field.combat;bag=items_for(field,identity)
    primary=next((i for i in bag if i.equipped and i.client_slot==16),None)
    effective=min(primary.unknown_bytes_03[0],combat.enhancement_caps[identity]) if primary else 0
    bonus=combat.enhancement_rules.bonus(effective) if primary and primary.template_id in combat.enhancement_rules.items else 0
    distance=combat_distance(cell,(target.x,target.y))
    low,high=combat.catalog.distance_damage(weapon.template_id,distance,bonus)
    profile=combat.proficiencies.get(identity)
    if profile is not None:
        skill=combat.proficiency_rules.value(profile,combat.human[identity],weapon.weapon_type)
        if weapon.weapon_type=='Melee':
            from .equipment_bonuses import bonuses
            skill=min(200,skill+bonuses(combat.inventories[identity],combat.resources[identity])['melee'])
        low,high=damage_endpoint(low,skill),damage_endpoint(high,skill)
    dog=combat.dog_bonuses.get(identity,{}) if weapon.template_id==333 else {}
    accuracy_bonus=dog.get(18,0)+combat.weapon_accuracy_bonuses.get(identity,{}).get(weapon.weapon_type,0)
    accuracy=combat.catalog.accuracy(weapon.template_id,distance,accuracy_bonus)
    source=combat.catalog.sources[weapon.template_id]
    critical=(int(source.get('critical',0))+combat.human_critical_bonuses.get(identity,0)
              if combat.resources[identity] in (1,2,6) else
              int(source.get('critical',0))+dog.get(4,0) if identity in combat.dog_bonuses else 0)
    return damage_distribution(low,high,accuracy,max(1,weapon.bullets_count),
                               max(0,min(100,critical)),combat.defense(target.actor_id))


def attacks_to_finish(distribution,health,maximum):
    """Fewest affordable attacks with at least an 80% current kill chance."""
    if not distribution or max(d for d,p in distribution)*maximum<health:return None
    alive={health:1.0};killed=0.0
    for count in range(1,maximum+1):
        remaining=defaultdict(float)
        for hp,p in alive.items():
            for damage,q in distribution:
                if damage>=hp:killed+=p*q
                else:remaining[hp-damage]+=p*q
        if killed+1e-12>=FINISH_CHANCE:return count,killed
        alive=remaining
    return None


def finish_plan(field,identity,enemies,known):
    """Prioritize an affordable kill, reserving cover from other known enemies.

    Candidate positions and occupancy come from the same bounded search as
    ordinary fire/retreat. No opponent outside the current sight set is read.
    """
    from .tactical_bot import weapon_for,items_for,routes,path_to,can_fire,retreat_path
    actor=field.actor(identity);weapon=weapon_for(field,identity)
    if weapon is None or actor.action_points<weapon.attack_ap or not enemies:return None
    maximum=min(MAX_ATTACKS,actor.action_points//weapon.attack_ap)
    if weapon.ammo_id:
        maximum=min(maximum,sum(i.count for i in items_for(field,identity)
                                if i.template_id==weapon.ammo_id)//weapon.bullets_count)
    if not maximum:return None
    previous,depth=routes(field,identity,known,(actor.action_points-weapon.attack_ap)//field.step_cost)
    candidates=[];estimates={};finishes={};positions=0
    for cell in sorted(depth,key=lambda p:(depth[p],p)):
        affordable=min(maximum,(actor.action_points-depth[cell]*field.step_cost)//weapon.attack_ap)
        firing=False
        for target in sorted(enemies,key=lambda a:(a.health,a.actor_id)):
            if not can_fire(field,cell,target,weapon):continue
            firing=True
            key=target.actor_id,combat_distance(cell,(target.x,target.y))
            if key not in estimates:estimates[key]=forecast(field,identity,cell,target,weapon)
            finish_key=(*key,affordable)
            if finish_key not in finishes:finishes[finish_key]=attacks_to_finish(estimates[key],target.health,affordable)
            finish=finishes[finish_key]
            if finish is not None:
                shots,chance=finish;cost=depth[cell]*field.step_cost+shots*weapon.attack_ap
                candidates.append((cost,-chance,depth[cell],target.actor_id,cell,target))
        # The closest 48 firing positions cover the existing fire-policy bound.
        if firing:positions+=1
        if positions>=48:break
    for cost,_,_,_,cell,target in sorted(candidates):
        others=tuple(e for e in enemies if e.actor_id!=target.actor_id)
        cover=()
        if others:
            shadow=copy(field);shadow._actors=dict(field._actors)
            shadow._actors[identity]=replace(actor,x=cell[0],y=cell[1])
            shadow._actors[target.actor_id]=replace(target,health=0)
            cover=retreat_path(shadow,identity,others,known,actor.action_points-cost)
            if cover is None:continue
        return path_to(previous,cell),target.actor_id,cover
    return None
