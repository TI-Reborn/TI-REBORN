"""4E TANetStatusUpdate attribute10 updates own actor action points."""
from .binary import Writer, PacketError


def encode_action_points(actor_id, points):
    if not isinstance(points,int) or not 0 <= points <= 255:
        raise PacketError('Action points must fit client byte field')
    return Writer().u8(0x4e).u32(actor_id).u32(1).u32(10).u32(points).u8(0).build()
