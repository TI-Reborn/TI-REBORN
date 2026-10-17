"""Full wire25 structure; semantic aliases recovered from original RTTI."""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError
from .arena import _name_read,_name_write

@dataclass(frozen=True)
class MemberGroup1:
    unknown_u8_01:int
    unknown_u32_01:int
    unknown_u8_02:int
    unknown_u32s:tuple[int,...] # five; first stored as byte by client

    @classmethod
    def soldier(cls, *, level, equip_status, injure_status, npc_id, avatar_id, rank, military_rank, points_to_next_rank):
        return cls(level, equip_status, injure_status, (npc_id, avatar_id, rank, military_rank, points_to_next_rank))

    level = property(lambda s: s.unknown_u8_01)
    equip_status = property(lambda s: s.unknown_u32_01)
    injure_status = property(lambda s: s.unknown_u8_02)
    npc_id = property(lambda s: s.unknown_u32s[0])
    avatar_id = property(lambda s: s.unknown_u32s[1])
    rank = property(lambda s: s.unknown_u32s[2])
    military_rank = property(lambda s: s.unknown_u32s[3])
    points_to_next_rank = property(lambda s: s.unknown_u32s[4])

@dataclass(frozen=True)
class MemberGroup2:
    name:bytes
    unknown_u8:int
    unknown_u16_01:int
    unknown_u16_02:int
    unknown_u32s:tuple[int,...] # six; first two stored as bytes by client
    children:tuple[int,...]=()

    soldier_name = property(lambda s: s.name)
    level = property(lambda s: s.unknown_u8)
    max_hp = property(lambda s: s.unknown_u16_01)
    p_defence = property(lambda s: s.unknown_u16_02)
    equip_status = property(lambda s: s.unknown_u32s[0])
    npc_id = property(lambda s: s.unknown_u32s[1])
    avatar_id = property(lambda s: s.unknown_u32s[2])
    rank = property(lambda s: s.unknown_u32s[3])
    military_rank = property(lambda s: s.unknown_u32s[4])
    points_to_next_rank = property(lambda s: s.unknown_u32s[5])
    weapon_item_ids = property(lambda s: s.children)

@dataclass(frozen=True)
class BattleMemberRecord:
    character_id:int
    name:bytes
    unknown_u32:int
    unknown_bytes:bytes # six bytes in wire order
    group1:tuple[MemberGroup1,...]=()
    group2:tuple[MemberGroup2,...]=()

    crest_id = property(lambda s: s.unknown_u32)
    average_level = property(lambda s: s.unknown_bytes[0])
    level = property(lambda s: s.unknown_bytes[1])
    color = property(lambda s: s.unknown_bytes[2])
    team = property(lambda s: s.unknown_bytes[3])
    ready = property(lambda s: s.unknown_bytes[4])
    online = property(lambda s: s.unknown_bytes[5])


def _count(r,minimum):
    count=r.u32()
    if count>(len(r.data)-r.offset)//minimum:raise PacketError('Impossible list count')
    return count


def encode_battle_members(unknown_u8,unknown_flag,members):
    members=tuple(members);w=Writer().u8(0x25).u8(unknown_u8).u8(unknown_flag).u32(len(members))
    for m in members:
        if not isinstance(m.unknown_bytes,bytes) or len(m.unknown_bytes)!=6:raise PacketError('Expected six member bytes')
        w.u32(m.character_id);_name_write(w,m.name);w.u32(m.unknown_u32);w.data.extend(m.unknown_bytes)
        w.u32(len(m.group1))
        for g in m.group1:
            if len(g.unknown_u32s)!=5:raise PacketError('Expected five group1 integers')
            w.u8(g.unknown_u8_01).u32(g.unknown_u32_01).u8(g.unknown_u8_02)
            for v in g.unknown_u32s:w.u32(v)
        w.u32(len(m.group2))
        for g in m.group2:
            if len(g.unknown_u32s)!=6:raise PacketError('Expected six group2 integers')
            _name_write(w,g.name);w.u8(g.unknown_u8).u16(g.unknown_u16_01).u16(g.unknown_u16_02)
            for v in g.unknown_u32s:w.u32(v)
            w.u32(len(g.children))
            for v in g.children:w.u16(v)
    if len(w.data)>65533:raise PacketError('Member list exceeds transport frame')
    return w.build()


def decode_battle_members(packet):
    if len(packet)>65533:raise PacketError('Member list exceeds transport frame')
    r=Reader(packet)
    if r.u8()!=0x25:raise PacketError('Expected BattleMemberList25')
    unknown,flag=r.u8(),r.u8();members=[]
    for _ in range(_count(r,23)):
        char,name=r.u32(),_name_read(r);number=r.u32();raw=r.read(6)
        first=[]
        for _ in range(_count(r,26)):
            a,b,c=r.u8(),r.u32(),r.u8();first.append(MemberGroup1(a,b,c,tuple(r.u32() for _ in range(5))))
        second=[]
        for _ in range(_count(r,34)):
            name2=_name_read(r);a,b,c=r.u8(),r.u16(),r.u16();values=tuple(r.u32() for _ in range(6))
            children=tuple(r.u16() for _ in range(_count(r,2)))
            second.append(MemberGroup2(name2,a,b,c,values,children))
        members.append(BattleMemberRecord(char,name,number,raw,tuple(first),tuple(second)))
    r.finish()
    return unknown,flag,tuple(members)
