"""Original SILVER889cdc request and88a79c result. Success semantics unknown."""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError

@dataclass(frozen=True)
class CharacterCreateRequest:
    name_bytes: bytes
    unknown_u16: int
    options: tuple[int,int,int,int]

def encode_character_create(p):
    if not isinstance(p.name_bytes,bytes) or b'\0' in p.name_bytes or len(p.name_bytes)>255:
        raise PacketError('Expected raw CString up to255 bytes')
    if len(p.options)!=4:raise PacketError('Expected four option bytes')
    w=Writer().u8(17);w.data.extend(p.name_bytes+b'\0');w.u16(p.unknown_u16)
    for v in p.options:w.u8(v)
    return w.build()

def decode_character_create(data):
    r=Reader(data)
    if r.u8()!=17:raise PacketError('Expected character create11')
    name=bytearray()
    while (v:=r.u8())!=0:
        name.append(v)
        if len(name)>255:raise PacketError('Name exceeds255 bytes')
    result=CharacterCreateRequest(bytes(name),r.u16(),tuple(r.u8() for _ in range(4)))
    r.finish();return result

def encode_character_create_result(status):return Writer().u8(18).u8(status).build()

def decode_character_create_result(data):
    r=Reader(data)
    if r.u8()!=18:raise PacketError('Expected character create result12')
    status=r.u8();r.finish();return status
