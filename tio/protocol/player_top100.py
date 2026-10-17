"""Original player standings: A4 builder77f74c, A5 reader77f788.

The native combo swaps indices0/5 before writing the selector. No account IDs,
wallets or owner routing keys occur in the payload. RTTI TPlayerRaiting names
the 64-byte native record; one wire dword is read and discarded.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError

SORTS={0:'rating',1:'wins',2:'damage',3:'kills',4:'experience',5:'rank',
       6:'bronze',7:'silver',8:'gold'}


def decode_request(packet):
    r=Reader(packet)
    if r.u8()!=0xa4:raise PacketError('Expected player standings request A4')
    selector=r.u8();r.finish()
    if selector not in SORTS:raise PacketError('Unsupported player standings selector')
    return selector


def encode_request(selector):
    packet=Writer().u8(0xa4).u8(selector).build();decode_request(packet);return packet


@dataclass(frozen=True)
class PlayerRating:
    name: bytes
    clan_name: bytes=b''
    clan_crest_id: int=0
    unknown_discarded_u32: int=0
    alliance_crest_id: int=0
    level: int=0
    damage_dealt: int=0
    damage_received: int=0
    wins: int=0
    losses: int=0
    rating: int=0
    military_rank: int=0
    rank_points: int=0
    experience: int=0
    kills: int=0
    deaths: int=0
    trueskill: int=0


def _name(w,value,maximum,*,empty=True):
    if not isinstance(value,bytes) or b'\0' in value or len(value)>maximum or (not empty and not value):
        raise PacketError('Invalid public encoded name')
    w.data.extend(value+b'\0')


def _i32(w,value):
    if type(value) is not int or not -(1<<31)<=value<(1<<31):raise PacketError('Expected signed32 standings value')
    return w.u32(value&0xffffffff)


def encode_ratings(selector,rows):
    encode_request(selector);rows=tuple(rows)
    if len(rows)>100:raise PacketError('Player standings are limited to100 rows')
    w=Writer().u8(0xa5).u8(selector).u16(len(rows))
    for row in rows:
        if isinstance(row,dict):row=PlayerRating(**row)
        _name(w,row.name,16,empty=False);_name(w,row.clan_name,32)
        w.u32(row.clan_crest_id).u32(row.unknown_discarded_u32).u32(row.alliance_crest_id).u8(row.level)
        for value in (row.damage_dealt,row.damage_received,row.wins,row.losses):w.u32(value)
        for value in (row.rating,row.military_rank,row.rank_points):_i32(w,value)
        for value in (row.experience,row.kills,row.deaths):w.u32(value)
        _i32(w,row.trueskill)
    return w.build()


def decode_ratings(packet):
    """Checked mirror for tests; signed fields retain native signed semantics."""
    r=Reader(packet)
    if r.u8()!=0xa5:raise PacketError('Expected player standings response A5')
    selector=r.u8();encode_request(selector);count=r.u16()
    if count>100:raise PacketError('Too many player standings rows')
    def name(maximum):
        value=bytearray()
        while (c:=r.u8())!=0:
            value.append(c)
            if len(value)>maximum:raise PacketError('Invalid standings name')
        return bytes(value)
    def signed():
        n=r.u32();return n if n<1<<31 else n-(1<<32)
    rows=[]
    for _ in range(count):
        nick,clan=name(16),name(32)
        if not nick:raise PacketError('Empty player name')
        rows.append(PlayerRating(nick,clan,r.u32(),r.u32(),r.u32(),r.u8(),
            r.u32(),r.u32(),r.u32(),r.u32(),signed(),signed(),signed(),
            r.u32(),r.u32(),r.u32(),signed()))
    r.finish();return selector,tuple(rows)


def encode_world_rows(selector,rows):
    """Whitelist real public fields; native u32 counters saturate, never wrap."""
    def u32(value):
        if type(value) is not int:raise PacketError('Invalid public counter')
        return min(0xffffffff,max(0,value))
    def i32(value):
        if type(value) is not int:raise PacketError('Invalid public signed counter')
        return min(0x7fffffff,max(-(1<<31),value))
    records=[]
    for row in rows:
        records.append(PlayerRating(name=row['name'],clan_name=row.get('clan_name',b''),
            clan_crest_id=u32(row.get('clan_crest_id',0)),alliance_crest_id=u32(row.get('alliance_crest_id',0)),
            level=min(255,u32(row['level'])),damage_dealt=u32(row['damage']),
            damage_received=u32(row.get('damage_received',0)),wins=u32(row['wins']),losses=u32(row.get('losses',0)),
            rating=i32(row['rating']),military_rank=i32(row.get('military_rank',0)),rank_points=i32(row['rank']),
            experience=u32(row['experience']),kills=u32(row.get('kills',0)),deaths=u32(row.get('deaths',0)),
            trueskill=i32(row.get('skill',0))))
    return encode_ratings(selector,records)
