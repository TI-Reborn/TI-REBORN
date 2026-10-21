"""Shared saved mines and burns using native battle notifications.

Legacy XML lacks Land Mine damage, flame fuel and effect duration. Balance
choices are declared in config/special_items.json, never supplied by clients.
"""
from dataclasses import dataclass, replace
from functools import lru_cache
import json
from pathlib import Path

from .combat_distance import combat_distance
from .protocol.battle_attack import AttackHit, AttackResult, encode_attack_result
from .protocol.item_list import decode_item_list, encode_item_list
from .protocol.action_points import encode_action_points
from .protocol.known_mines import KnownMine, encode_known_mines
from .protocol.battle_mines import MineDeployed, encode_mine_deployed
from .visibility import clear_sight


@lru_cache(maxsize=1)
def rules():
    value=json.loads((Path(__file__).resolve().parents[1]/'config/special_items.json').read_text(encoding='utf-8'))
    if not 1<=value['mine_limit_per_battle']<=128:raise ValueError('Invalid mine limit')
    for rule in value['mines'].values():
        if any(type(rule[k]) is not int or rule[k]<1 for k in ('damage_base','radius','ap','credits')) or rule['damage_random']<0:
            raise ValueError('Invalid mine policy')
    for rule in value['burns'].values():
        if not 1<=rule['damage']<=65535 or not 1<=rule['turns']<=10:raise ValueError('Invalid burn policy')
    return value


@dataclass(frozen=True)
class PlantedMine:
    identity: int
    source: object
    template_id: int
    x: int
    y: int
    damage_base: int
    damage_random: int
    radius: int


@dataclass(frozen=True)
class Burn:
    source: object
    template_id: int
    damage: int
    remaining: int
    last_generation: int


def initialize(combat):
    # Restored snapshots from earlier builds have no hazard attributes.
    if not hasattr(combat,'mines'):combat.mines={}
    if not hasattr(combat,'burns'):combat.burns={}
    if not hasattr(combat,'mine_sequence'):combat.mine_sequence=1
    if not hasattr(combat,'hazard_damage'):combat.hazard_damage={}
    if not hasattr(combat,'sight_kill_victims'):
        combat.sight_kill_victims={victim for _,victim in combat.rank_kills}


def known_mines(combat,owner):
    initialize(combat);field=combat.field
    return encode_known_mines(KnownMine(m.x,m.y,m.template_id,field.teams.get(m.source.owner_id,0))
        for m in sorted(combat.mines.values(),key=lambda m:m.identity) if field.allied(m.source.owner_id,owner))


def deploy(combat,owner,request,*,view=None):
    initialize(combat);field=combat.field
    actor=field._actors.get(request.actor_id)
    if actor is None or actor.owner_id!=owner or not actor.health or not combat.human.get(actor.actor_id):
        raise ValueError('Living owned human required to deploy a mine')
    if not field.inside(request.x,request.y) or (request.x,request.y) in field.blocked:
        raise ValueError('Mine cell is blocked or outside map')
    if combat_distance((actor.x,actor.y),(request.x,request.y))!=1:
        raise ValueError('Mine must be placed on an adjacent cell')
    if not clear_sight((actor.x,actor.y),(request.x,request.y),field.blocked):raise ValueError('Mine placement is blocked')
    if any(a.health and (a.x,a.y)==(request.x,request.y) for a in field._actors.values()):raise ValueError('Mine cell is occupied')
    if any((m.x,m.y)==(request.x,request.y) for m in combat.mines.values()):raise ValueError('Mine already deployed here')
    if len(combat.mines)>=rules()['mine_limit_per_battle']:raise ValueError('Battle mine limit reached')
    old=combat.inventories[actor.actor_id];_,items,flag=decode_item_list(old)
    selected=next((i for i in items if i.instance_id==request.instance_id),None)
    rule=None if selected is None else rules()['mines'].get(str(selected.template_id))
    from .durability import broken
    if rule is None or selected.count!=1 or broken(selected):raise ValueError('Owned usable mine required')
    if actor.action_points<rule['ap']:raise ValueError('Insufficient action points')
    inventory=encode_item_list(actor.actor_id,tuple(i for i in items if i!=selected),flag)
    mine=PlantedMine(combat.mine_sequence,actor,selected.template_id,request.x,request.y,
        rule['damage_base'],rule['damage_random'],rule['radius'])
    state=replace(actor,action_points=actor.action_points-rule['ap'],weapons=combat.catalog.equipped(inventory,human=True,resource=combat.resources[actor.actor_id]))
    replies=(encode_mine_deployed(MineDeployed(actor.actor_id,mine.x,mine.y,mine.template_id)),
             encode_action_points(actor.actor_id,state.action_points),combat.inventory_packet(actor.actor_id,inventory))
    combat._persist_batch({actor.actor_id:inventory})
    combat.inventories[actor.actor_id]=inventory;field._actors[actor.actor_id]=state
    combat.mines[mine.identity]=mine;combat.mine_sequence+=1
    if view is not None and selected.equipped:
        from .durability import refresh_template
        refresh_template(combat,view,actor.actor_id)
        replies+=view.snapshot_packets(actor.actor_id)
    return (*replies,known_mines(combat,owner),*combat.skill_packets(actor.actor_id))


def stop_path(combat,path):
    initialize(combat)
    positions={(m.x,m.y) for m in combat.mines.values()}
    for index,position in enumerate(path):
        if position in positions:return path[:index+1]
    return path


def apply_damage(combat,source,template,target,victims,raw,*,periodic=False):
    from .battle_item_effects import _atomic
    return _atomic(combat,lambda:_apply_damage(combat,source,template,target,victims,raw,periodic=periodic))


def _apply_damage(combat,source,template,target,victims,raw,*,periodic=False):
    """One atomic armor/loot/inventory update before authoritative HP changes."""
    field=combat.field;states={};changes={};hits=[];damaged=[]
    statistics={o:dict(v) for o,v in combat.statistics.items()};kills=[]
    hazard_damage=dict(combat.hazard_damage)
    from .armor import mitigate
    from .durability import wear_inventory
    from .premium import current as premium_current
    remainders=dict(combat.premium_wear_remainders)
    def counters(owner):return statistics.setdefault(owner,dict(kills=0,losses=0,damage_dealt=0,damage_received=0))
    # A reused/stale victim list cannot apply a second death or resurrect HP.
    victims=(field._actors.get(identity) for identity in sorted({a.actor_id for a in victims}))
    for victim in victims:
        if victim is None or not victim.health:continue
        reduced,absorbed=mitigate(raw(victim),combat.defense(victim.actor_id))
        damage=min(victim.health,reduced)
        states[victim.actor_id]=replace(victim,health=victim.health-damage,action_points=0 if damage==victim.health else victim.action_points)
        hits.append(AttackHit(victim.actor_id,damage,victim.health-damage,absorbed_damage=min(65535,absorbed)))
        counters(victim.owner_id)['damage_received']+=damage
        if not field.allied(source.owner_id,victim.owner_id):
            counters(source.owner_id)['damage_dealt']+=damage
            if damage:
                pair=(source.owner_id,victim.owner_id)
                hazard_damage[pair]=hazard_damage.get(pair,0)+damage
            if damage and damage==victim.health:
                counters(source.owner_id)['kills']+=1;kills.append((source.actor_id,victim.actor_id))
        if damage and damage==victim.health:counters(victim.owner_id)['losses']+=1
        if victim.actor_id in combat.inventories and damage:
            premium=premium_current(*combat.persistence[victim.actor_id])[0] if victim.actor_id in combat.persistence else 0
            inventory=wear_inventory(combat.inventories[victim.actor_id],armor_damage=reduced,half_wear=premium==3,remainders=remainders)
            if inventory!=combat.inventories[victim.actor_id]:changes[victim.actor_id]=inventory
        damaged.append((victim,damage))
    loot=getattr(field,'loot',None);staged=loot.stage_deaths(states,changes) if loot is not None else None
    old_armor={i:combat.displayed_armor(i) for i in changes}
    from .equipment_bonuses import bonuses
    for identity,inventory in changes.items():
        previous=field.actor(identity)
        sight_delta=bonuses(inventory,combat.resources[identity])['sight']-bonuses(combat.inventories[identity],combat.resources[identity])['sight']
        states[identity]=replace(states.get(identity,previous),
            weapons=combat.catalog.equipped(inventory,human=combat.human[identity],resource=combat.resources[identity]),
            sight_radius=previous.sight_radius+sight_delta)
    sight_awards,sight_changed=combat.stage_kill_sight(states,kills)
    # 4B replays the source weapon animation (including a new grenade throw).
    # Existing fire changes only victim HP; keep kill credit on the server.
    from .protocol.health import encode_health
    replies=(tuple(encode_health(h.actor_id,h.left_hp) for h in hits) if periodic else
        (encode_attack_result(AttackResult(source.actor_id,(source.x,source.y),target,template,tuple(hits),mine_state=1 if template in (321,325) else None)),))
    replies+=tuple(combat.inventory_packet(i,p) for i,p in changes.items())
    combat._persist_batch(changes)
    combat.inventories.update(changes);field._actors.update(states)
    combat.sight_kill_victims=sight_awards
    combat.statistics=statistics;combat.hazard_damage=hazard_damage
    combat.rank_kills.extend(kills);combat.premium_wear_remainders=remainders
    if staged is not None:loot.boxes.update(staged[0]);loot.ground.update(staged[1])
    if getattr(field,'practice',None) is None:
        before_xp=dict(combat.experience.totals)
        for victim,damage in damaged:combat.experience.damage(combat,source,victim,damage)
        from .battle_item_effects import freeze_experience,freeze_rank_kills
        event_time=__import__('time').time()
        freeze_experience(combat,before_xp,now=event_time)
        freeze_rank_kills(combat,kills,now=event_time)
        from .visibility import visible_actors
        visible=visible_actors(field,source.owner_id)
        outcomes=[(victim,True,False,damage==victim.health,victim.actor_id in visible)
            for victim,damage in damaged if damage and not field.allied(source.owner_id,victim.owner_id)]
        combat.achievements.attack(source,field._ability_turns.get(source.actor_id,0),template,
            combat.catalog.weapons[template].weapon_type,outcomes)
    from .armor_display import encode_armor
    from .battle_item_effects import refresh_sight
    replies+=refresh_sight(combat)
    replies+=tuple(encode_armor(i,combat.displayed_armor(i)) for i in changes if old_armor[i]!=combat.displayed_armor(i))
    view=getattr(field,'result_view',None)
    if view is not None:
        replies+=tuple(p for identity in sorted(sight_changed)
            if identity in view.visible and field.actor(identity).health for p in view.snapshot_packets(identity))
        replies+=view.refresh()
    return replies


def after_move(combat,actor_id,path=()):
    initialize(combat);field=combat.field;actor=field.actor(actor_id)
    mine=next((m for m in combat.mines.values() if (m.x,m.y)==(actor.x,actor.y)),None)
    fire=fire_damage(combat,actor_id,path=path)
    actor=field.actor(actor_id)
    if mine is None or not actor.health:return fire
    victims=[a for a in field._actors.values() if a.health and
        (a.x-mine.x)**2+(a.y-mine.y)**2<=mine.radius**2 and clear_sight((mine.x,mine.y),(a.x,a.y),field.blocked)]
    replies=apply_damage(combat,mine.source,mine.template_id,(mine.x,mine.y),victims,
        lambda victim:mine.damage_base+combat.rng.randint(0,mine.damage_random))
    del combat.mines[mine.identity]
    return (*fire,*replies)


def fire_areas(combat):
    from .battle_item_effects import initialize as item_state
    fires=item_state(combat).setdefault('fires',{})
    generation=max(combat.field._ability_turns.values(),default=0)
    for identity,area in tuple(fires.items()):
        if generation>=area['expiry']:del fires[identity]
    return fires


def fire_cells(combat,area):
    from .visibility import field_sight
    field=combat.field;cx,cy=area['center'];radius=area['radius']
    return frozenset((x,y) for x in range(max(0,cx-radius),min(field.width,cx+radius+1))
        for y in range(max(0,cy-radius),min(field.height,cy+radius+1))
        if (x-cx)**2+(y-cy)**2<=radius**2 and (x,y) not in field.blocked
        and field_sight(field,(cx,cy),(x,y)))


def add_fire(combat,source,center,radius):
    from .battle_item_effects import initialize as item_state
    state=item_state(combat);fires=fire_areas(combat)
    rule=rules()['burns']['319'];identity=state['sequence'];state['sequence']+=1
    fires[identity]=dict(source=source,center=center,radius=radius,damage=rule['damage'],
        expiry=max(combat.field._ability_turns.values(),default=0)+rule['turns'])
    # Initial explosion is the damage for this generation; no doubled fire tick.
    state.setdefault('fire_ticks',{}).update({a.actor_id:combat.field._ability_turns[a.actor_id]
        for a in combat.field._actors.values() if (a.x,a.y) in fire_cells(combat,fires[identity])})


def fire_damage(combat,identity,*,path=()):
    from .battle_item_effects import initialize as item_state
    actor=combat.field.actor(identity)
    if not actor.health:return ()
    generation=combat.field._ability_turns[identity];ticks=item_state(combat).setdefault('fire_ticks',{})
    if ticks.get(identity)==generation:return ()
    route=set(path or ((actor.x,actor.y),))
    areas=[a for a in fire_areas(combat).values() if route & fire_cells(combat,a)]
    if not areas:return ()
    area=max(areas,key=lambda a:a['damage'])
    replies=apply_damage(combat,area['source'],319,(actor.x,actor.y),(actor,),lambda victim:area['damage'],periodic=True)
    ticks[identity]=generation
    return replies


def add_burns(combat,source,template,victims):
    initialize(combat);rule=rules()['burns'].get(str(template))
    if rule is None:return
    for identity in victims:
        actor=combat.field._actors.get(identity)
        if actor is None or not actor.health:continue
        previous=combat.burns.get(identity)
        damage=max(rule['damage'],previous.damage if previous else 0)
        remaining=max(rule['turns'],previous.remaining if previous else 0)
        combat.burns[identity]=Burn(source,template,damage,remaining,combat.field._ability_turns[identity])


def turn_effects(combat,owner,actor_ids):
    initialize(combat);field=combat.field;replies=[]
    for identity in sorted(set(actor_ids)):
        actor=field._actors.get(identity)
        if actor is None or actor.owner_id!=owner:raise ValueError('Owned burn actor required')
    for identity in sorted(set(actor_ids)):
        replies.extend(fire_damage(combat,identity))
        burn=combat.burns.get(identity);actor=field.actor(identity)
        if burn is None:continue
        if not actor.health:combat.burns.pop(identity,None);continue
        generation=field._ability_turns[identity]
        if generation<=burn.last_generation:continue
        replies.extend(apply_damage(combat,burn.source,burn.template_id,(actor.x,actor.y),(actor,),lambda victim:burn.damage,periodic=True))
        if burn.remaining<=1 or not field.actor(identity).health:combat.burns.pop(identity,None)
        else:combat.burns[identity]=replace(burn,remaining=burn.remaining-1,last_generation=generation)
    return tuple(replies)
