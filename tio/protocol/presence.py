"""Native chat rosters: C7 global; 4F/51 location, trade and help (7d02d8)."""
from dataclasses import dataclass
from .binary import Writer, PacketError


@dataclass(frozen=True)
class Player:
    identity: int
    name: bytes
    level: int = 1
    crest: int = 0
    alliance: int = 0
    status: int = 0
    rank: int = 0
    dealer: int = 0


def _encode_players(players,header):
    players=tuple(players)
    if len(players)>255:raise PacketError('Presence batch exceeds byte count')
    w=Writer();w.data.extend(header);w.u8(len(players))
    for p in players:
        if not p.name or len(p.name)>255 or b'\0' in p.name:raise PacketError('Invalid player name')
        w.u32(p.identity);w.data.extend(p.name+b'\0')
        w.u8(p.level).u32(p.crest).u32(p.alliance).u8(p.status).u32(p.rank).u8(p.dealer)
    return w.build()


def encode_players(players):return _encode_players(players,b'\xc7\x02')


def encode_location_players(players):return _encode_players(players,b'\x4f')


def encode_location_clear():return b'\x51'


def encode_clear():return b'\xc7\x04'


def encode_remove(identities):
    identities=tuple(identities)
    w=Writer().u8(0xc7).u8(3).u32(len(identities))
    for identity in identities:w.u32(identity)
    return w.build()
