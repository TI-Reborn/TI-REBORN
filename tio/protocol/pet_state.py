"""Original8c3c94 emits67 actor:u32 and action:u32 (from byte DL).

Action semantics are intentionally not inferred from the actor's current
5ff1 state. UI callbacks use action0; other callers require investigation.
"""
from .binary import Reader,Writer,PacketError,uint


def encode_squad_slot(actor_id,slot):
    if slot not in (1,2,3):raise PacketError('Regular squad slot must be1..3')
    return Writer().u8(0xbf).u8(3).u32(actor_id).u8(slot).build()


def decode_squad_slot(packet):
    r=Reader(packet)
    if r.read(2)!=b'\xbf\x03':raise PacketError('Expected squad assignmentBF03')
    actor,slot=r.u32(),r.u8();r.finish()
    if slot not in (1,2,3):raise PacketError('Regular squad slot must be1..3')
    return actor,slot


def encode_pet_state_request(actor_id,action):
    uint(action,8)
    return Writer().u8(0x67).u32(actor_id).u32(action).build()


def decode_pet_state_request(packet):
    r=Reader(packet)
    if r.u8()!=0x67:raise PacketError('Expected pet state request67')
    actor,action=r.u32(),r.u32();r.finish();uint(action,8)
    return actor,action
