"""Combine real account squads into one field without changing saved IDs."""
from dataclasses import replace
import json
from pathlib import Path

from .abilities import AbilityCatalog, AbilityLevel
from .battle_state import BattleField
from .combat import Combat
from .map_generation import generate_map
from .protocol.item_list import decode_item_list, encode_item_list
from .protocol.battle_soldier import decode_battle_soldier
from .protocol.abilities import encode_abilities, decode_abilities
from .protocol.battle_ground import encode_battle_ground
from .visibility import VisibilityView


def require_assault_location(town, levels, world=None):
    """Validate a trusted assault builder's admitted territory or training base."""
    levels=tuple(levels)
    if world is not None and world['profile']=='assault_training':
        from .world_completion import require_location
        return require_location(town,levels,training=True)
    from .territories import CONFIG,load_config
    _,territories=load_config(CONFIG)
    territory=territories.get(town)
    if territory is None or territory['enabled'] is not True:
        raise ValueError('Территория не поддерживает штурм')
    lo,hi=territory['levels']
    if not levels or any(type(n) is not int or not lo<=n<=hi for n in levels):
        raise ValueError('Бойцы не соответствуют уровням территории')
    return world


def survival_deployment(arena, seats):
    """Separate 3/4 hostile squads on reachable cells in the original map.

    The manual defines free-for-all ownership, not a historical spawn formula.
    Corner anchors and nearest open cells are explicit server placement policy.
    """
    from .map_generation import reachable_cells
    width,height=arena.ground.width,arena.ground.height
    anchors=((width//2,2),(2,height-3),(width-3,height-3)) if len(seats)==3 else (
        (2,2),(width-3,2),(width-3,height-3),(2,height-3))
    available=set(reachable_cells(arena))-set(arena.containers)-{p[:2] for p in arena.doors}
    result={}
    for seat,anchor in zip(seats,anchors):
        owner,side,path,account,ticket,bot=seat
        cells=sorted(available,key=lambda p:((p[0]-anchor[0])**2+(p[1]-anchor[1])**2,p))
        chosen=tuple(cells[:len(ticket.actors)])
        if len(chosen)!=len(ticket.actors):raise ValueError('Insufficient survival deployment cells')
        result[owner]=chosen
        available.difference_update(chosen)
    return result


def prepare(seats, mode, *, seed=None, ranked=False, profile='reservation',arena_map=None,selected_ids=False,wager=False,map_size=None,town_id=None):
    """Seats: (unique owner, side, path, account, ticket, is_bot)."""
    from tools.survival_scene import prepare_survival
    raw=json.loads((Path(__file__).resolve().parents[1]/'config/abilities.json').read_text())
    catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in raw['records'])
    size=max(len(s[4].actors) for s in seats)
    world=None
    if town_id is not None:
        from .world_completion import location
        world=location(town_id)
        levels=tuple(l for s in seats for l in s[4].levels)
        if arena_map is not None and profile=='assault':
            # Only the trusted assault path supplies both the profile and map.
            # Ordinary matchmaking retains the city's own admission rules.
            world=require_assault_location(town_id,levels,world)
        else:
            from .cities import require_arena
            city=require_arena(town_id,levels);profile=city.profile
    elif profile=='detroit':
        from .world_completion import require_location
        town_id=18;world=require_location(18,tuple(l for s in seats for l in s[4].levels))
    deployment_size=max(3,len(seats)//2*size)
    if arena_map is not None:generated=None
    elif ranked:
        from .contest_maps import generate as generate_contest
        generated=generate_contest(seed=seed,deployment_size=deployment_size)
    elif world is not None and map_size is None:
        from .world_completion import generate_world_map
        generated=generate_world_map(town_id,seed=seed,deployment_size=deployment_size,mode=mode)
    else:generated=generate_map(profile,seed=seed,deployment_size=deployment_size,mode=mode,map_size=map_size)
    arena_map=arena_map if generated is None else generated.arena
    free_for_all=mode==0 and len(seats) in (3,4) and not ranked
    deployment=survival_deployment(arena_map,seats) if free_for_all else None
    cache={};actors=[];sources={};side_index={s[1]:0 for s in seats};identity=0x40000000
    for owner,side,path,account,ticket,bot in seats:
        key=(str(path),account)
        if key not in cache:
            from .matchmaking import SurvivalQueue
            from .owned_pets import OwnedPetStore
            full=SurvivalQueue().join(owner,OwnedPetStore(path).list(account),mode=mode) if mode==0 and not ranked and not selected_ids else ticket
            if (full.actors[:len(ticket.actors)],full.levels[:len(ticket.levels)])!=(ticket.actors,ticket.levels):
                raise ValueError('Selected squad changed during matchmaking')
            cache[key]=prepare_survival(path,account,full,catalog,arena_map=arena_map,mode=mode,
                                        admitted_prefix=mode in (1,4) and not selected_ids,selected_ids=ranked or selected_ids,
                                        allow_mixed_levels=wager,ranked=ranked)
        original=cache[key]
        for local in ticket.actors:
            identity+=1
            spawn=deployment[owner][side_index[side]] if free_for_all else (
                arena_map.player_spawns,arena_map.bot_spawns)[side][side_index[side]]
            side_index[side]+=1
            actor=original.field.actor(local)
            actors.append(replace(actor,actor_id=identity,owner_id=owner,x=spawn[0],y=spawn[1]))
            sources[identity]=(original,local,path,account,bot,side)
    field=BattleField(arena_map.ground.width,arena_map.ground.height,actors,
        blocked=arena_map.blocked,step_cost=1,teams={s[0]:s[1] for s in seats},
        transparent_obstacles=arena_map.transparent_obstacles)
    field.battle_mode=mode;field.patrol_waypoints=generated.patrol if generated else ()
    from .avatars import selections
    avatar_sources={}
    for identity,(_,local,path,account,bot,_) in sources.items():
        key=(str(path),account)
        if key not in avatar_sources:avatar_sources[key]=selections(path,account) if path and account and not bot else {}
    field.avatar_ids={identity:avatar_sources[(str(path),account)].get(local,0) for identity,(_,local,path,account,bot,_) in sources.items()}
    field.scene_metadata=dict(profile=generated.profile if generated else profile,
        variant=generated.variant if generated else 'original_assault',seed=generated.seed if generated else seed,
        width=field.width,height=field.height,objects=generated.layout['objects'] if generated else (),
        crates=len(arena_map.containers),doors=len(arena_map.doors))
    if generated and generated.profile=='trueskill_contest':
        field.scene_metadata['control_points']=generated.layout['control_points']
    if world is not None:
        field.scene_metadata['world_policy']=dict(version=1,town_id=town_id,
            levels=tuple(world['levels']),carry_items=world['carry_items'],max_upgrade=world['max_upgrade'],
            rank_gain=town_id!=4,map_geometry='original_assault_v1' if generated is None else
                'original_whole_map_v1' if town_id==18 else 'procedural_military_v1',
            bonus_crates=town_id==4)
    sample=next(iter(cache.values()))
    field.combat=Combat(field,sample.field.combat.catalog)
    templates={};skills={};permissions={}
    for identity,(original,local,path,account,bot,side) in sources.items():
        actor=field.actor(identity);old=original.field.combat
        field._turn_points[identity]=original.field._turn_points[local]
        _,items,flag=decode_item_list(old.inventories[local])
        inventory=encode_item_list(identity,items,flag)
        field.combat.register(identity,inventory,human=old.human[local],
            path=None if bot else path,account=account,pet_packet=old.proficiencies[local])
        field.combat.storage_ids[identity]=local
        for name in ('miner_defense','dog_bonuses','weapon_accuracy_bonuses','human_critical_bonuses','weight_capacities','display_unarmored_bonuses','learned','skill_lists'):
            if local in getattr(old,name):getattr(field.combat,name)[identity]=getattr(old,name)[local]
        for name in ('_healing_rules','_slash_rules','_dog_rules'):
            for (actor_id,ability),value in getattr(original.field,name).items():
                if actor_id==local:getattr(field,name)[identity,ability]=value
        permissions[identity]=original.field.doors.permissions.get(local,frozenset())
        t=original.visibility.templates[local]
        color=next(i for i,s in enumerate(seats) if s[0]==actor.owner_id)
        templates[identity]=replace(t,fields={**t.fields,'0x8c5088':identity,
            '0x8c50ea':actor.owner_id,'0x8c519b':actor.x,'0x8c51af':actor.y,
            '0x8c5187':side,'0x8c5173':color,
            '0x8c5116':b'AI bot' if bot else t.fields['0x8c5116']})
        found=next((p for p in original.packets if p[:1]==b'\x80' and int.from_bytes(p[1:5],'little')==local),None)
        if found:
            _,learned,_=decode_abilities(found)
            skills[identity]=encode_abilities(identity,learned)
        if bot or (world is not None and not world['carry_items']):
            base=None
            if bot:
                from contextlib import closing
                from .db_transaction import connect
                with closing(connect(path)) as db:
                    row=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,local)).fetchone()
                if row is None:raise ValueError('Transient Outpost source disappeared')
                base=bytes(row[0])
            templates[identity],skills[identity]=field.combat.exclude_personal_equipment(
                identity,catalog,templates[identity],pet_packet=base)
    from .battle_doors import BattleDoors
    from .battle_loot import BattleLoot
    field.doors=BattleDoors(field,arena_map.doors,permissions)
    field.loot=BattleLoot(field.combat,arena_map.containers,level=max(l for s in seats for l in s[4].levels))
    # Transient seats may have no persistence route. Their excluded personal
    # IDs still reserve match namespace, just like the real owners' saved IDs.
    field.loot.next_id=max(field.loot.next_id,1+max((i.instance_id
        for p in field.combat.personal_inventories.values() for i in decode_item_list(p)[1]),default=0))
    if world is not None and generated is not None:
        import random
        field.loot.rng=random.Random(generated.seed ^ 0x4C4F4F545F54494F)
        if town_id==4:
            # Outpost supplies are battle-only; personal gear is retained in
            # Combat.personal_inventories for both persistence CAS projections.
            for position in field.loot.boxes:field.loot.boxes[position]=field.loot._roll()
    views={owner:VisibilityView(field,owner,dict(templates)) for owner,_,_,_,_,bot in seats if not bot}
    return field,views,encode_battle_ground(arena_map.ground),skills
