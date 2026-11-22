"""Arena policy: bounded scavenging, treatment, and affordable fire/cover plans.

Planning reads public map geometry, own inventory and currently shared sight.
It never queries hidden actors' positions. Committed actions use the same APIs
as players, including their AP, ammunition, capacity and visibility checks.
"""
from collections import deque
from copy import copy
from dataclasses import replace
from functools import lru_cache
from typing import TYPE_CHECKING

from .combat import MEDICAL_ITEMS
from .combat_distance import combat_distance
from .medical_items import DOG_MEAT, can_use_medical
from .mobs import INFECTED_DOG
from .protocol.battle_attack import AttackRequest, encode_attack_request
from .protocol.battle_move import BattleMove, encode_move_request
from .protocol.battle_loot import LootTransfer, encode_loot_transfer
from .protocol.battle_position import BattlePositionRequest, encode_position_request
from .protocol.item_action import ItemAction, encode_item_action, item_target_option
from .protocol.item_list import decode_item_list, encode_item_list
from .visibility import field_sight
from .weight import inventory_weight, overload_penalty

if TYPE_CHECKING:
    from .turn_planning import TurnObjective, TurnPlan


@lru_cache(maxsize=1)
def armor_catalog():
    from .equipment import armor_rules
    return armor_rules()


def items_for(field, identity):
    return decode_item_list(field.combat.inventories[identity])[1]


def enemies_for(field, owner, identity):
    from .training_bot import bot_known
    known=bot_known(field,owner,identity)
    return tuple(field.actor(i) for i in sorted(known)
                 if field.actor(i).health and not field.allied(field.actor(i).owner_id,owner))


def routes(field, identity, known, steps, *, start=None):
    """Cardinal BFS bounded by AP; occupancy is restricted to known actors."""
    if start is None:
        actor=field.actor(identity);start=(actor.x,actor.y)
    blocked=field.blocked|{(field.actor(i).x,field.actor(i).y) for i in known
                           if i!=identity and field.actor(i).health}
    previous={start:None};depth={start:0};queue=deque([start])
    while queue:
        x,y=queue.popleft()
        if depth[x,y]>=steps:continue
        for cell in ((x-1,y),(x,y-1),(x,y+1),(x+1,y)):
            if cell in previous or cell in blocked or not field.inside(*cell):continue
            previous[cell]=(x,y);depth[cell]=depth[x,y]+1;queue.append(cell)
    return previous,depth


def path_to(previous, cell):
    path=[]
    while previous[cell] is not None:
        path.append(cell);cell=previous[cell]
    return tuple(reversed(path))


def weapon_for(field, identity):
    combat=field.combat;items=items_for(field,identity)
    primary=next((i for i in items if i.equipped and i.client_slot==16),None)
    resource=combat.resources[identity]
    template=primary.template_id if primary else (337 if resource==6 else 300 if combat.human[identity]
                                                 else combat.catalog.npc_defaults.get(resource,333))
    weapon=combat.catalog.weapons[template]
    from .durability import broken
    if primary is not None and broken(primary):return None
    if combat.catalog.sources[template].get('weaponAttack') not in ('Bullet','None'):return None
    if weapon.ammo_id and sum(i.count for i in items if i.template_id==weapon.ammo_id)<weapon.bullets_count:return None
    return weapon


def can_fire(field, cell, target, weapon):
    from .battle_item_effects import clear_item_sight
    end=(target.x,target.y)
    return (1<=combat_distance(cell,end)<=weapon.max_range and field_sight(field,cell,end)
            and clear_item_sight(field.combat,cell,end))


def hidden_cell(field, identity, cell, enemies):
    """Evaluate cover against every *known* hostile observer and its sight.

    A restricted field prevents enemy recon from consulting hidden sources.
    Smoke, illumination, recon and asymmetric sight use the actual sight rules.
    """
    from .battle_item_effects import can_observe
    shadow=copy(field)
    shadow._actors={a.actor_id:a for a in enemies}
    actor=replace(field.actor(identity),x=cell[0],y=cell[1])
    shadow._actors[identity]=actor
    return not any(can_observe(field.combat,e,actor,field=shadow) for e in enemies)


def retreat_path(field, identity, enemies, known, budget, *, hidden_cache=None):
    previous,depth=routes(field,identity,known,max(0,budget)//field.step_cost)
    for cell in sorted(depth,key=lambda p:(depth[p],p)):
        if hidden_cache is None:hidden=hidden_cell(field,identity,cell,enemies)
        else:
            if cell not in hidden_cache:hidden_cache[cell]=hidden_cell(field,identity,cell,enemies)
            hidden=hidden_cache[cell]
        if hidden:return path_to(previous,cell)
    return None


def fire_plan(field, identity, enemies, known):
    """Reserve the weapon's real AP price plus the shortest route out of sight."""
    actor=field.actor(identity);weapon=weapon_for(field,identity)
    if weapon is None or actor.action_points<weapon.attack_ap:return None
    previous,depth=routes(field,identity,known,(actor.action_points-weapon.attack_ap)//field.step_cost)
    # Prefer firing with little exposure and AP cost. Bound costly cover/LOS
    # evaluations on large maps; no scan over unobserved enemy coordinates.
    candidates=[]
    for cell in sorted(depth,key=lambda p:(depth[p],p)):
        for target in sorted(enemies,key=lambda a:(a.health,a.actor_id)):
            if can_fire(field,cell,target,weapon):candidates.append((cell,target))
        if len(candidates)>=48:break
    fallback=None;hidden_cache={}
    for cell,target in candidates:
        approach=path_to(previous,cell)
        remaining=actor.action_points-depth[cell]*field.step_cost-weapon.attack_ap
        shadow=copy(field);shadow._actors=dict(field._actors)
        shadow._actors[identity]=replace(actor,x=cell[0],y=cell[1])
        cover=retreat_path(shadow,identity,enemies,known,remaining,hidden_cache=hidden_cache)
        if cover is not None:return approach,target.actor_id,cover
        if fallback is None:fallback=(approach,target.actor_id,None)
    return fallback


class Actions:
    def __init__(self,arena,owner,view):
        self.arena,self.owner,self.view=arena,owner,view;self.packets=[]

    def do(self,method,packet):
        # Hosted BotEventArena publishes each action to all real clients. The
        # local compatibility route projects the same action for its one view.
        view=self.view
        before=None if view is None else dict(view.field._actors)
        visible=None if view is None else view.visible
        kwargs={}
        if view is not None and method!='move':
            from .visibility import VisibilityView, visible_actors
            own=VisibilityView(view.field,self.owner,dict(view.templates))
            own.visible=visible_actors(view.field,self.owner);kwargs['view']=own
        result=getattr(self.arena,method)(self.owner,packet,**kwargs)
        packets=(result,) if isinstance(result,bytes) else tuple(result or ())
        if view is None:self.packets.extend(packets)
        else:
            from server.battle_events import project_action
            if kwargs:view.templates.update(kwargs['view'].templates)
            self.packets.extend(project_action(view,self.owner,before,visible,packets,visuals=False))
        return result

    def move(self,identity,cell):
        field=next(f for f in self.arena._fields.values() if identity in f._actors)
        doors=getattr(field,'doors',None)
        if doors is not None and doors.states.get(cell) is False:
            from .protocol.battle_door import DoorRequest, encode_door_request
            self.do('door_action',encode_door_request(DoorRequest(identity,True,*cell)))
        return self.move_path(identity, (cell,))

    def move_path(self, identity: int, path: tuple[tuple[int, int], ...]):
        return self.do('move', encode_move_request(BattleMove(identity, path)))

    def item(self,identity,item,slot=None):
        return self.do('equip',encode_item_action(ItemAction(identity,item.instance_id,
                                         255 if slot is None else item_target_option(slot))))


def medical_item(field, identity):
    actor=field.actor(identity)
    if not actor.max_health or actor.health*10>actor.max_health*7:return None
    choices=[i for i in items_for(field,identity) if can_use_medical(i.template_id, field.combat.resources[identity])
             and MEDICAL_ITEMS[i.template_id][1]<=actor.action_points]
    if not choices:return None
    missing=actor.max_health-actor.health
    return min(choices,key=lambda i:(-min(missing,MEDICAL_ITEMS[i.template_id][0])/MEDICAL_ITEMS[i.template_id][1],
                                     MEDICAL_ITEMS[i.template_id][0],i.instance_id))


def heal(field, identity, actions):
    chosen=medical_item(field,identity)
    if chosen is None:return False
    actions.item(identity,chosen);return True


def fits(field, identity, items):
    combat=field.combat
    if len(items)>field.loot.policy['inventory_slots']:return False
    if identity not in combat.weight_capacities:return True
    packet=encode_item_list(identity,items)
    capacity=combat.weight_capacity(identity, packet)
    return overload_penalty(inventory_weight(packet),capacity)==0


def loot_selection(field, identity, contents):
    """One usable weapon, matching ammunition, missing armor and a few kits."""
    from .enhancement_limits import required_level
    from .protocol.pet_info import decode_pet_info
    from .durability import broken
    combat=field.combat;bag=list(items_for(field,identity));selected=[]
    profile=combat.proficiencies.get(identity)
    level=decode_pet_info(profile,human_equipment=combat.human[identity]).fields['0x8c4aef'] if profile else 1
    resource=combat.resources[identity];armor=armor_catalog()
    def add(item,count):
        if count<=0:return False
        take=replace(item,unknown_u32_01=count)
        if not fits(field,identity,(*bag,take)):return False
        bag.append(take);selected.append((item.instance_id,count));return True
    def quantity(item,maximum):
        for count in range(min(item.count,maximum),0,-1):
            if add(item,count):return
    weapon=next((combat.catalog.weapons[i.template_id] for i in bag if i.template_id in combat.catalog.weapons
                 and i.template_id not in (300,333,337) and not broken(i)),None)
    if weapon is None and combat.human[identity]:
        guns=[i for i in contents if i.template_id in combat.catalog.weapons and not broken(i)
              and required_level(i)<=level and i.template_id not in (300,333,337)
              and (combat.catalog.sources[i.template_id].get('freaks_only')=='1')==(resource==6)
              and combat.catalog.sources[i.template_id].get('weaponAttack') in ('Bullet','None')]
        for item in sorted(guns,key=lambda i:-(combat.catalog.weapons[i.template_id].damage_base/
                                               combat.catalog.weapons[i.template_id].attack_ap)):
            w=combat.catalog.weapons[item.template_id]
            ammo=next((a for a in (*bag,*contents) if a.template_id==w.ammo_id and a.count>=w.bullets_count),None)
            if w.ammo_id and ammo is None:continue
            minimum=(*bag,item,replace(ammo,unknown_u32_01=w.bullets_count)) if ammo in contents else (*bag,item)
            if not fits(field,identity,minimum):continue
            if add(item,1):weapon=w;break
    if weapon and weapon.ammo_id:
        needed=max(0,weapon.bullets_count*6-sum(i.count for i in bag if i.template_id==weapon.ammo_id))
        for item in contents:
            if item.template_id==weapon.ammo_id and needed:
                before=sum(n for _,n in selected);quantity(item,needed)
                needed-=sum(n for _,n in selected)-before
    for item in sorted(contents,key=lambda i:i.instance_id):
        if item.template_id in MEDICAL_ITEMS and item.template_id!=DOG_MEAT:
            quantity(item,max(0,3-sum(i.count for i in bag if i.template_id in MEDICAL_ITEMS)))
    covered=set()
    for item in bag:
        if item.template_id in armor:covered.update(armor[item.template_id].get('covers',(armor[item.template_id]['slot'],)))
    for item in contents:
        rule=armor.get(item.template_id)
        if rule is None or broken(item) or required_level(item)>level:continue
        allowed=resource==6 if rule.get('miner') else resource in (3,4,5) if rule['dog'] else resource in (1,2)
        covers=set(rule.get('covers',(rule['slot'],)))
        if not allowed or (rule.get('female') and resource!=2) or covers&covered:continue
        if add(item,1):covered.update(covers)
    return tuple(selected)


def equip_found(field, identity, actions):
    from .durability import broken
    armor=armor_catalog();bag=items_for(field,identity)
    primary=next((i for i in bag if i.equipped and i.client_slot==16 and not broken(i)),None)
    covered=set()
    for i in bag:
        if i.equipped and i.template_id in armor:
            covered.update(armor[i.template_id].get('covers',(armor[i.template_id]['slot'],)))
    for item in bag:
        if item.equipped or broken(item):continue
        if item.template_id in field.combat.catalog.weapons and primary is None:
            weapon=field.combat.catalog.weapons[item.template_id]
            if weapon.ammo_id and sum(i.count for i in bag if i.template_id==weapon.ammo_id)<weapon.bullets_count:continue
            actions.item(identity,item,16);primary=item
        elif item.template_id in armor and field.actor(identity).action_points>=2:
            rule=armor[item.template_id];covers=set(rule.get('covers',(rule['slot'],)))
            if not covers&covered:
                actions.item(identity,item,rule['slot']);covered.update(covers)


def scavenge(field, identity, owner, known, actions):
    if not hasattr(field,'loot') or not field.combat.human[identity]:return False
    if not hasattr(field,'bot_crates'):field.bot_crates={}
    visited=field.bot_crates.setdefault(identity,set())
    # Armed and armored bots begin hunting after the first crate, otherwise
    # check a second crate. This state is part of the durable field snapshot.
    equipped=items_for(field,identity)
    ready=weapon_for(field,identity)
    resupply=ready is None and any(i.template_id in field.combat.catalog.weapons for i in equipped)
    if not hasattr(field,'bot_supply_turns'):field.bot_supply_turns={}
    turn=field._ability_turns[identity]
    generation,count=field.bot_supply_turns.get(identity,(turn,0))
    if generation!=turn:count=0
    if (len(visited)>=2 and not resupply) or count>=2 or (visited and ready and ready.template_id not in (300,337)
                          and any(i.equipped and i.template_id in armor_catalog() for i in equipped)):return False
    actor=field.actor(identity)
    previous,depth=routes(field,identity,known,field.width+field.height)
    targets=[]
    for box in field.loot.boxes:
        if box in visited or box in field.loot.ground:continue
        cells=[(box[0]+dx,box[1]+dy) for dx in (-1,0,1) for dy in (-1,0,1)
               if (box[0]+dx,box[1]+dy) in depth]
        if cells:
            cell=min(cells,key=lambda p:(depth[p],p));targets.append((depth[cell],box,cell))
    if not targets:return False
    _,box,cell=min(targets)
    path=path_to(previous,cell)
    if path:
        if actor.action_points<field.step_cost:return False
        actions.move(identity,path[0]);return True
    cost=field.loot.policy['reopen_ap' if box in field.loot.opened else 'unseal_ap']
    if actor.action_points<cost:return False
    actions.do('loot_action',encode_position_request(BattlePositionRequest(identity,*box)))
    # Contents become known only after the authoritative open action.
    selection=loot_selection(field,identity,field.loot.boxes[box])
    actions.do('loot_action',encode_loot_transfer(LootTransfer(identity,*box,withdrawals=selection)))
    visited.add(box)
    field.bot_supply_turns[identity]=(turn,count+1)
    equip_found(field,identity,actions)
    return True


def _execute_plan(actions: Actions, room_id: int, identity: int, plan: 'TurnPlan',
                  known: frozenset[int]) -> bool:
    """Return whether an observation or a miss warrants replanning."""
    from .training_bot import bot_known
    field = actions.arena._fields[room_id]

    def walk(path, *, require_target=False):
        for cell in path:
            actions.move(identity, cell)
            if room_id not in actions.arena._turns:
                return False
            visible = bot_known(field, actions.owner, identity)
            if visible - known or (require_target and plan.target not in visible):
                return False
        return True

    if not walk(plan.before, require_target=plan.target is not None):
        return True
    if plan.medical is not None:
        actions.item(identity, plan.medical)
        return True
    for _ in range(plan.shots):
        target = field.actor(plan.target)
        if not target.health:
            break
        actions.do('attack', encode_attack_request(AttackRequest(identity, target.x, target.y)))
        if room_id not in actions.arena._turns:
            return False
        if field.actor(plan.target).health == target.health or bot_known(field, actions.owner, identity) - known:
            return True
    return not walk(plan.after)


def play_actor(arena, room_id, owner, identity, *, view=None,
               objective: 'TurnObjective | None' = None):
    from .training_bot import bot_known, approach_path
    from .bot_finishing import finish_plan
    field=arena._fields[room_id];actions=Actions(arena,owner,view)
    seen = {} if objective is None else {enemy.actor_id: enemy for enemy in objective.recent_enemies}
    # At most one actor turn's movement/actions, with a guard for zero-AP gear.
    for _ in range(64):
        actor=field.actor(identity)
        if room_id not in arena._turns or not actor.health or actor.action_points<=0:break
        try:
            if objective is not None:
                from .turn_planning import choose_plan
                known = bot_known(field, owner, identity)
                seen.update((enemy, field.actor(enemy)) for enemy in known
                            if not field.allied(owner, field.actor(enemy).owner_id))
                plan = choose_plan(field, identity, known, replace(objective, recent_enemies=tuple(seen.values())))
                if plan is not None:
                    if _execute_plan(actions, room_id, identity, plan, known):
                        continue
                    break
            if heal(field,identity,actions):continue
            equip_found(field,identity,actions)
            enemies=enemies_for(field,owner,identity);known=bot_known(field,owner,identity)
            actor=field.actor(identity)
            weapon=weapon_for(field,identity)
            finishing=finish_plan(field,identity,enemies,known) if enemies else None
            if (weapon is None or weapon.template_id in (300,337)) and finishing is None and scavenge(field,identity,owner,known,actions):continue
            if weapon is None:
                primary=next((i for i in items_for(field,identity) if i.equipped and i.client_slot==16),None)
                if primary is not None:
                    actions.item(identity,primary);continue
            if enemies:
                plan=finishing or fire_plan(field,identity,enemies,known)
                if plan is not None:
                    approach,target_id,cover=plan
                    if approach:
                        if field.combat.resources[identity] == INFECTED_DOG:
                            actions.move_path(identity, approach)
                        else:
                            actions.move(identity, approach[0])
                        continue
                    target=field.actor(target_id)
                    actions.do('attack',encode_attack_request(AttackRequest(identity,target.x,target.y)))
                    # Re-evaluate against survivors and newly revealed hostiles
                    # after the shot (kills can extend the shooter's sight).
                    if room_id not in arena._turns:break
                    now=enemies_for(field,owner,identity)
                    if not now:break
                    # Actual HP/ammo/AP have changed. Continue a feasible kill
                    # instead of executing the old unconditional hit-and-run.
                    if finish_plan(field,identity,now,bot_known(field,owner,identity)) is not None:continue
                    escape=retreat_path(field,identity,now,bot_known(field,owner,identity),
                                        field.actor(identity).action_points) if cover is not None else None
                    if escape:
                        for cell in escape:
                            if room_id not in arena._turns or field.actor(identity).action_points<field.step_cost:break
                            actions.move(identity,cell)
                        break
                    if escape==():break
                    continue
                # No affordable shot: close only to weapon range and reserve
                # its AP cost, or retreat if already exposed with no budget.
                weapon=weapon_for(field,identity)
                reserve=weapon.attack_ap if weapon else 0
                if actor.action_points<=reserve:
                    escape=retreat_path(field,identity,enemies,known,actor.action_points)
                    if escape:
                        for cell in escape:actions.move(identity,cell)
                    break
                path=approach_path(field,identity,enemies,known)
                if not path:break
                actions.move(identity,path[0]);continue
            if scavenge(field,identity,owner,known,actions):continue
            waypoints=getattr(field,'patrol_waypoints',())
            if not waypoints:break
            if not hasattr(field,'patrol_progress'):field.patrol_progress={}
            index=field.patrol_progress.get(identity,0);path=()
            for _ in waypoints:
                target=waypoints[index%len(waypoints)]
                path=approach_path(field,identity,(),known,destination=target)
                if path:break
                index+=1
            field.patrol_progress[identity]=index
            if not path:break
            actions.move(identity,path[0])
        except ValueError:
            # Unknown occupancy or a changed authoritative precondition stops
            # the action; never bypass validation, refill, or grant free AP.
            break
    return tuple(actions.packets)
