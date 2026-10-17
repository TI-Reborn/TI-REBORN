"""Application0C two raw CStrings; application0D status. SILVER87d608/87d8a4."""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError

@dataclass(frozen=True)
class Auth2Request:
    unknown_string_01: bytes
    server_list_trailing_bytes: bytes


def encode_auth2_request(p):
    fields=[]
    for value in (p.unknown_string_01,p.server_list_trailing_bytes):
        if not isinstance(value,bytes) or len(value)>255 or b'\0' in value:
            raise PacketError('Expected raw CString up to255 bytes without NUL')
        fields.append(value+b'\0')
    return b'\x0c'+b''.join(fields)


def decode_auth2_request(data):
    r=Reader(data)
    if r.u8()!=12: raise PacketError('Expected application0C')
    fields=[]
    for _ in range(2):
        field=bytearray()
        while True:
            value=r.u8()
            if not value:break
            field.append(value)
            if len(field)>255:raise PacketError('CString exceeds255 bytes')
        fields.append(bytes(field))
    r.finish();return Auth2Request(*fields)


def encode_auth2_result(status):
    return Writer().u8(13).u8(status).build()


def decode_auth2_result(data):
    r=Reader(data)
    if r.u8()!=13:raise PacketError('Expected application0D')
    status=r.u8();r.finish();return status
