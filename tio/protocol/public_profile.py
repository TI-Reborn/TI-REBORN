"""68 request (96d568), A7/00 reader (96d7d0), original silver.dll.

League indices are reversed: lg03=bronze, lg00=platinum.
The two 605dc4 calls read u64s; the UI displays the low dword/word.
"""
import struct
from .binary import Reader,Writer,PacketError


def decode_request(packet):
    r=Reader(packet)
    if r.u8()!=0x68:raise PacketError('Expected profile request')
    kind=r.u8();name=bytearray()
    while (c:=r.u8())!=0:
        name.append(c)
        if len(name)>16:raise PacketError('Invalid character name')
    r.finish()
    if kind!=0 or not name or not bytes(name).isalnum():
        raise PacketError('Only character profiles are supported')
    return bytes(name)


def encode_profile(identity,name,level,biography,*,online=True,in_battle=False,
                   rating=0,wins=0,losses=0,kills=0,deaths=0,damage_dealt=0,damage_received=0,
                   online_hours=0,squad_rank=0,squad_icon=0,mercenaries=(),
                   skill=0,league=3,place=0,streak=0,contact='',website='',clan_name=b'',clan_crest_id=0,
                   alliance_name=b'',alliance_crest_id=0):
    if not name or len(name)>16 or not name.isalnum():raise PacketError('Invalid name')
    w=Writer().u8(0xa7).u8(0).u32(identity)
    w.data.extend(name+b'\0');w.u8(level).u32(0)
    # Original96d958/96d965 call68a094(id,0/1). These are crest IDs,
    # not persistent clan/alliance entity identifiers.
    if not isinstance(clan_name,bytes) or len(clan_name)>32 or b'\0' in clan_name:raise PacketError('Invalid clan name')
    if not isinstance(alliance_name,bytes) or len(alliance_name)>32 or b'\0' in alliance_name:raise PacketError('Invalid alliance name')
    w.data.extend(clan_name+b'\0');w.u32(clan_crest_id);w.data.extend(alliance_name+b'\0');w.u32(alliance_crest_id)
    w.u8(int(in_battle)).u8(0)
    for v in (0,online_hours,rating,wins,losses,kills,deaths,damage_dealt,damage_received,squad_icon,squad_rank):
        if type(v) is not int or not -(1<<31)<=v<(1<<32):raise PacketError('Invalid profile statistic')
        w.u32(v&0xffffffff)
    # About me / contact / website; only the public summary is populated.
    for text in (biography,contact,website):
        if '\0' in text:raise PacketError('Invalid profile text')
        w.data.extend(text.encode('utf-16-le')+b'\0\0')
    mercenaries=tuple(mercenaries)
    if len(mercenaries)>20:raise PacketError('Too many profile soldiers')
    w.u8(len(mercenaries))
    for nick,lvl,xp,rank in mercenaries:
        if not nick or b'\0' in nick or len(nick)>64:raise PacketError('Invalid soldier name')
        w.data.extend(nick+b'\0');w.u8(lvl).u32(0).u32(xp).u32(0).u32(rank).u32(0).u32(0)
    w.u8(0).u32(0).u32(0).u32(0).u8(0).u8(int(online))
    if league not in (0,1,2,3):raise PacketError('Invalid league')
    w.u32(skill).u32(league)
    w.data.extend(struct.pack('<QQ',place,streak));w.u8(0)
    return w.build()
