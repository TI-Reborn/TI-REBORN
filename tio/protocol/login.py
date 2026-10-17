"""CONFIRMED LSAuthResult consumer: silver.dll preferred VA 0x87ce60.

This codec includes the application opcode, NOT an ORANGE transport header.
Nonzero status meanings remain unknown; no success token is invented by default.
"""
from dataclasses import dataclass
from enum import IntEnum
from .binary import PacketError, Reader, Writer, uint


@dataclass(frozen=True)
class LSAuthResult:
    status: int
    unknown_u32_01: int | None = None

    def __post_init__(self):
        uint(self.status, 8)
        if self.status == 0:
            uint(self.unknown_u32_01, 32)
        elif self.unknown_u32_01 is not None:
            raise PacketError('Nonzero status has no proven u32 field')


def encode_ls_auth_result(packet: LSAuthResult) -> bytes:
    w = Writer().u8(0x02).u8(packet.status)
    if packet.status == 0:
        w.u32(packet.unknown_u32_01)
    return w.build()


def decode_ls_auth_result(data: bytes) -> LSAuthResult:
    r = Reader(data)
    if r.u8() != 0x02:
        raise PacketError('Expected application opcode 0x02')
    status = r.u8()
    packet = LSAuthResult(status, r.u32() if status == 0 else None)
    r.finish()
    return packet


def transform_auth_value(value: int) -> int:
    """Exact uint32 arithmetic of 0x87c5e4; token semantics are LIKELY only."""
    uint(value, 32)
    return (((value ^ 4) * 8 * 0xe8) & 0xffffffff) ^ 0x375830

@dataclass(frozen=True)
class BasicLoginRequest:
    """Only opcode03 branch without optional mode suffix; raw encoded strings."""
    login_bytes:bytes
    password_bytes:bytes
    transformed_auth_u32:int

def encode_basic_login_request(p):
    fields=[]
    for value in (p.login_bytes,p.password_bytes):
        value=bytes(value)
        if len(value)>255 or b'\0' in value: raise PacketError('Invalid login CString')
        fields.append(value+b'\0')
    return b'\x03'+b''.join(fields)+Writer().u32(p.transformed_auth_u32).build()

def decode_basic_login_request(data):
    r=Reader(data)
    if r.u8()!=3: raise PacketError('Expected basic application login03')
    fields=[]
    for _ in range(2):
        field=bytearray()
        while True:
            value=r.u8()
            if value==0: break
            field.append(value)
            if len(field)>255: raise PacketError('Login CString exceeds native shortstring bound')
        fields.append(bytes(field))
    result=BasicLoginRequest(*fields,r.u32());r.finish();return result

def encode_login_success():
    """Status0 branch confirmed at silver 0x87d072; no error layout implied."""
    return b'\x04\x00'

def decode_login_success(data):
    if bytes(data)!=b'\x04\x00': raise PacketError('Expected login04 success status0')


class LoginFailureStatus(IntEnum):
    """Original 0x6d46e8 text table, consumed by LSLoginResult 0x87d00c."""
    INVALID_CREDENTIALS = 3  # Wrong username or password
    ACCESS_FAILED = 4
    ACCOUNT_IN_USE = 7
    OVERLOADED = 15
    MAINTENANCE = 16


def encode_login_failure(status):
    """The proven ordinary error branch reads one status byte, no payload.

    Only named, native-confirmed statuses are accepted. In particular 0x12
    has a separate string/callback branch and must never use this encoder.
    """
    if isinstance(status, LoginFailureStatus): status = int(status)
    uint(status, 8)
    try: status = LoginFailureStatus(status)
    except ValueError as exc: raise PacketError('Unconfirmed ordinary login failure status') from exc
    return bytes((0x04, status))
