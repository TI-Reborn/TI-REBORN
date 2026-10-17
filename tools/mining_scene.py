"""Prepare native mode7 and original resource100 sick miners; no mirrored gear."""
from dataclasses import replace
from tio.mining import MiningBattle,band
from tio.mine_map import generate
from tio.battle_state import BattleActor,BattleField
from tio.protocol.battle_soldier import BattleSoldier,SCHEMAS,CONDITIONS
from tio.protocol.item_list import ItemRecord,encode_item_list
from tio.protocol.battle_ground import encode_battle_ground
from tio.protocol.abilities import encode_abilities
from tio.protocol.known_mines import encode_known_mines
from tio.weapons import WeaponStats
from tio.visibility import VisibilityView
from tools.survival_scene import prepare_survival,PreparedSurvival


def prepare_mining(path,account,ticket,catalog,*,role=1,seed=None,shared=False):
    if type(role) is not int or role not in (1,2,3):raise ValueError('Choose Miner, Raider or Defender')
    minimum,maximum,total,hp,armor,low,high=band(ticket.levels)
    layout=generate(seed,role=role,shared=shared)
    base=prepare_survival(path,account,replace(ticket,mode=0),catalog,arena_map=layout.arena)
    previous=base.field;combat=previous.combat;owner=ticket.character_id;enemy=base.bot_owner
    actors=[];templates={}
    for identity in ticket.actors:
        a=previous.actor(identity);resource=combat.resources[identity]
        # Original underground sight:5 human,6 dog/miner. Helmet bonus remains.
        from tio.battle_item_effects import rules as item_rules
        sight=(6 if resource in (3,4,5,6) else 5)+item_rules()['policy']['dark_sight_penalty']
        from tio.protocol.item_list import decode_item_list
        from tio.battle_loot import BattleLoot
        metadata=previous.loot.metadata
        from tio.equipment_bonuses import bonuses
        sight+=bonuses(combat.inventories[identity],resource)['sight']
        actors.append(replace(a,sight_radius=sight));templates[identity]=base.visibility.templates[identity]
    # Discard all provisional mirrored opponents from the reusable own-squad preparation.
    for attr in ('inventories','persistence','human','resources','enhan'+'cement_caps','weight_capacities','proficiencies','miner_defense','rank_profiles','rental_tax_units','dog_bonuses','weapon_accuracy_bonuses','display_unarmored_bonuses'):
        values=getattr(combat,attr)
        for identity in tuple(values):
            if identity not in ticket.actors:values.pop(identity)
    from tio.crystal_market import POLICY
    mob_ap=POLICY['mob_ap']
    weapon=WeaponStats(353,'Sick Miner Attack','Melee',low,high-low,POLICY['mob_attack_ap'],None,None,1,1,1)
    combat.catalog.weapons[353]=weapon
    combat.catalog.sources[353]={'weaponAttack':'None','weaponType':'Melee','accuracy':'100'}
    combat.npc_defense={}
    for index,(x,y) in enumerate(layout.arena.bot_spawns):
        identity=0x71000000+index
        actors.append(BattleActor(identity,enemy,x,y,mob_ap,hp,hp,sight_radius=6+item_rules()['policy']['dark_sight_penalty'],weapons=(weapon,)))
        fields={key:(b'' if reader=='CString' else 0) for key,size,reader in SCHEMAS[True]}
        fields.update({'0x8c5088':identity,'0x8c50ea':enemy,'0x8c50fb':100,'0x8c5116':b'Sick Miner',
                       '0x8c5134':maximum,'0x8c519b':x,'0x8c51af':y,'0x8c5187':1,'0x8c5173':1,
                       '0x8c566a':hp,'0x8c57bb':hp,'0x8c567f':6,'0x8c571d':mob_ap,'0x8c5694':mob_ap,'0x8c52cf':353,
                       '0x8c5731':armor})
        for key,(control,expected) in CONDITIONS.items():
            if not (bool(fields[control]) if expected is None else fields[control]==expected):fields.pop(key,None)
        templates[identity]=BattleSoldier(True,fields)
        item=ItemRecord(0x72000000+index,353,bytes(2),1,1,16,(1,1,1),bytes(4),None,bytes(3))
        combat.register(identity,encode_item_list(identity,(item,)),human=True)
        combat.resources[identity]=100;combat.npc_defense[identity]=armor
        combat.rank_profiles[identity]=(maximum,0)
    field=BattleField(60,60,actors,blocked=layout.arena.blocked,step_cost=1,teams={owner:0,enemy:1},transparent_obstacles=layout.arena.transparent_obstacles)
    combat.field=field;field.combat=combat;field.battle_mode=7
    for attr in ('_healing_rules','_slash_rules','_dog_rules'):
        setattr(field,attr,{key:v for key,v in getattr(previous,attr).items() if key[0] in ticket.actors})
    for identity in ticket.actors:field._turn_points[identity]=previous._turn_points[identity]
    from tio.battle_doors import BattleDoors
    field.doors=BattleDoors(field,(),{})
    field.loot=BattleLoot(combat,layout.arena.containers,level=maximum)
    field.mining=MiningBattle(field,layout,total,role,owner)
    field.item_darkness=True
    from tio.battle_item_effects import initialize,refresh_sight
    initialize(field.combat);refresh_sight(field.combat)
    from tio.mining_ai import configure_patrols
    from tio.crystal_market import POLICY
    configure_patrols(field,field.actor_ids(enemy),radius=POLICY['mutant_patrol_radius'])
    field.scene_metadata=dict(profile='mine',resource=layout.resource,width=60,height=60,role=role,level_band=[minimum,maximum],deposits=layout.deposits,mobs=10)
    view=VisibilityView(field,owner,templates)
    # Do not send provisional mirrored actor/skill records from base preparation.
    skills=tuple(p for p in base.packets if p[:1]==b'\x80')
    packets=(encode_battle_ground(layout.arena.ground),*view.refresh(),*skills,
             *(combat.inventory_packet(i) for i in ticket.actors),encode_known_mines(()),b'\x41')
    return PreparedSurvival(field,packets,enemy,ticket.actors,view,7,(owner,enemy))


def append_mining_owner(field,path,account,ticket,catalog,*,role,templates):
    """Append one saved squad to the existing mine, returning its private view.

    The shared hub authorizes membership and journals this entire admission.
    It copies the newly added templates into existing viewers before fanout.
    Preparing source stats creates no account or roster writes.
    """
    from tio.mine_map import spawn_positions
    from tio.protocol.abilities import decode_abilities
    from tio.protocol.item_list import decode_item_list
    mine=field.mining;owner=ticket.character_id
    if not mine.shared:raise ValueError('Shared mine required')
    if type(role) is not int or role not in (1,2,3):raise ValueError('Invalid mining role')
    if owner in mine.exited or field.actor_ids(owner):raise ValueError('Already admitted to this mine')
    if any(saved_account==account for _,saved_account in field.combat.persistence.values()):
        raise ValueError('Account already admitted to this mine')
    if tuple(band(ticket.levels))!=tuple(band((field.scene_metadata['level_band'][0],))):
        raise ValueError('Squad does not match this mine level range')
    occupied={(a.x,a.y) for a in field._actors.values() if a.health!=0}
    mutants={(a.x,a.y) for a in field._actors.values()
             if a.health!=0 and field.combat.resources.get(a.actor_id)==100}
    spawns=spawn_positions(mine.layout,role,len(ticket.actors),occupied=occupied,mutants=mutants)
    source=prepare_survival(path,account,replace(ticket,mode=0),catalog,arena_map=mine.layout.arena)
    identity=mine.next_actor_id
    identities=tuple(range(identity,identity+len(ticket.actors)))
    if not identities or identities[-1]>=0x71000000 or any(i in field.combat.actor_owners for i in identities):
        raise ValueError('Mine actor identities exhausted')
    side=1 if role==2 else 0;color=len(mine.roles)
    plans=[]
    for local,global_id,position in zip(ticket.actors,identities,spawns):
        actor=source.field.actor(local);old=source.field.combat;resource=old.resources[local]
        from tio.equipment_bonuses import bonuses
        from tio.battle_item_effects import rules as item_rules
        sight=(6 if resource in (3,4,5,6) else 5)+item_rules()['policy']['dark_sight_penalty']+bonuses(old.inventories[local],resource)['sight']
        actor=replace(actor,actor_id=global_id,owner_id=owner,x=position[0],y=position[1],sight_radius=sight)
        _,items,flag=decode_item_list(old.inventories[local])
        inventory=encode_item_list(global_id,items,flag)
        template=source.visibility.templates[local]
        template=replace(template,fields={**template.fields,'0x8c5088':global_id,
            '0x8c50ea':owner,'0x8c519b':actor.x,'0x8c51af':actor.y,
            '0x8c5187':side,'0x8c5173':color})
        skill=next((p for p in source.packets if p[:1]==b'\x80' and int.from_bytes(p[1:5],'little')==local),None)
        skill=None if skill is None else encode_abilities(global_id,decode_abilities(skill)[1])
        plans.append((local,actor,inventory,template,skill))
    mine.register_owner(owner,role)
    for local,actor,inventory,template,skill in plans:
        identity=actor.actor_id;old=source.field.combat
        field._actors[identity]=actor
        field._turn_points[identity]=source.field._turn_points[local]
        field._ability_turns[identity]=0
        field.combat.register(identity,inventory,human=old.human[local],path=path,
                              account=account,pet_packet=old.proficiencies[local])
        field.combat.storage_ids[identity]=local
        for name in ('miner_defense','dog_bonuses','weapon_accuracy_bonuses','human_critical_bonuses',
                     'weight_capacities','display_unarmored_bonuses','learned','skill_lists'):
            if local in getattr(old,name):getattr(field.combat,name)[identity]=getattr(old,name)[local]
        for name in ('_healing_rules','_slash_rules','_dog_rules'):
            for (actor_id,ability),value in getattr(source.field,name).items():
                if actor_id==local:getattr(field,name)[identity,ability]=value
        field.doors.permissions[identity]=source.field.doors.permissions.get(local,frozenset())
        templates[identity]=template
    mine.next_actor_id=identities[-1]+1
    field.scene_metadata['roles']=dict(mine.roles)
    if getattr(field,'item_darkness',False):
        from tio.battle_item_effects import refresh_sight
        refresh_sight(field.combat)
    view=VisibilityView(field,owner,templates)
    packets=(encode_battle_ground(mine.layout.arena.ground),*view.refresh(),
             *(skill for _,_,_,_,skill in plans if skill is not None),
             *(field.combat.inventory_packet(i) for i in identities),encode_known_mines(()),b'\x41')
    return view,packets


def prepare_shared_mining(path,entries,catalog,*,seed=None):
    """Entries are (account, ticket, role); return the first owner's scene.

    The hub retains field/views/ground, rather than the PreparedSurvival value.
    All real squads are remapped; only the ten original mutants are copied
    from provisional preparation. Each account keeps its own saved pet IDs.
    """
    from tio.combat import Combat
    from tio.battle_doors import BattleDoors
    from tio.battle_loot import BattleLoot
    from tio.mining_ai import configure_patrols
    from tio.crystal_market import POLICY
    entries=tuple(entries)
    if not entries:raise ValueError('Mine requires an admitted squad')
    owners=tuple(ticket.character_id for _,ticket,_ in entries)
    if len(set(owners))!=len(owners) or len({account for account,_,_ in entries})!=len(entries):
        raise ValueError('Duplicate mine account or owner')
    ranges={tuple(band(ticket.levels)) for _,ticket,_ in entries}
    if len(ranges)!=1:raise ValueError('All squads must use one mine level range')
    account,ticket,role=entries[0]
    base=prepare_mining(path,account,ticket,catalog,role=role,seed=seed,shared=True)
    old=base.field;enemy=base.bot_owner;layout=old.mining.layout
    if enemy in owners:raise ValueError('Reserved mine NPC owner')
    npc_ids=old.actor_ids(enemy)
    if len(npc_ids)!=10:raise ValueError('Mine requires exactly ten mutants')
    from tio.battle_item_effects import initialize,refresh_sight
    # Provisional actors already include darkness. Seed the fresh combat with
    # retained base sight so its item effects apply that penalty only once.
    npc_sight=initialize(old.combat)['base_sight']
    field=BattleField(old.width,old.height,
        tuple(replace(old.actor(i),sight_radius=npc_sight[i]) for i in npc_ids),
        blocked=old.blocked,step_cost=old.step_cost,teams={enemy:2},
        transparent_obstacles=old.transparent_obstacles)
    field.battle_mode=7;field.combat=Combat(field,old.combat.catalog)
    field.mine_mutant_sight_version=1
    field.combat.npc_defense={};templates={}
    for identity in npc_ids:
        field.combat.register(identity,old.combat.inventories[identity],human=True)
        field.combat.resources[identity]=100
        field.combat.npc_defense[identity]=old.combat.npc_defense[identity]
        field.combat.rank_profiles[identity]=old.combat.rank_profiles[identity]
        template=base.visibility.templates[identity]
        templates[identity]=replace(template,fields={**template.fields,'0x8c5187':2})
    field.doors=BattleDoors(field,(),{})
    field.loot=BattleLoot(field.combat,layout.arena.containers,level=max(ticket.levels))
    field.scene_metadata={**old.scene_metadata,'shared':True,'roles':{},'mobs':10}
    field.mining=MiningBattle(field,layout,old.mining.total,role,ticket.character_id,shared=True)
    configure_patrols(field,npc_ids,radius=POLICY['mutant_patrol_radius'])
    first_skills=()
    for account,member,member_role in entries:
        _,packets=append_mining_owner(field,path,account,member,catalog,role=member_role,templates=templates)
        if member is ticket:first_skills=tuple(p for p in packets if p[:1]==b'\x80')
    field.mining.sent_deposits={}
    field.item_darkness=True
    initialize(field.combat);refresh_sight(field.combat)
    view=VisibilityView(field,ticket.character_id,templates)
    ids=field.actor_ids(ticket.character_id)
    packets=(encode_battle_ground(layout.arena.ground),*view.refresh(),*first_skills,
             *(field.combat.inventory_packet(i) for i in ids),encode_known_mines(()),b'\x41')
    return PreparedSurvival(field,packets,enemy,ids,view,7,(*owners,enemy))
