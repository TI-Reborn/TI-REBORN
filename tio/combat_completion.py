"""Manual HP capacity injection on the existing authoritative native33 route.

HP/cooldown state is plain snapshot-supported data inside item_effects. Neither
city PetInfo nor base stats are persisted by this temporary combat effect.
"""
from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path

from .protocol.binary import PacketError, Writer
from .protocol.health import encode_health


@lru_cache(maxsize=1)
def rules():
    value=json.loads((Path(__file__).resolve().parents[1]/'config/combat_completion.json').read_text(encoding='utf-8'))
    expected={'template':5012,'bonus_percent':10,'ap':8,'turns':10,'cooldown':15,'weight':1,'gold':100}
    if value.get('version')!=1 or any(type(value['health'].get(k)) is not int or value['health'][k]!=v for k,v in expected.items()):
        raise ValueError('Unsupported manual HP injection policy')
    return value


def initialize(combat):
    from .battle_item_effects import initialize as base_initialize
    state=base_initialize(combat)
    state.setdefault('health_capacity',{});state.setdefault('health_cooldown',{})
    return state


def encode_max_health(actor_id,maximum):
    """Original4E attribute5 ->8c785f stores native actor+6008 word."""
    if type(maximum) is not int or not 1<=maximum<=65535:
        raise PacketError('Maximum health must fit native word')
    return Writer().u8(0x4e).u32(actor_id).u32(1).u32(5).u32(maximum).u8(0).build()


def handles(template):return template==rules()['health']['template']


def use(combat,owner,action):
    # Called by battle_item_effects._use within its existing atomic SQL unit.
    from .battle_item_effects import _actor,_selected,_consume,_pay
    if action.option!=255:raise ValueError('HP injection requires unspecified native33 target')
    actor=_actor(combat,owner,action.pet_id)
    selected,items,flag=_selected(combat,actor,action.instance_id)
    row=rules()['health']
    if selected.template_id!=row['template'] or selected.equipped or selected.unknown_words[0]<=0:
        raise ValueError('Owned unused HP injection required')
    state=initialize(combat);identity=actor.actor_id;generation=combat.field._ability_turns[identity]
    if generation<state['health_cooldown'].get(identity,0):raise ValueError('HP injection is cooling down')
    if identity in state['health_capacity']:raise ValueError('HP injection is already active')
    maximum=actor.max_health*(100+row['bonus_percent'])//100
    if maximum>65535 or maximum<=actor.max_health:raise ValueError('HP injection exceeds native capacity')
    # Prepare every scalar packet before the CAS/inventory mutation.
    capacity=encode_max_health(identity,maximum)
    replies=_pay(combat,actor,row['ap'],_consume(identity,selected,items,flag))
    current=combat.field.actor(identity)
    combat.field._actors[identity]=replace(current,max_health=maximum)
    state['health_capacity'][identity]={'base':actor.max_health,'maximum':maximum,'expiry':generation+row['turns']-1}
    state['health_cooldown'][identity]=generation+row['cooldown']
    return (capacity,*replies)


def end_turn(combat,owner,actor_ids):
    """Use inside existing item-effect end transaction, including timeout."""
    state=initialize(combat);replies=[]
    for identity in sorted(set(actor_ids)):
        actor=combat.field._actors.get(identity)
        if actor is None or actor.owner_id!=owner:raise ValueError('Owned turn actors required')
        saved=state['health_capacity'].get(identity)
        if saved is None:continue
        if actor.max_health!=saved['maximum']:
            raise ValueError('Authoritative maximum HP changed while injection was active')
        if actor.health and combat.field._ability_turns[identity]<saved['expiry']:continue
        current=min(actor.health,saved['base'])
        packets=(encode_max_health(identity,saved['base']),)
        if current!=actor.health:packets+=(encode_health(identity,current),)
        combat.field._actors[identity]=replace(actor,max_health=saved['base'],health=current)
        del state['health_capacity'][identity]
        replies.extend(packets)
    return tuple(replies)


def settlement_health(combat, identity):
    """Freeze wounds against the permanent capacity without persisting the buff."""
    actor=combat.field.actor(identity)
    saved=getattr(combat,'item_effects',{}).get('health_capacity',{}).get(identity)
    return actor.health if saved is None else min(actor.health,saved['base'])
