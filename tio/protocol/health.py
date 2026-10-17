"""4E status4 carries absolute current HP; native8c75b2 writes actor+6006."""
from .binary import Writer,PacketError


def encode_health(actor_id,health):
    if type(health) is not int or not 0<=health<=65535:
        raise PacketError('Health must fit native word')
    return Writer().u8(0x4e).u32(actor_id).u32(1).u32(4).u32(health).u8(0).build()
