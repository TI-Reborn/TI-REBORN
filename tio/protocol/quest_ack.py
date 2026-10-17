"""Original B8/10 ACK: dispatcher9CC548, reader9CC230 consumes a Cardinal.

The reader queues the Cardinal in the native quest manager. Continue is
client-local (9CB3C0); it never grants server tutorial progress.
"""
from .binary import Reader, Writer, PacketError, uint


def encode_ack(identity):
    uint(identity, 32)
    if not identity: raise PacketError('Quest ACK identity must be positive')
    return Writer().u8(0xb8).u8(0x10).u32(identity).build()


def decode_ack(packet):
    r = Reader(packet)
    if (r.u8(), r.u8()) != (0xb8, 0x10): raise PacketError('Expected quest ACK B8/10')
    identity = r.u32()
    r.finish()
    if not identity: raise PacketError('Invalid quest ACK identity')
    return identity
