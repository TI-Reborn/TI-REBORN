"""Native C1/10 sources and F0/521 outcome for the implant workshop."""
from .binary import PacketError, Reader, Writer


def decode_request(packet: bytes) -> tuple[int, int]:
    reader = Reader(packet)
    if reader.read(2) != b'\xc1\x10':
        raise PacketError('Expected implant crafting C1/10')
    first, second = reader.u32(), reader.u32()
    reader.finish()
    if not first or not second or first == second:
        raise PacketError('Нужны два разных импланта')
    return first, second


def encode_result(template: int | None, level: int = 0) -> bytes:
    # F0 dispatch7D1D98 maps448 to7D2B8F and521 to7D2BA7.
    writer = Writer().u8(0xf0).u32(448 if template is None else 521)
    if template is None:
        return writer.u32(0).build()
    if type(level) is not int or not 5 <= level <= 25:
        raise PacketError('Invalid crafted upgrade level')
    return writer.u32(2).u32(1).u32(template).u32(1).u32(level).build()
