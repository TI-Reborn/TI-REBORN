"""An infected dog pack on an original outdoor map, with persisted player gear."""
from dataclasses import replace
from tio.battle_state import BattleActor,BattleField
from tio.protocol.battle_soldier import BattleSoldier,SCHEMAS,CONDITIONS
from tio.protocol.item_list import encode_item_list
from tio.protocol.battle_ground import encode_battle_ground
from tio.protocol.known_mines import encode_known_mines
from tio.visibility import VisibilityView
from tools.survival_scene import prepare_survival,PreparedSurvival


def prepare_encounter(path,account,ticket,catalog,*,seed=None,policy=None,biome=None):
    from tio.world_encounters import POLICY
    policy=POLICY if policy is None else policy
    from tio.map_generation import generate_map
    from tio.arena_map import ArenaMap
    from collections import deque
    biome=biome or policy['biomes'][(seed or 0)%len(policy['biomes'])]
    if biome not in policy['biomes']:raise ValueError('Unavailable encounter biome')
    generated=generate_map('encounter_'+biome,seed=seed,deployment_size=4,mode=0)
    layout=generated.arena
    brush={'ash':7,'autumn':8,'blight':9}[biome]
    # Native7173cc matches each grid cell +8 against ground.xml IDs. The
    # leading BattleGround byte is a fog flag; it does not select the terrain.
    layout=replace(layout,ground=replace(layout.ground,first_layer=bytes((brush,))*layout.ground.width*layout.ground.height))
    if layout.containers:raise ValueError('Encounter biome must not contain equipment crates')
    # Walkable, connected cells at a fair distance from the player deployment.
    distances={p:0 for p in layout.player_spawns[:len(ticket.actors)]};pending=deque(distances)
    while pending:
        x,y=pending.popleft()
        for cell in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if cell in distances or cell in layout.blocked or not (0<=cell[0]<layout.ground.width and 0<=cell[1]<layout.ground.height):continue
            distances[cell]=distances[x,y]+1;pending.append(cell)
    count=len(ticket.actors)+1
    import random
    rng=random.Random(generated.seed ^ 0x444f4753)
    candidates=sorted(p for p,d in distances.items() if 10<=d<=16)
    rng.shuffle(candidates)
    if len(candidates)<count:raise ValueError('No fair connected encounter spawns')
    spawns=tuple(candidates[:count])
    layout=replace(layout,bot_spawns=spawns)
    base=prepare_survival(path,account,ticket,catalog,arena_map=layout)
    previous=base.field;combat=previous.combat;owner=ticket.character_id;enemy=base.bot_owner
    mirrored=set(previous._actors)-set(ticket.actors)
    for values in vars(combat).values():
        if isinstance(values,dict):
            for identity in mirrored:values.pop(identity,None)
    level=max(ticket.levels);hp=policy['health_base']+policy['health_per_level']*(level-1)
    weapon=combat.catalog.weapons[policy['weapon_id']]
    actors=[previous.actor(i) for i in ticket.actors]
    templates={i:base.visibility.templates[i] for i in ticket.actors}
    combat.npc_defense={}
    for index,(x,y) in enumerate(spawns):
        identity=0x71000000+index
        actors.append(BattleActor(identity,enemy,x,y,policy['action_points'],hp,hp,sight_radius=policy['sight'],weapons=(weapon,)))
        fields={key:(b'' if reader=='CString' else 0) for key,size,reader in SCHEMAS[False]}
        fields.update({'0x8c5088':identity,'0x8c50ea':enemy,'0x8c50fb':policy['resource_id'],
                       '0x8c5116':'Заражённая собака'.encode('cp1251'),'0x8c5134':level,
                       '0x8c519b':x,'0x8c51af':y,'0x8c5187':1,'0x8c5173':1,
                       '0x8c566a':hp,'0x8c57bb':hp,'0x8c567f':policy['sight'],
                       '0x8c571d':policy['action_points'],'0x8c5694':policy['action_points'],
                       '0x8c543f':policy['weapon_id']})
        for key,(control,expected) in CONDITIONS.items():
            if not (bool(fields[control]) if expected is None else fields[control]==expected):fields.pop(key,None)
        templates[identity]=BattleSoldier(False,fields)
        combat.register(identity,encode_item_list(identity,()),human=False)
        combat.resources[identity]=policy['resource_id'];combat.rank_profiles[identity]=(level,0)
        combat.npc_defense[identity]=0
    field=BattleField(layout.ground.width,layout.ground.height,actors,blocked=layout.blocked,step_cost=1,
                     teams={owner:0,enemy:1},transparent_obstacles=layout.transparent_obstacles)
    combat.field=field;field.combat=combat;field.battle_mode=7
    for attr in ('_healing_rules','_slash_rules','_dog_rules'):
        setattr(field,attr,{key:value for key,value in getattr(previous,attr).items() if key[0] in ticket.actors})
    for identity in ticket.actors:field._turn_points[identity]=previous._turn_points[identity]
    from tio.battle_doors import BattleDoors
    field.doors=BattleDoors(field,layout.doors,{i:previous.doors.permissions.get(i,frozenset()) for i in ticket.actors})
    from tio.battle_loot import BattleLoot
    # No random weapon crates in dog encounters. Credits/XP are the first reward.
    field.loot=BattleLoot(combat,(),level=level)
    field.scene_metadata=dict(profile='infected_dogs',biome=biome,ground_brush=brush,variant=generated.variant,seed=generated.seed,width=field.width,height=field.height,dogs=count,level=level)
    field.patrol_waypoints=generated.patrol
    field.encounter_report=dict(kind='infected_dogs',level=level,dogs=count,loot_version=1,
        credits=policy['credits_base']+policy['credits_per_level']*level+policy['credits_per_dog']*count)
    field.enemy_name='Заражённые собаки'.encode('cp1251')
    view=VisibilityView(field,owner,templates)
    skills=tuple(p for p in base.packets if p[:1]==b'\x80' and int.from_bytes(p[1:5],'little') in ticket.actors)
    packets=(encode_battle_ground(layout.ground),*view.refresh(),*skills,
             *(combat.inventory_packet(i) for i in ticket.actors),encode_known_mines(()),b'\x41')
    return PreparedSurvival(field,packets,enemy,ticket.actors,view,7,(owner,enemy))
