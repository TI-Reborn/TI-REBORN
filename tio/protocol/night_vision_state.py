"""Explicit F9/v1 owner-only full snapshot for the NVG client toggle gate."""
import struct
from .binary import PacketError

MAX_ACTORS = 64


def encode_night_vision_state(actors):
    actors = tuple(actors)
    if (len(actors) > MAX_ACTORS or any(type(actor) is not int or not 1 <= actor <= 0x7fffffff
                                      for actor in actors)
            or any(first >= second for first, second in zip(actors, actors[1:]))):
        raise PacketError('Invalid night vision owner snapshot')
    return b'\xf9\x01' + struct.pack('<H', len(actors)) + b''.join(
        struct.pack('<I', actor) for actor in actors)


def decode_night_vision_state(packet):
    if not isinstance(packet, bytes) or len(packet) < 4 or packet[:2] != b'\xf9\x01':
        raise PacketError('Invalid night vision snapshot')
    count = struct.unpack_from('<H', packet, 2)[0]
    if count > MAX_ACTORS or len(packet) != 4 + 4 * count:
        raise PacketError('Invalid night vision snapshot length')
    actors = tuple(struct.unpack_from('<I', packet, 4 + 4 * index)[0] for index in range(count))
    encode_night_vision_state(actors)
    return actors
