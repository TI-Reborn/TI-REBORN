"""Native TrueSkill party packet codec; legacy wire layout is unchanged."""
from collections.abc import Sequence
from enum import IntEnum

from tio.ranked_party import MAX_FIGHTERS
from .binary import Reader, Writer, PacketError
from .friends import read_name


class Operation(IntEnum):
    INVITE = 0x32
    LEAVE = 0x33
    ALLOCATE = 0x34
    ANSWER = 0x37
    REFRESH = 0x38


PARTY_REQUEST_PREFIXES = frozenset(bytes((0xc6, operation)) for operation in Operation)
PetRow = tuple[int, int, int, int, int, int, int]
MemberRow = tuple[int, bytes, int, int, int, int, int, Sequence[PetRow]]
RequestValue = tuple[bytes, str] | tuple[int, int] | int | None


def text(reader: Reader) -> str:
    size = reader.u16()
    if size > 200:
        raise PacketError('Invitation text too long')
    try:
        value = reader.read(size * 2).decode('utf-16le')
    except UnicodeError as error:
        raise PacketError('Invalid invitation text') from error
    if any(ord(character) < 32 for character in value):
        raise PacketError('Invalid invitation text')
    return value


def decode(packet: bytes) -> tuple[Operation, RequestValue]:
    reader = Reader(packet)
    if reader.u8() != 0xc6:
        raise PacketError('Expected TrueSkill party request')
    try:
        operation = Operation(reader.u8())
    except ValueError as error:
        raise PacketError('Unexpected TrueSkill party request') from error
    value: RequestValue = None
    if operation == Operation.INVITE:
        value = (read_name(reader), text(reader))
    elif operation == Operation.ALLOCATE:
        target, slots = reader.u32(), reader.u8()
        if not 0 <= slots <= MAX_FIGHTERS:
            raise PacketError('Party soldier allocation must be 0..4')
        value = (target, slots)
    elif operation == Operation.ANSWER:
        value = reader.u8()
        if value not in (0, 1):
            raise PacketError('Invalid invitation answer')
    reader.finish()
    return operation, value


def invite(name: bytes, message: str = '') -> bytes:
    read_name(Reader(name + b'\0'))
    raw = message.encode('utf-16le')
    writer = Writer().u8(0xc6).u8(0x35)
    writer.data.extend(name + b'\0')
    writer.u16(len(raw) // 2)
    writer.data.extend(raw)
    return writer.build()


def snapshot(leader: int, members: Sequence[MemberRow], tokens: int = 0) -> bytes:
    """Encode IDs, names, readiness, allocations and selected fighter summaries."""
    writer = Writer().u8(0xc6).u8(0x36).u32(leader).u32(len(members))
    if len(members) > MAX_FIGHTERS:
        raise PacketError('Party too large')
    for identity, name, level, crest, alliance, state, slots, pets in members:
        writer.u32(identity)
        writer.data.extend(name + b'\0')
        writer.u32(level).u32(crest).u32(alliance).u8(state).u8(slots).u8(len(pets))
        for resource, rank, pet_level, health, maximum, first, second in pets:
            writer.u32(resource).u32(rank).u32(pet_level).u32(health)
            writer.u16(maximum).u16(first).u16(second)
    return writer.u16(tokens).build()
