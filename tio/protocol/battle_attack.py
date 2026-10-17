"""49 native95dfe8 request;4B native6543fc/653d24 response.

Native9602d4 uses the top-level result for ordinary attacks and each hit's
result for skills. Result2 selects ch01 (*Miss*); result4 is critical damage.
"""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError

RESULT_NORMAL=0
RESULT_MISS=2
RESULT_CRITICAL=4


@dataclass(frozen=True)
class AttackRequest:
    actor_id:int
    x:int
    y:int


def encode_attack_request(r):
    return Writer().u8(0x49).u32(r.actor_id).u8(r.x).u8(r.y).build()


def decode_attack_request(packet):
    r=Reader(packet)
    if r.u8()!=0x49:raise PacketError('Expected attack49')
    result=AttackRequest(r.u32(),r.u8(),r.u8());r.finish();return result


@dataclass(frozen=True)
class AttackHit:
    actor_id:int
    damage:int
    left_hp:int
    flags:int=0
    additional_damage:int=0
    absorbed_damage:int=0
    auto_health:int=0


@dataclass(frozen=True)
class AttackResult:
    actor_id:int
    origin:tuple
    target:tuple
    weapon_id:int
    hits:tuple=()
    skill_id:int=0
    flags:int=0
    impact:tuple|None=None
    mine_state:int|None=None


def encode_attack_result(result):
    w=Writer().u8(0x4b).u32(result.actor_id)
    for x,y in (result.origin,result.target):w.u32(x).u32(y)
    w.u16(result.weapon_id).u32(result.skill_id)
    x,y=result.impact or result.target
    w.u32(x).u32(y).u32(result.flags).u32(len(result.hits))
    for h in result.hits:
        w.u32(h.actor_id).u32(h.flags).u16(h.damage).u16(h.left_hp)
        w.u16(h.additional_damage).u16(h.absorbed_damage).u16(h.auto_health)
    if result.mine_state is not None and not 0<=result.mine_state<=255:raise PacketError('Mine result exceeds native byte')
    w.u8(int(result.mine_state is not None))
    if result.mine_state is not None:w.u32(result.mine_state)
    return w.build()


def decode_attack_result(packet):
    """Decode native attack results for per-observer hit filtering."""
    r=Reader(packet)
    if r.u8()!=0x4b:raise PacketError('Expected attack result4B')
    actor=r.u32();origin=(r.u32(),r.u32());target=(r.u32(),r.u32())
    weapon=r.u16();skill=r.u32();impact=(r.u32(),r.u32());flags=r.u32()
    hits=[]
    for _ in range(r.u32()):
        identity,hit_flags=r.u32(),r.u32()
        hits.append(AttackHit(identity,r.u16(),r.u16(),hit_flags,r.u16(),r.u16(),r.u16()))
    optional=r.u8()
    if optional not in (0,1):raise PacketError('Invalid mine presence flag')
    mine=r.u32() if optional else None
    if mine is not None and mine>255:raise PacketError('Mine result exceeds native byte')
    r.finish()
    return AttackResult(actor,origin,target,weapon,tuple(hits),skill,flags,impact,mine)
