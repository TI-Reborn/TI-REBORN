"""Arena BA02 room records; unknown numeric fields retain native offsets.
Layout confirmed by85fa88; values and room lifecycle are not inferred.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError

@dataclass(frozen=True)
class ArenaRoom:
    unknown_u32_00: int
    discarded_u32_02: int
    category: int
    unknown_u8_1e: int
    discarded_u32_03: int
    unknown_u8_1d: int
    unknown_u8_1c: int
    name: bytes
    unknown_u32_04: int
    unknown_u8_1a: int
    unknown_u8_1b: int
    unknown_u8_18: int
    unknown_u8_20: int


def encode_room_list(rooms=()):
    rooms=tuple(rooms)
    if len(rooms)>32767:raise PacketError('Arena count exceeds signed16 range')
    w=Writer().u8(0xba).u8(2).u16(len(rooms))
    for r in rooms:
        if not isinstance(r.name,bytes) or b'\0' in r.name:raise PacketError('Expected NUL-free name bytes')
        w.u32(r.unknown_u32_00).u32(r.discarded_u32_02).u8(r.category).u8(r.unknown_u8_1e)
        w.u32(r.discarded_u32_03).u8(r.unknown_u8_1d).u8(r.unknown_u8_1c)
        w.data.extend(r.name+b'\0')
        w.u32(r.unknown_u32_04).u8(r.unknown_u8_1a).u8(r.unknown_u8_1b).u8(r.unknown_u8_18).u8(r.unknown_u8_20)
    if len(w.data)>65533:raise PacketError('Arena list exceeds transport frame')
    return w.build()


def decode_room_list(packet):
    r=Reader(packet)
    if r.read(2)!=b'\xba\x02':raise PacketError('Expected Arena listBA02')
    count=r.u16()
    if count>32767:raise PacketError('Negative Arena count')
    rooms=[]
    for _ in range(count):
        prefix=(r.u32(),r.u32(),r.u8(),r.u8(),r.u32(),r.u8(),r.u8())
        name=bytearray()
        while (value:=r.u8())!=0:name.append(value)
        rooms.append(ArenaRoom(*prefix,bytes(name),r.u32(),r.u8(),r.u8(),r.u8(),r.u8()))
    r.finish()
    return tuple(rooms)

@dataclass(frozen=True)
class ArenaMemberPet:
    unknown_u8_01: int
    unknown_flag_01: int
    unknown_flag_02: int
    unknown_u32s: tuple[int, ...] # seven values in wire order, third decremented by client
    name: bytes

@dataclass(frozen=True)
class ArenaMember:
    character_id: int
    name: bytes
    unknown_u32_114: int
    unknown_u8_109: int
    unknown_flag_110: int
    pets: tuple[ArenaMemberPet, ...] = ()


def _name_write(w, name):
    if not isinstance(name,bytes) or b'\0' in name or len(name)>255:
        raise PacketError('Expected NUL-free name bytes, at most255')
    w.data.extend(name+b'\0')


def _name_read(r):
    name=bytearray()
    while (value:=r.u8())!=0:
        name.append(value)
        if len(name)>255:raise PacketError('Name too long')
    return bytes(name)


def encode_member_list(room_id, unknown_u8, members):
    members=tuple(members)
    if len(members)>8:raise PacketError('Client has eight member slots')
    w=Writer().u8(0xba).u8(11).u32(room_id).u8(unknown_u8).u16(len(members))
    for m in members:
        if len(m.pets)>3:raise PacketError('Client has three pet slots per member')
        w.u32(m.character_id);_name_write(w,m.name)
        w.u32(m.unknown_u32_114).u8(m.unknown_u8_109).u8(m.unknown_flag_110).u16(len(m.pets))
        for p in m.pets:
            if len(p.unknown_u32s)!=7:raise PacketError('Expected seven pet integers')
            w.u8(p.unknown_u8_01).u8(p.unknown_flag_01).u8(p.unknown_flag_02)
            for value in p.unknown_u32s[:5]:w.u32(value)
            _name_write(w,p.name)
            for value in p.unknown_u32s[5:]:w.u32(value)
    return w.build()


def decode_member_list(packet):
    r=Reader(packet)
    if r.read(2)!=b'\xba\x0b':raise PacketError('Expected Arena membersBA0B')
    room_id,unknown,count=r.u32(),r.u8(),r.u16()
    if count>8:raise PacketError('Client has eight member slots')
    members=[]
    for _ in range(count):
        char_id,name=r.u32(),_name_read(r)
        value,byte,flag,n=r.u32(),r.u8(),r.u8(),r.u16()
        if n>3:raise PacketError('Client has three pet slots per member')
        pets=[]
        for _ in range(n):
            a,b,c=r.u8(),r.u8(),r.u8()
            values=tuple(r.u32() for _ in range(5));pet_name=_name_read(r)
            values+=tuple(r.u32() for _ in range(2))
            pets.append(ArenaMemberPet(a,b,c,values,pet_name))
        members.append(ArenaMember(char_id,name,value,byte,flag,tuple(pets)))
    r.finish()
    return room_id,unknown,tuple(members)

@dataclass(frozen=True)
class ArenaRemoveRequest:
    character_id: int
    kick: bool


def encode_remove_request(request):
    if type(request.kick) is not bool:raise PacketError('Expected boolean kick flag')
    return Writer().u8(0xba).u8(5).u32(request.character_id).u8(int(request.kick)).build()


def decode_remove_request(packet):
    r=Reader(packet)
    if r.read(2)!=b'\xba\x05':raise PacketError('Expected Arena removalBA05')
    character_id,flag=r.u32(),r.u8()
    if flag not in (0,1):raise PacketError('Unrecovered Arena removal mode')
    r.finish()
    return ArenaRemoveRequest(character_id,bool(flag))

@dataclass(frozen=True)
class ArenaCreateRequest:
    mode: int
    map_size: int
    players_count: int
    unknown_u8_01: int
    unknown_u32_01: int
    soldiers_count_01: int
    soldiers_count_02: int
    level_range_index: int
    unknown_u32_02: int

    @property
    def stake(self):
        """Numeric edit labelled m617 in the original create form."""
        return self.unknown_u32_02


def encode_create_request(request):
    r=request
    return (Writer().u8(0xc8).u8(0x2b).u32(r.mode).u8(r.map_size).u8(r.players_count)
            .u8(r.unknown_u8_01).u32(r.unknown_u32_01).u8(r.soldiers_count_01)
            .u8(r.soldiers_count_02).u8(r.level_range_index).u32(r.unknown_u32_02).build())


def decode_create_request(packet):
    r=Reader(packet)
    if r.read(2)!=b'\xc8\x2b':raise PacketError('Expected create battleC8/2B')
    request=ArenaCreateRequest(r.u32(),r.u8(),r.u8(),r.u8(),r.u32(),r.u8(),r.u8(),r.u8(),r.u32())
    r.finish()
    return request


def decode_room_ready(packet):
    r=Reader(packet)
    if r.u8()!=0x2c: raise PacketError('Expected main-room ready2C')
    value=r.u8()
    if value not in (0,1): raise PacketError('Invalid ready state')
    r.finish()
    return bool(value)


def validate_room_leave(packet):
    if packet != b'\x2a\x01':
        raise PacketError('Expected main-room leave2A01; alternate mode unrecovered')


def decode_room_start(packet, *, mode):
    """Owner Start a08ab0; mode16 alone carries the UI selection byte."""
    r = Reader(packet)
    if r.u8() != 0x2e:
        raise PacketError('Expected main-room start2E')
    selection = r.u8() if mode == 16 else None
    if selection is not None and selection not in (0, 1, 2):
        raise PacketError('Unknown mode16 start selection')
    r.finish()
    return selection

@dataclass(frozen=True)
class BattleSettings:
    unknown_u32_40: int
    unknown_u8_01: int
    mode: int
    unknown_u16_14: int
    unknown_u8_1f: int
    owner_name: bytes
    unknown_bytes: bytes # offsets1d,1e,1c,20,28
    unknown_u32_2c: int
    unknown_flag_30: int
    mode16_extra: tuple[bytes, int, int] | None = None

    # Original window_battleroom_info tags and russian.lng; see ARENA.md.
    @property
    def map_size(self): return self.unknown_bytes[3]

    @property
    def players_count(self): return self.unknown_u8_01

    @property
    def soldiers_count(self): return self.unknown_bytes[2]

    @property
    def turn_seconds(self): return self.unknown_u16_14

    @property
    def exit_zone(self): return self.unknown_bytes[4]

    @property
    def stake(self): return self.unknown_u32_2c


def encode_battle_settings_body(s):
    if not isinstance(s.unknown_bytes,bytes) or len(s.unknown_bytes)!=5:
        raise PacketError('Expected five BattleSettings bytes')
    if (s.mode==16)!=(s.mode16_extra is not None):raise PacketError('Mode16 extension mismatch')
    w=Writer().u32(s.unknown_u32_40).u8(s.unknown_u8_01).u8(s.mode).u16(s.unknown_u16_14).u8(s.unknown_u8_1f)
    _name_write(w,s.owner_name);w.data.extend(s.unknown_bytes)
    w.u32(s.unknown_u32_2c).u8(s.unknown_flag_30)
    if s.mode16_extra is not None:
        flags,first,second=s.mode16_extra
        if not isinstance(flags,bytes) or len(flags)!=4:raise PacketError('Expected four mode16 flags')
        w.data.extend(flags);w.u16(first).u16(second)
    return w.build()


def decode_battle_settings_body(body):
    r=Reader(body)
    first,byte,mode,word,last=r.u32(),r.u8(),r.u8(),r.u16(),r.u8()
    owner=_name_read(r);values=r.read(5);number=r.u32();flag=r.u8()
    extra=(r.read(4),r.u16(),r.u16()) if mode==16 else None
    r.finish()
    return BattleSettings(first,byte,mode,word,last,owner,values,number,flag,extra)
