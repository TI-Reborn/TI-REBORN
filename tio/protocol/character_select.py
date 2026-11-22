"""Only the proven empty branch of SILVER889eac CharSelectInfo10."""
from .binary import PacketError

RETURN_TO_CHARACTER_SELECT = b'\xc8\xfa'

def encode_empty_character_list():
    return b'\x10\0\0'

def decode_empty_character_list(data):
    if bytes(data)!=b'\x10\0\0':
        raise PacketError('Only exact empty CharSelectInfo10 is implemented')


from dataclasses import dataclass
from .binary import Reader,Writer

@dataclass(frozen=True)
class CharacterRecord:
    record_id: int
    name_bytes: bytes
    resource_type: int
    unknown_u32_01: int
    unknown_u8_01: int
    select_hint: int
    optional_flag: int
    optional_six: bytes
    words: tuple[int,...]
    unknown_u8_02: int
    unknown_u32_02: int
    boolean_byte: int


def encode_character_list(records):
    w=Writer().u8(16).u16(len(records))
    for r in records:
        w.u8(r.record_id)
        if not isinstance(r.name_bytes,bytes) or len(r.name_bytes)>255 or b'\0' in r.name_bytes:raise PacketError('Invalid name CString')
        w.data.extend(r.name_bytes+b'\0')
        w.u8(r.resource_type).u32(r.unknown_u32_01).u8(r.unknown_u8_01).u8(r.select_hint).u8(r.optional_flag)
        if not isinstance(r.optional_six,bytes) or len(r.optional_six)!=(6 if r.optional_flag else 0):raise PacketError('Invalid conditional six-byte block')
        w.data.extend(r.optional_six)
        if len(r.words)!=19:raise PacketError('Expected19 u16 fields')
        for v in r.words:w.u16(v)
        w.u8(r.unknown_u8_02).u32(r.unknown_u32_02).u8(r.boolean_byte)
    if len(w.data)>65533:raise PacketError('Character list exceeds frame policy')
    return w.build()


def decode_character_list(data):
    r=Reader(data)
    if r.u8()!=16:raise PacketError('Expected CharSelectInfo10')
    records=[]
    for _ in range(r.u16()):
        ident=r.u8();name=bytearray()
        while True:
            c=r.u8()
            if c==0:break
            name.append(c)
            if len(name)>255:raise PacketError('Name exceeds255 bytes')
        resource=r.u8();v=r.u32();a=r.u8();hint=r.u8();flag=r.u8()
        optional=r.read(6) if flag else b''
        records.append(CharacterRecord(ident,bytes(name),resource,v,a,hint,flag,optional,tuple(r.u16() for _ in range(19)),r.u8(),r.u32(),r.u8()))
    r.finish();return tuple(records)
