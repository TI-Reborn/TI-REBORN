"""Recovered ordinary4C summary and per-soldier XP, silver95e4d0.

Result byte:0 defeat,1 victory,2 draw (native audio labels95eaf0/95eb08).
Summary slots: kills,losses,damage dealt,damage received,credits,rental tax.
Confirmed by window718263..718490 and russian.lng st04..st10/st15.
Wallet balance travels in the separate asset packet.
"""
from .binary import Writer,PacketError
from dataclasses import dataclass
import math
import struct


@dataclass(frozen=True)
class SoldierExperience:
    actor_id:int
    gain:int
    previous_skills:tuple # Seven IEEE754 bit patterns, native result order.
    profile:tuple # Eight pairs of saved/base IEEE754 bit patterns.


def encode_battle_over(result,*,kills=0,losses=0,damage_dealt=0,damage_received=0,credits=0,rental_tax=0,soldiers=()):
    if result not in (0,1,2):raise PacketError('Invalid battle outcome')
    w=Writer().u8(0x4c).u8(0).u8(0).u8(result)
    if not 0<=kills<=65535 or not 0<=losses<=65535:raise PacketError('Battle counts exceed native words')
    for value in (kills,losses,damage_dealt,damage_received,credits,rental_tax):w.u32(value)
    if len(soldiers)>31 or len({s.actor_id for s in soldiers})!=len(soldiers):raise PacketError('Invalid experience recipients')
    w.u8(len(soldiers))
    for s in soldiers:
        if not 0<=s.gain<=0x7fffffff or len(s.previous_skills)!=7 or len(s.profile)!=16:raise PacketError('Invalid experience record')
        w.u32(s.actor_id).u32(s.gain).u32(0).u16(0).u16(0)
        for value in (*s.previous_skills,*s.profile):
            w.u32(value)
            number=struct.unpack('<f',struct.pack('<I',value))[0]
            if not math.isfinite(number) or not 0<=number<=200:raise PacketError('Invalid result skill')
        w.u8(0)
    return w.build()
