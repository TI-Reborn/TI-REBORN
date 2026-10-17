"""Original net3_Markers: B2/06 request and B2/07 notification.

Both contain a mark byte, character u32 and tile x/y bytes. 70E0A0 writes
the request; 962659 dispatches B2/07 to the 70E100 notification reader. The native
HUD passes kind 1 to place a mark and FF, with character=0, to remove one.
Server notifications use the recipient's BattleMemberList character IDs.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError


PLACE=1
REMOVE=0xff
NATIVE_TTL_SECONDS=200


@dataclass(frozen=True)
class TacticalMark:
    kind: int
    character_id: int
    x: int
    y: int


def _encode(value,subcommand):
    if type(value.kind) is not int or value.kind not in (PLACE,REMOVE):
        raise PacketError('Unsupported tactical mark kind')
    return (Writer().u8(0xb2).u8(subcommand).u8(value.kind).u32(value.character_id)
            .u8(value.x).u8(value.y).build())


def _decode(packet,subcommand):
    reader=Reader(packet)
    if reader.read(2)!=bytes((0xb2,subcommand)):raise PacketError('Unexpected tactical mark direction')
    value=TacticalMark(reader.u8(),reader.u32(),reader.u8(),reader.u8())
    reader.finish()
    if value.kind not in (PLACE,REMOVE):raise PacketError('Unsupported tactical mark kind')
    return value


def encode_tactical_mark(value):return _encode(value,6)


def decode_tactical_mark(packet):return _decode(packet,6)


def encode_tactical_mark_notification(value):return _encode(value,7)


def decode_tactical_mark_notification(packet):return _decode(packet,7)
