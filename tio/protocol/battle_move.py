"""S2C3D BattleSoldierMove: actor ID and byte coordinate pairs."""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError


@dataclass(frozen=True)
class BattleMove:
    actor_id: int
    path: tuple[tuple[int, int], ...]


def encode_battle_move(move):
    w = Writer().u8(0x3d).u32(move.actor_id).u8(len(move.path))
    for x, y in move.path:
        w.u8(x).u8(y)
    return w.build()


def decode_battle_move(packet):
    r = Reader(packet)
    if r.u8() != 0x3d:
        raise PacketError('Expected BattleSoldierMove3D')
    actor_id, count = r.u32(), r.u8()
    path = tuple((r.u8(), r.u8()) for _ in range(count))
    r.finish()
    return BattleMove(actor_id, path)


def encode_move_request(move):
    """C2S3C uses the same body as S2C3D; original ti.exe6dc460."""
    return b'\x3c' + encode_battle_move(move)[1:]


def decode_move_request(packet):
    if packet[:1] != b'\x3c':
        raise PacketError('Expected movement request3C')
    return decode_battle_move(b'\x3d' + packet[1:])
