"""Original ti.exe crest59/5A and allianceAF06/AF07; native proof in evidence.

The native stack buffer is1024 bytes. This codec narrows it to the authoritative
canonical16x16 24bit BMP policy (max824, actual822), before any client receives it.
IDs share the global crest blob sequence across clans and future alliances.
"""
from dataclasses import dataclass
import struct
from .binary import Reader,Writer,PacketError,uint
from ..clan_benefits import validate_crest
from ..clans import ClanRejected

CLAN=0
ALLIANCE=1
MAX_BYTES=824


def decode_upload(data):
    """Original Silver6e68e8: 58, u16 size, canonical BMP; zero removes."""
    r=Reader(data)
    if r.u8()!=0x58:raise PacketError('Expected clan crest upload')
    size=r.u16()
    if size>MAX_BYTES:raise PacketError('Crest bitmap exceeds bounded native policy')
    raw=r.read(size);r.finish()
    if size:_bmp(raw)
    return raw if size else None


def encode_upload(bmp):
    if bmp is not None:_bmp(bmp)
    raw=bmp or b'';w=Writer().u8(0x58).u16(len(raw));w.data.extend(raw)
    return w.build()


def _kind(value):
    if type(value) is not int or value not in (CLAN,ALLIANCE):raise PacketError('Unknown crest kind')
    return value


def _identity(value):
    uint(value,32)
    if not value:raise PacketError('Crest ID must be positive')
    return value


def _bmp(value):
    if not isinstance(value,bytes) or len(value)>MAX_BYTES:raise PacketError('Invalid bounded crest bitmap')
    try:
        validate_crest(value)
        if struct.unpack_from('<i',value,22)[0]!=16:raise ClanRejected('Native crest requires bottom-up BMP')
    except ClanRejected:raise PacketError('Invalid canonical crest bitmap') from None
    return value


@dataclass(frozen=True)
class CrestRequest:
    kind:int
    crest_id:int


@dataclass(frozen=True)
class CrestContent:
    kind:int
    crest_id:int
    bmp:bytes


def _prefix(w,kind,*,reply=False):
    if _kind(kind)==CLAN:return w.u8(0x5a if reply else 0x59)
    return w.u8(0xaf).u8(7 if reply else 6)


def _read_prefix(r,*,reply=False):
    first=r.u8()
    if first==(0x5a if reply else 0x59):return CLAN
    if first==0xaf and r.u8()==(7 if reply else 6):return ALLIANCE
    raise PacketError('Unexpected crest opcode')


def encode_request(crest_id,kind=CLAN):
    return _prefix(Writer(),kind).u32(_identity(crest_id)).build()


def decode_request(packet):
    r=Reader(packet);kind=_read_prefix(r);identity=_identity(r.u32());r.finish()
    return CrestRequest(kind,identity)


def encode_content(crest_id,bmp,kind=CLAN):
    _identity(crest_id);_bmp(bmp)
    w=_prefix(Writer(),kind,reply=True).u32(crest_id).u16(len(bmp));w.data.extend(bmp)
    return w.build()


def decode_content(packet):
    r=Reader(packet);kind=_read_prefix(r,reply=True);identity=_identity(r.u32());size=r.u16()
    if size>MAX_BYTES:raise PacketError('Crest bitmap exceeds bounded native policy')
    bmp=_bmp(r.read(size));r.finish()
    return CrestContent(kind,identity,bmp)
