"""S2C43: silver8c7edc dispatches to8c71e0, reads one actor u32."""
from .binary import Reader, Writer, PacketError


def encode_battle_remove(actor_id):
    return Writer().u8(0x43).u32(actor_id).build()


def decode_battle_remove(packet):
    r = Reader(packet)
    if r.u8() != 0x43:
        raise PacketError('Expected battle actor removal43')
    actor_id = r.u32()
    r.finish()
    return actor_id
