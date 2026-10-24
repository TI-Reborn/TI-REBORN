"""Native 13/u32 slot and 14/u8 result: builders 889d8c, reader 88aa60."""
from .binary import PacketError, Reader, Writer


def decode_delete_request(packet: bytes) -> int:
    reader = Reader(packet)
    if reader.u8() != 0x13:
        raise PacketError('Expected character deletion request')
    slot = reader.u32()
    reader.finish()
    if not 1 <= slot <= 5:
        raise PacketError('Character slot must be 1..5')
    return slot


def encode_delete_result(status: int) -> bytes:
    return Writer().u8(0x14).u8(status).build()
