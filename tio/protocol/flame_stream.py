"""F7/v2 transient flame event; F7/v1 terrain snapshots are unchanged."""
from .binary import Reader, Writer, PacketError

MAX_POINTS = 72


def encode_flame_stream(actor_id, token, points):
    points = tuple(points)
    if type(actor_id) is not int or not 0 < actor_id <= 0xffffffff or type(token) is not int or not 0 <= token <= 0xffffffff:
        raise PacketError('Invalid flame event identity')
    if not 1 <= len(points) <= MAX_POINTS:
        raise PacketError('Invalid flame point count')
    w = Writer().u8(0xf7).u8(2).u32(actor_id).u32(token).u8(len(points))
    for x, y, size, travel in points:
        if any(type(v) is not int for v in (x,y,size,travel)) or not (0 <= x < 8160 and 0 <= y < 8160 and 4 <= size <= 32 and 1 <= travel <= 24):
            raise PacketError('Invalid flame point')
        w.u16(x).u16(y).u8(size).u8(travel)
    return w.build()


def decode_flame_stream(packet):
    r = Reader(packet)
    if (r.u8(), r.u8()) != (0xf7, 2):
        raise PacketError('Unsupported flame event')
    actor, token, count = r.u32(), r.u32(), r.u8()
    if not 1 <= count <= MAX_POINTS:
        raise PacketError('Invalid flame count')
    points = tuple((r.u16(),r.u16(),r.u8(),r.u8()) for _ in range(count))
    r.finish()
    encode_flame_stream(actor, token, points)
    return actor, token, points
