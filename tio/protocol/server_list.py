"""SILVER 0x87d1cc list06 and 0x87c76c request05. Field semantics stay conservative."""
from dataclasses import dataclass
from .binary import PacketError, Reader, Writer

@dataclass(frozen=True)
class ServerEntry:
    unknown_u8_01: int
    address_octets: bytes
    unknown_u16_01: int
    unknown_u16_02: int
    unknown_u16_03: int
    unknown_u8_02: int

@dataclass(frozen=True)
class ServerList:
    unknown_u8_01: int
    entries: tuple[ServerEntry, ...]
    trailing_bytes: bytes = b''

@dataclass(frozen=True)
class ServerListRequest:
    unknown_u8_01: int
    unknown_u32_01: int
    trailing_bytes: bytes


def _cstring(value):
    if not isinstance(value, bytes) or len(value)>255 or b'\0' in value:
        raise PacketError('Expected raw CString of at most255 bytes without NUL')
    return value+b'\0'


def _read_cstring(r):
    result=bytearray()
    while True:
        v=r.u8()
        if v==0: return bytes(result)
        result.append(v)
        if len(result)>255: raise PacketError('CString exceeds server policy bound255')


def encode_server_list(p: ServerList) -> bytes:
    w=Writer().u8(6).u8(len(p.entries)).u8(p.unknown_u8_01)
    for e in p.entries:
        w.u8(e.unknown_u8_01)
        if not isinstance(e.address_octets,bytes) or len(e.address_octets)!=4:
            raise PacketError('Expected four address octets')
        for v in e.address_octets: w.u8(v)
        w.u16(e.unknown_u16_01).u16(e.unknown_u16_02).u16(e.unknown_u16_03).u8(e.unknown_u8_02)
    return w.build()+_cstring(p.trailing_bytes)


def decode_server_list(data: bytes) -> ServerList:
    r=Reader(data)
    if r.u8()!=6: raise PacketError('Expected server-list06')
    count=r.u8(); flag=r.u8()
    # Native lower bound is too weak (10 per record); require all12 plus NUL.
    if len(r.data)-r.offset<count*12+1: raise PacketError('Truncated server list')
    entries=tuple(ServerEntry(r.u8(),r.read(4),r.u16(),r.u16(),r.u16(),r.u8()) for _ in range(count))
    result=ServerList(flag,entries,_read_cstring(r));r.finish();return result


def encode_server_list_request(p: ServerListRequest) -> bytes:
    return Writer().u8(5).u8(p.unknown_u8_01).u32(p.unknown_u32_01).build()+_cstring(p.trailing_bytes)


def decode_server_list_request(data: bytes) -> ServerListRequest:
    r=Reader(data)
    if r.u8()!=5: raise PacketError('Expected server-list request05')
    p=ServerListRequest(r.u8(),r.u32(),_read_cstring(r));r.finish();return p
