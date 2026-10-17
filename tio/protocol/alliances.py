"""Alliance AF family confirmed against original Silver 6e107c..6e1cbc.

Encoded names are CP1251 bytes supplied by the caller. Prices, rights,
membership, expiry, and crest storage are server policy, outside this module.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError

OPERATIONS = (1, 2, 4, 8, 9, 10, 11, 12, 14)


def _cstring(w, value, maximum=255):
    if not isinstance(value, bytes) or b'\0' in value or len(value) > maximum:
        raise PacketError('Expected bounded non-NUL encoded bytes')
    w.data.extend(value + b'\0')


def _read_string(r, maximum):
    end = r.data.find(b'\0', r.offset)
    if end < 0 or end-r.offset > maximum:
        raise PacketError('Unterminated or overlong string')
    value = r.read(end-r.offset)
    r.read(1)
    return value


def decode_request(data: bytes):
    r = Reader(data)
    if r.u8() != 0xaf:
        raise PacketError('Expected alliance request AF')
    operation = r.u8()
    if operation not in OPERATIONS:
        raise PacketError('Unsupported alliance operation')
    value = None
    if operation in (1, 2):
        value = _read_string(r, 64 if operation == 1 else 255)
        if not value:
            raise PacketError('Empty alliance or clan name')
    elif operation == 4:
        value = r.u8()
        if value not in (0, 1):
            raise PacketError('Unknown invitation decision')
    elif operation in (9, 11):
        value = r.u32()
    r.finish()
    return operation, value


def encode_invitation(inviter: bytes, alliance: bytes) -> bytes:
    w = Writer().u8(0xaf).u8(3)
    _cstring(w, inviter)
    _cstring(w, alliance)
    return w.build()


@dataclass(frozen=True)
class AllianceMember:
    name: bytes
    online: int
    level: int
    unknown_u32: int = 0


@dataclass(frozen=True)
class AllianceClan:
    id: int
    name: bytes
    level: int
    influence: int
    leader: bytes
    members: tuple[AllianceMember, ...] = ()
    crest_id: int = 0
    flags: int = 0


@dataclass(frozen=True)
class AllianceInfo:
    id: int
    name: bytes
    level: int
    leading_clan: int
    influence: int
    state: int
    clans: tuple[AllianceClan, ...] = ()
    crest_id: int = 0
    clan_count: int | None = None


def encode_info(p: AllianceInfo) -> bytes:
    if p.state not in (0, 1):
        raise PacketError('Expected alliance state boolean')
    # Original first field is matched to the member-clan ID in6e15f4/168f.
    # A storage alliance ID is independent; native identity is its leading clan.
    w = Writer().u8(0xaf).u8(13).u32(p.leading_clan)
    _cstring(w, p.name)
    w.u8(p.level).u32(p.crest_id).u32(p.influence).u8(p.state).u16(len(p.clans))
    for clan in p.clans:
        w.u32(clan.id)
        _cstring(w, clan.name)
        w.u8(clan.level).u32(clan.crest_id).u16(len(clan.members)).u32(clan.influence)
        _cstring(w, clan.leader)
        w.u8(clan.flags)
        for member in clan.members:
            _cstring(w, member.name)
            w.u8(member.online).u8(member.level).u32(member.unknown_u32)
    return w.build()


def encode_ratings(rows) -> bytes:
    rows = tuple(rows)
    w = Writer().u8(0xaf).u8(15).u32(len(rows))
    for row in rows:
        w.u32(row.leading_clan)
        _cstring(w, row.name)
        count = len(row.clans) if row.clan_count is None else row.clan_count
        w.u8(row.level).u32(row.crest_id).u32(row.influence).u8(count)
        leading_name = next((c.name for c in row.clans if c.id == row.leading_clan), b'')
        _cstring(w, leading_name)
    return w.build()
