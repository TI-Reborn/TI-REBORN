"""SILVER87c7b4 builder07 /87d400 result08; eight bytes remain opaque."""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError

@dataclass(frozen=True)
class ServerLoginRequest:
    server_id: int
    unknown_bytes_01: bytes

def encode_server_login_request(p):
    if not isinstance(p.unknown_bytes_01,bytes) or len(p.unknown_bytes_01)!=8:
        raise PacketError('Expected exactly8 opaque bytes')
    return Writer().u8(7).u8(p.server_id).build()+p.unknown_bytes_01

def decode_server_login_request(data):
    r=Reader(data)
    if r.u8()!=7: raise PacketError('Expected server-login07')
    p=ServerLoginRequest(r.u8(),r.read(8));r.finish();return p

def encode_server_login_result(status):
    return Writer().u8(8).u8(status).build()

def decode_server_login_result(data):
    r=Reader(data)
    if r.u8()!=8: raise PacketError('Expected server-login08')
    status=r.u8();r.finish();return status
