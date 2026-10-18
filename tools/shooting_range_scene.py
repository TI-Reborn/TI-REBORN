"""Original 38x38 shootingrange resource and mob10 wooden targets."""
from dataclasses import replace
import json
from pathlib import Path

from tio.arena_map import ArenaMap
from tio.battle_state import BattleActor, BattleField
from tio.protocol.battle_ground import BattleGround, GroundEntry, encode_battle_ground
from tio.protocol.battle_soldier import BattleSoldier, SCHEMAS, CONDITIONS
from tio.protocol.known_mines import encode_known_mines
from tio.protocol.item_list import encode_item_list
from tio.shooting_range import POLICY, Practice
from tio.visibility import VisibilityView
from tools.survival_scene import prepare_survival, PreparedSurvival


def prepare_range(path, account, ticket, catalog):
    layout=json.loads((Path(__file__).resolve().parents[1]/'config/shooting_range_map.json').read_text())
    w,h=layout['width'],layout['height']
    blocked=frozenset((i%w,i//w) for i,t in enumerate(layout['tiles']) if t in (2,3,4))
    transparent=frozenset((i%w,i//w) for i,t in enumerate(layout['tiles']) if t in (2,4))
    spawns=tuple(map(tuple,POLICY['player_spawns']));targets=tuple(map(tuple,POLICY['targets']))
    if len(set(spawns+targets)) != len(spawns+targets) or any(p in blocked or not(0<=p[0]<w and 0<=p[1]<h) for p in spawns+targets):
        raise ValueError('Invalid shooting range deployment')
    ground=BattleGround(0,w,h,bytes(w*h),(GroundEntry(layout['resource'].encode(),0,0),),bytes(w*h))
    layout=ArenaMap(ground,blocked,spawns,targets[:3],transparent_obstacles=transparent)
    base=prepare_survival(path,account,ticket,catalog,arena_map=layout)
    previous=base.field;combat=previous.combat;owner=ticket.character_id
    enemy=base.bot_owner
    actors=[previous.actor(i) for i in ticket.actors]
    templates={i:base.visibility.templates[i] for i in ticket.actors}
    # Retain own combat state and discard transient mirrored opponents.
    for attr in ('inventories','persistence','human','resources','enhancement_caps','weight_capacities',
                 'proficiencies','initial_proficiencies','miner_defense','rank_profiles','rental_tax_units',
                 'dog_bonuses','weapon_accuracy_bonuses','display_unarmored_bonuses'):
        values=getattr(combat,attr)
        for identity in tuple(values):
            if identity not in ticket.actors:values.pop(identity)
    target_ids=[]
    for index,(x,y) in enumerate(targets):
        identity=0x73000000+index
        if identity in ticket.actors:raise ValueError('Reserved target identity collision')
        target_ids.append(identity);hp=POLICY['target_health']
        actors.append(BattleActor(identity,enemy,x,y,0,hp,hp,sight_radius=0))
        fields={key:(b'' if reader=='CString' else 0) for key,size,reader in SCHEMAS['target']}
        fields.update({'0x8c5088':identity,'0x8c50ea':enemy,'0x8c50fb':10,'0x8c5116':b'Target',
                       '0x8c5134':1,'0x8c519b':x,'0x8c51af':y,'0x8c5187':1,'0x8c5173':1,
                       '0x8c566a':hp,'0x8c57bb':hp})
        for key,(control,expected) in CONDITIONS.items():
            if not (bool(fields[control]) if expected is None else fields[control]==expected):fields.pop(key,None)
        templates[identity]=BattleSoldier('target',fields)
        combat.register(identity,encode_item_list(identity,()),human=False)
        combat.resources[identity]=10
    field=BattleField(w,h,actors,blocked=blocked,step_cost=1,teams={owner:0,enemy:1},transparent_obstacles=transparent)
    combat.field=field;field.combat=combat;field.battle_mode=16
    for attr in ('_healing_rules','_slash_rules','_dog_rules'):
        setattr(field,attr,{k:v for k,v in getattr(previous,attr).items() if k[0] in ticket.actors})
    for identity in ticket.actors:field._turn_points[identity]=previous._turn_points[identity]
    from tio.battle_doors import BattleDoors
    from tio.battle_loot import BattleLoot
    field.doors=BattleDoors(field,(),{})
    field.loot=BattleLoot(combat,(),level=max(ticket.levels))
    field.practice=Practice(field,owner,target_ids)
    field.scene_metadata=dict(profile='shooting_range',resource='shootingrange',width=w,height=h,targets=len(targets),mode=16)
    view=VisibilityView(field,owner,templates)
    skills=tuple(p for p in base.packets if p[:1]==b'\x80')
    packets=(encode_battle_ground(ground),*view.refresh(),*skills,
             *(combat.inventory_packet(i) for i in ticket.actors),encode_known_mines(()),b'\x41')
    return PreparedSurvival(field,packets,enemy,ticket.actors,view,16,(owner,))
