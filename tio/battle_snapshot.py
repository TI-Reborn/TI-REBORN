"""Versioned JSON graph of server state with a fixed class allowlist.

No pickle, imports from payloads, sockets, session credentials or executable
callbacks. Object references preserve field/combat/view cycles. Runtime clocks
and locks are rebound explicitly. Containers preserve tuple keys and fractions.
"""
from collections import deque
from dataclasses import fields,is_dataclass
from fractions import Fraction
from functools import lru_cache
from importlib import import_module
import hashlib
import json
import math
from pathlib import Path
import random
import threading
import time
from types import MappingProxyType
from .performance import timed

VERSION=1
MAX_BYTES=8*1024*1024
MODULES=('arena_service','arena_rooms','battle_state','combat','weapons','armor',
    'weapon_proficiency','enhancement','level_progression','achievements','battle_doors',
    'battle_loot','visibility','mining','shooting_range','arena_map','mine_map',
    'protocol.battle_ground','protocol.battle_members','protocol.arena',
    'protocol.battle_soldier','protocol.item_list','protocol.abilities','reward_policy','control_points','assault_battle','battle_hazards')
OBJECTS={'ArenaService','ArenaRooms','BattleField','Combat','WeaponCatalog','ArmorCatalog',
    'ProficiencyRules','EnhancementRules','BattleExperience','BattleAchievements','BattleDoors',
    'BattleLoot','VisibilityView','MiningBattle','Practice'}
OMIT={'_clock','_lock','_durable','_durable_arena','clock'}


@lru_cache(maxsize=1)
def registry():
    result={}
    for name in MODULES:
        module=import_module('tio.'+name)
        for value in vars(module).values():
            if (isinstance(value,type) and value.__module__==module.__name__
                    and (is_dataclass(value) or value.__name__ in OBJECTS)):
                result[value.__module__+'.'+value.__name__]=value
    return result


@lru_cache(maxsize=1)
def rules_digest():
    root=Path(__file__).resolve().parents[1];h=hashlib.sha256()
    for p in sorted((root/'config').glob('*.json')):
        # Optional contracts are frozen in their mission/checkpoint. Adding
        # their catalogue must not invalidate pre-existing ordinary battles.
        if p.name in ('pve_contracts.json', 'contracts_map_profiles.json'):
            continue
        h.update(p.name.encode());h.update(p.read_bytes())
    h.update((root/'evidence/items_diagnostic.xml').read_bytes())
    return h.hexdigest()


@timed('checkpoint.encode')
def dumps(value,*,clock=time.monotonic,wall=time.time):
    nodes=[];seen={};allowed=registry()
    def encode(v):
        kind=type(v)
        if v is None or kind in (bool,int,str):return v
        if kind is float:
            if not math.isfinite(v):raise ValueError('Nonfinite battle state')
            return v
        # Most graph entries are plain containers. Avoid ABC instance checks
        # for each of their elements; retain the original path for subclasses.
        if kind is bytes:return {'b':v.hex()}
        if kind is dict:return {'d':[[encode(k),encode(x)] for k,x in v.items()]}
        if kind is tuple:return {'t':[encode(x) for x in v]}
        if kind is list:return {'l':[encode(x) for x in v]}
        if kind in (set,frozenset):return {'s' if kind is set else 'z':[encode(x) for x in sorted(v,key=repr)]}
        if kind is deque:return {'q':[encode(x) for x in v]}
        if isinstance(v,bytes):return {'b':v.hex()}
        if isinstance(v,Path):return {'p':str(v)}
        if isinstance(v,Fraction):return {'f':[v.numerator,v.denominator]}
        if isinstance(v,MappingProxyType):return {'m':[[encode(k),encode(x)] for k,x in v.items()]}
        if isinstance(v,dict):return {'d':[[encode(k),encode(x)] for k,x in v.items()]}
        if isinstance(v,tuple):return {'t':[encode(x) for x in v]}
        if isinstance(v,list):return {'l':[encode(x) for x in v]}
        if isinstance(v,(set,frozenset)):return {'s' if isinstance(v,set) else 'z':[encode(x) for x in sorted(v,key=repr)]}
        if isinstance(v,deque):return {'q':[encode(x) for x in v]}
        name=type(v).__module__+'.'+type(v).__name__
        if type(v) is random.Random:name='random.Random'
        elif name not in allowed:raise ValueError('Unsupported battle state type: '+name)
        if id(v) in seen:return {'r':seen[id(v)]}
        index=len(nodes);seen[id(v)]=index;nodes.append(None)
        attributes={'state':v.getstate()} if name=='random.Random' else {
            k:x for k,x in vars(v).items() if k not in OMIT}
        nodes[index]={'class':name,'attributes':encode(attributes)}
        return {'r':index}
    data=dict(version=VERSION,rules=rules_digest(),mono=clock(),wall=wall(),root=encode(value),nodes=nodes)
    text=json.dumps(data,separators=(',',':'),allow_nan=False)
    if len(text.encode())>MAX_BYTES:raise ValueError('Battle snapshot exceeds limit')
    return text


def loads(text,*,clock=time.monotonic,wall=time.time,rebase=True):
    if len(text.encode())>MAX_BYTES:raise ValueError('Battle snapshot exceeds limit')
    data=json.loads(text)
    if data['version']!=VERSION or data['rules']!=rules_digest():raise ValueError('Incompatible battle snapshot')
    nodes=data['nodes'];allowed=registry()
    if len(nodes)>10000:raise ValueError('Too many snapshot objects')
    objects=[]
    for node in nodes:
        name=node['class']
        if name=='random.Random':value=random.Random()
        elif name in allowed:value=allowed[name].__new__(allowed[name])
        else:raise ValueError('Unknown snapshot class')
        objects.append(value)
    def decode(v):
        if v is None or type(v) in (bool,int,str):return v
        if type(v) is float:
            if not math.isfinite(v):raise ValueError('Nonfinite snapshot value')
            return v
        if not isinstance(v,dict) or len(v)!=1:raise ValueError('Malformed snapshot value')
        tag,x=next(iter(v.items()))
        if tag=='r':
            if type(x) is not int or not 0<=x<len(objects):raise ValueError('Invalid snapshot reference')
            return objects[x]
        if tag=='b':return bytes.fromhex(x)
        if tag=='p':return Path(x)
        if tag=='f':return Fraction(*x)
        if tag in ('d','m'):
            pairs=[(decode(k),decode(a)) for k,a in x];result=dict(pairs)
            if len(pairs)!=len(result):raise ValueError('Duplicate snapshot key')
            return MappingProxyType(result) if tag=='m' else result
        factories={'t':tuple,'l':list,'s':set,'z':frozenset,'q':deque}
        if tag in factories:return factories[tag](decode(a) for a in x)
        raise ValueError('Unknown snapshot value type')
    for node,value in zip(nodes,objects):
        attributes=decode(node['attributes'])
        if node['class']=='random.Random':value.setstate(attributes['state']);continue
        if any(not isinstance(k,str) or k.startswith('__') or k in OMIT for k in attributes):raise ValueError('Invalid snapshot attribute')
        if is_dataclass(value) and set(attributes)!={f.name for f in fields(value)}:raise ValueError('Invalid snapshot record')
        for k,x in attributes.items():object.__setattr__(value,k,x)
    # Deadlines retain their real absolute expiry across a process restart.
    elapsed=max(0,wall()-data['wall'])
    shift=clock()-data['mono']-elapsed if rebase else 0
    for value in objects:
        name=type(value).__name__
        if name=='ArenaRooms':value._lock=threading.RLock()
        elif name=='ArenaService':
            value._clock=clock
            if rebase:value._turns={i:(o,ids,end+shift) for i,(o,ids,end) in value._turns.items()}
        elif name=='Practice':value.clock=wall
        elif name=='BattleField':
            if not 1<=value.width<=255 or not 1<=value.height<=255:raise ValueError('Invalid restored battlefield')
            if any(i!=a.actor_id or not value.inside(a.x,a.y) for i,a in value._actors.items()):raise ValueError('Invalid restored actors')
        elif name=='Combat':
            from .battle_hazards import initialize
            initialize(value)
    root=decode(data['root'])
    return root,dict(shift=shift,elapsed=elapsed,wall=data['wall'])
