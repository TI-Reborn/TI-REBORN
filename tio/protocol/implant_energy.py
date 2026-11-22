"""Native4E attributes13/14: energy+6018/max_energy+601c (8c78c3/8c7907)."""
from .binary import PacketError, Writer


def encode_energy(actor: int, current: int, maximum: int) -> bytes:
    if not 0 <= current <= maximum <= 65535:
        raise PacketError('Energy must fit native word')
    return (Writer().u8(0x4e).u32(actor).u32(2).u32(14).u32(maximum)
            .u32(13).u32(current).u8(0).build())
