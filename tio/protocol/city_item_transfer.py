"""City6E writer992444 uses the same direction order as battle98F478."""

from .battle_exchange import BattleExchange, decode_exchange, encode_exchange


def decode_transfer(packet: bytes) -> BattleExchange:
    request = decode_exchange(packet)
    return request


def encode_transfer(request: BattleExchange) -> bytes:
    return encode_exchange(request)
