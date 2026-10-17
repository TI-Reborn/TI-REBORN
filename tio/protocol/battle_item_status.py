"""Native4E attribute12 is absolute sight (8c7a8b -> a86df8).

Unlike BattleSoldier3B this update preserves the actor's current animation.
The original initial sight field is one byte, although4E stores a u32.
"""
from .binary import Writer, Reader, PacketError


def encode_sight(actor_id, sight):
    if type(sight) is not int or not 0 <= sight <= 255:
        raise PacketError('Sight must fit native byte')
    return Writer().u8(0x4e).u32(actor_id).u32(1).u32(12).u32(sight).u8(0).build()


def decode_sight(packet):
    r = Reader(packet)
    if r.u8() != 0x4e:
        raise PacketError('Expected attribute4E')
    actor = r.u32()
    if r.u32() != 1 or r.u32() != 12:
        raise PacketError('Expected one sight attribute12')
    sight = r.u32()
    if sight > 255 or r.u8() != 0:
        raise PacketError('Invalid sight update')
    r.finish()
    return actor, sight
