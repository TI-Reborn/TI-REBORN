"""Original turn messages: TurnNow C8/17, YourTurn38, Finished39, EndTurn3A."""
from .binary import Reader, Writer, PacketError


def encode_end_turn(actor_id=0):
    return Writer().u8(0x3a).u32(actor_id).build()


def decode_end_turn(packet):
    r=Reader(packet)
    if r.u8()!=0x3a:raise PacketError('Expected EndTurn3A')
    actor=r.u32()
    r.finish()
    return actor


def encode_your_turn(seconds):
    return Writer().u8(0x38).u32(seconds).build()


def decode_your_turn(packet):
    r=Reader(packet)
    if r.u8()!=0x38:raise PacketError('Expected YourTurn38')
    seconds=r.u32()
    r.finish()
    return seconds


def encode_your_turn_finished():
    return b'\x39'


def encode_turn_now(owner_id, seconds):
    # Native classifier65d034 maps C8/17 to internal type1B (acd15c).
    # Type1B is NOT a wire opcode. Reader630bd8 consumes the two u32 fields.
    return Writer().u8(0xc8).u8(0x17).u32(owner_id).u32(seconds).build()


def encode_members_arranged(owners):
    """Native71: count followed by (character ID, zero-based turn order)."""
    owners=tuple(owners)
    if len(owners)>8 or len(set(owners))!=len(owners):
        raise PacketError('Expected at most eight distinct battle members')
    w=Writer().u8(0x71).u8(len(owners))
    for index,owner in enumerate(owners):w.u32(owner).u8(index)
    return w.build()


def turn_seconds(actor_count):
    """Classic manual p37: one/two/three fighters get40/60/120 seconds."""
    if actor_count not in (1,2,3):raise ValueError('Expected one to three fighters')
    return (40,60,120)[actor_count-1]
