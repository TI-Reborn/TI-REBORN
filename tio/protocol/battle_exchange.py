"""Native mercenary exchange6E (silver98F478), distinct from ground transfer40.

First array is left-to-right, second is right-to-left (9DCF92). Empty arrays
are emitted by our client opening hook to bind confirmation to a turn/snapshot.
"""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError


@dataclass(frozen=True)
class BattleExchange:
    actor_id:int
    target_id:int
    withdrawals:tuple=()
    deposits:tuple=()


def encode_exchange(request):
    w=Writer().u8(0x6e).u32(request.actor_id).u32(request.target_id)
    for rows in (request.deposits,request.withdrawals):
        w.u32(len(rows))
        for identity,count in rows:w.u32(identity).u32(count)
    return w.build()


def decode_exchange(packet):
    r=Reader(packet)
    if r.u8()!=0x6e:raise PacketError('Expected exchange6E')
    actor,target=r.u32(),r.u32();selections=[]
    if not actor or not target or actor==target:raise PacketError('Нужны два разных бойца')
    for _ in range(2):
        count=r.u32()
        if count>1000 or count>(len(packet)-r.offset)//8:raise PacketError('Invalid exchange count')
        rows=tuple((r.u32(),r.u32()) for _ in range(count))
        if len({i for i,n in rows})!=count or any(not i or n>0x7fffffff for i,n in rows):
            raise PacketError('Invalid exchange selection')
        selections.append(rows)
    r.finish()
    if {i for i,n in selections[0]} & {i for i,n in selections[1]}:raise PacketError('Item moves both ways')
    return BattleExchange(actor,target,selections[1],selections[0])
