"""Shared saved mines and burns using native battle notifications.

Legacy XML lacks Land Mine damage, flame fuel and effect duration. Balance
choices are declared in config/special_items.json, never supplied by clients.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import json
from pathlib import Path
from typing import TYPE_CHECKING

from .combat_distance import combat_distance
from .protocol.battle_attack import AttackHit, AttackResult, encode_attack_result
from .protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from .protocol.known_mines import KnownMine, encode_known_mines
from .protocol.battle_mines import MineDeployed, encode_mine_deployed
from .visibility import clear_sight, field_sight

if TYPE_CHECKING:
    from .battle_state import BattleActor
    from .combat import Combat
    from .protocol.item_action import ItemAction
    from .protocol.mine_defuse import MineDefuse
    from .visibility import VisibilityView

MINE_SKILL = 'Engineering'


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
    if not hasattr(combat,'mine_discoveries'):combat.mine_discoveries={}
    if not hasattr(combat,'mine_scans'):combat.mine_scans={}
    if not hasattr(combat,'hazard_damage'):combat.hazard_damage={}
    if not hasattr(combat,'sight_kill_victims'):
        combat.sight_kill_victims={victim for _,victim in combat.rank_kills}


def known_mine_ids(combat: Combat, owner: int) -> set[int]:
    initialize(combat)
    return {m.identity for m in combat.mines.values()
            if combat.field.allied(m.source.owner_id, owner) or owner in combat.mine_discoveries.get(m.identity, ())}


def known_mines(combat,owner):
    field = combat.field
    mines = (combat.mines[i] for i in sorted(known_mine_ids(combat, owner)))
    return encode_known_mines(KnownMine(m.x,m.y,m.template_id,field.teams.get(m.source.owner_id,0))
        for m in mines)


def is_mine_finder(template_id: int) -> bool:
    from .durability import definitions
    return definitions().get(template_id, {}).get('item_type') == 'minefinder'


def _use_device(combat: Combat, actor: BattleActor, selected: ItemRecord,
                items: tuple[ItemRecord, ...], flag: int, *, train: bool,
                view: VisibilityView | None) -> tuple[bytes, ...]:
    from .battle_item_effects import _atomic, _pay, _train_proficiency
    from .durability import definitions, wear
    cost = int(definitions()[selected.template_id]['actionPoints'])
    if not 1 <= cost <= 255:
        raise ValueError('Invalid mine device AP')
    remaining = wear(selected, 1)
    inventory = encode_item_list(actor.actor_id, tuple(
        remaining if i == selected else i for i in items if i != selected or remaining is not None), flag)
    trained = _train_proficiency(combat, actor, cost, MINE_SKILL) if train else None

    def spend():
        replies = _pay(combat, actor, cost, inventory, trained=trained)
        if view is not None and trained is not None:
            replies += view.snapshot_packets(actor.actor_id)
        return replies

    return _atomic(combat, spend, views=() if view is None else (view,))


def find_mines(combat: Combat, owner: int, action: ItemAction, *,
               view: VisibilityView | None = None) -> tuple[bytes, ...]:
    from .battle_item_effects import _actor, _selected
    from .durability import definitions
    actor = _actor(combat, owner, action.pet_id)
    selected, items, flag = _selected(combat, actor, action.instance_id)
    if (action.option != 255 or not is_mine_finder(selected.template_id) or selected.equipped
            or selected.count != 1 or selected.unknown_words[0] <= 0):
        raise ValueError('Требуется исправный миноискатель в рюкзаке')
    field = combat.field
    known = known_mine_ids(combat, owner)
    generation = field._ability_turns[actor.actor_id]
    origin = (actor.x, actor.y)
    previous_generation, cells = combat.mine_scans.get(actor.actor_id, (-1, frozenset()))
    if generation != previous_generation:
        cells = frozenset()
    if origin in cells:
        return (known_mines(combat, owner),)
    # The original finder tooltip reads the template's power field as a radius.
    radius = int(definitions()[selected.template_id]['power'])
    if not 1 <= radius <= 255:
        raise ValueError('Invalid mine finder radius')
    found = [mine.identity for mine in combat.mines.values() if mine.identity not in known
             and combat_distance(origin, (mine.x, mine.y)) <= radius
             and field_sight(field, origin, (mine.x, mine.y))]
    replies = _use_device(combat, actor, selected, items, flag, train=bool(found), view=view)
    for identity in found:
        combat.mine_discoveries[identity] = combat.mine_discoveries.get(identity, frozenset()) | {owner}
    combat.mine_scans[actor.actor_id] = (generation, cells | {origin})
    return (*replies, known_mines(combat, owner))


def defuse_mine(combat: Combat, owner: int, request: MineDefuse, *,
                view: VisibilityView | None = None) -> tuple[bytes, ...]:
    from .battle_item_effects import _actor
    from .durability import definitions
    actor = _actor(combat, owner, request.actor_id)
    field = combat.field
    position = (request.x, request.y)
    known = known_mine_ids(combat, owner)
    mine = next((m for m in combat.mines.values() if m.identity in known and (m.x, m.y) == position), None)
    if (mine is None or not field.inside(*position) or combat_distance((actor.x, actor.y), position) != 1
            or not field_sight(field, (actor.x, actor.y), position)
            or any(a.health and (a.x, a.y) == position for a in field._actors.values())):
        raise ValueError('Нужна известная мина на свободной соседней клетке')
    _, items, flag = decode_item_list(combat.inventories[actor.actor_id])
    # C8/40 has no instance ID. Select the first usable probe by stable inventory ID.
    catalogue = definitions()
    selected = min((i for i in items if i.count == 1 and not i.equipped and i.unknown_words[0] > 0
                    and catalogue.get(i.template_id, {}).get('item_type') == 'defuse'),
                   key=lambda i: i.instance_id, default=None)
    if selected is None:
        raise ValueError('Требуется исправный щуп в рюкзаке')
    removed = encode_mine_deployed(MineDeployed(actor.actor_id, mine.x, mine.y, mine.template_id, 3))
    replies = _use_device(combat, actor, selected, items, flag,
                          train=not field.allied(mine.source.owner_id, owner), view=view)
    del combat.mines[mine.identity]
    combat.mine_discoveries.pop(mine.identity, None)
    return (*replies, removed)


def deploy(combat,owner,request,*,view=None):
    from .battle_item_effects import _pay, _train_proficiency
    from .weapon_proficiency import damage_endpoint

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
    spent_ap=field.weapon_ap_cost(rule['ap'])
    if actor.action_points<spent_ap:raise ValueError('Insufficient action points')
    inventory=encode_item_list(actor.actor_id,tuple(i for i in items if i!=selected),flag)
    low, high = rule['damage_base'], rule['damage_base'] + rule['damage_random']
    profile = combat.proficiencies.get(actor.actor_id)
    if profile is not None:
        skill = combat.proficiency_rules.value(profile, True, MINE_SKILL)
        skill = min(skill, getattr(combat, 'ranked_limits', {}).get(actor.actor_id, 200))
        low, high = damage_endpoint(low, skill), damage_endpoint(high, skill)
    mine=PlantedMine(combat.mine_sequence,actor,selected.template_id,request.x,request.y,
        low,high-low,rule['radius'])
    from .implant_battle import extras
    if 19 in extras(combat,actor.actor_id):
        from .implants import policy
        factor=100+policy()['extra']['effects']['19']['percent']
        mine=replace(mine,damage_base=mine.damage_base*factor//100,damage_random=mine.damage_random*factor//100)
    # shortcut: successful mining actions use the existing proficiency gains until original server coefficients are known.
    trained = _train_proficiency(combat, actor, rule['ap'], MINE_SKILL)
    deployed = encode_mine_deployed(MineDeployed(actor.actor_id, mine.x, mine.y, mine.template_id))
    replies = (deployed, *_pay(combat, actor, spent_ap, inventory, trained=trained))
    combat.mines[mine.identity]=mine;combat.mine_sequence+=1
    if view is not None and (selected.equipped or trained is not None):
        if selected.equipped:
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
    combat.mine_discoveries.pop(mine.identity, None)
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
