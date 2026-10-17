"""Skill list layouts from silver.dll readers8c1bd8 and8c2624.

32-bit values preserve raw bits; signed/domain interpretation is separate.
8E tail is learning credits (8ad56d -> confirmation m183); 80 tail is
forgetting credits (m184). Original amounts are not in the legacy catalog.
"""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError


def encode_skill_tree(owner,entries):
    """AA reader8c2174: id,rank,learned,required actor level,two prices.

    entries are (id,rank,learned,required_level,learn_credits,forget_credits).
    """
    w=Writer().u8(0xaa).u32(owner).u16(len(entries))
    for ability,rank,learned,required,price,forget in entries:
        w.u32(ability).u8(rank).u8(int(learned)).u8(required).u32(price).u32(forget)
    return w.build()


def encode_ability_request(owner_id,ability_id,*,opcode=0x8f):
    """Native 8c2420/8c245c: actor and selected skill, no requested rank.

    8F is invoked from other_perks, 90 from my_perks. The latter's
    refund/reset policy is intentionally not inferred from its layout.
    """
    if opcode not in (0x8f,0x90):raise PacketError('Expected ability request8F/90')
    return Writer().u8(opcode).u32(owner_id).u32(ability_id).build()


def decode_ability_request(packet):
    r=Reader(packet);opcode=r.u8()
    if opcode not in (0x8f,0x90):raise PacketError('Expected ability request8F/90')
    owner,ability=r.u32(),r.u32();r.finish()
    return owner,ability,opcode


@dataclass(frozen=True)
class AbilityEntry:
    ability_id: int
    level: int
    unknown_u32: int
    active_byte: int | None = None


def encode_abilities(owner_id,entries,*,for_learning=False):
    w=Writer().u8(0x8e if for_learning else 0x80).u32(owner_id).u16(len(entries))
    for entry in entries:
        w.u32(entry.ability_id).u8(entry.level)
        if for_learning:
            if entry.active_byte is not None:raise PacketError('Learning list has no active byte')
        else:
            w.u8(entry.active_byte)
        w.u32(entry.unknown_u32)
    return w.build()


def decode_abilities(packet):
    r=Reader(packet);opcode=r.u8()
    if opcode not in (0x80,0x8e):raise PacketError('Expected skill list80/8E')
    owner=r.u32();entries=[]
    for _ in range(r.u16()):
        ability_id,level=r.u32(),r.u8()
        active=r.u8() if opcode==0x80 else None
        entries.append(AbilityEntry(ability_id,level,r.u32(),active))
    r.finish()
    return owner,tuple(entries),opcode==0x8e
