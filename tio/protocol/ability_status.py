"""7F/01 skill state, original serializer62f038 and consumer8c0790.

State3 draws cooldown progress (8ba31f); state4 passes the UI activation
gate (8bba8e). Remaining cooldown is an absolute value, not a decrement.
"""
from dataclasses import dataclass
from .binary import Writer, Reader, PacketError


@dataclass(frozen=True)
class AbilityStatus:
    ability_id: int
    level: int
    state: int
    remaining: int


def encode_ability_status(actor_id, entries):
    entries = tuple(entries)
    # Consumer loops with a byte even though the wire count is u32.
    if len(entries) > 255:
        raise PacketError('Too many skill states for native consumer')
    w = Writer().u8(0x7f).u8(1).u32(actor_id).u32(len(entries))
    for e in entries:
        if e.state not in (3, 4):
            raise PacketError('Only recovered cooldown/available states supported')
        w.u32(e.ability_id).u8(e.level).u32(e.state).u32(e.remaining)
    return w.build()


def decode_ability_status(packet):
    r = Reader(packet)
    if (r.u8(), r.u8()) != (0x7f, 1):
        raise PacketError('Expected skill status7F/01')
    actor_id, count = r.u32(), r.u32()
    if count > 255:
        raise PacketError('Too many skill states for native consumer')
    entries = tuple(AbilityStatus(r.u32(), r.u8(), r.u32(), r.u32()) for _ in range(count))
    r.finish()
    if any(e.state not in (3, 4) for e in entries):
        raise PacketError('Unsupported skill state')
    return actor_id, entries
