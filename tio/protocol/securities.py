"""Original SILVER C1 ABI of the game_Quotation window: SC Pyramid stocks and bonds.

S2C dispatcher 0x6fff04 routes 02/06/0B/0D to readers 0x6ff9ec, 0x6ffcd8,
0x6ffe40 and 0x6ffdb0. C2S builders: 01 0x6ff728 and 05 0x6ff75c (both sent on
Engine.EnterWorld), 0C 0x6ff8d4, 0A 0x6ff900, 09 0x6ff92c (ConfirmBuyBonds),
03 0x6ff7cc, 07 0x6ff964, 08 0x6ff9a8. Builders 04 and 10 belong to the
administrator window and are deliberately not decoded.

Dates are signed int64 Unix seconds: the window compares them with the client
clock that 0xa8ae90 fills through DateTimeToUnix, not with Delphi TDateTime.
"""
from dataclasses import dataclass
from enum import Enum
import struct

from .binary import Reader, Writer, PacketError, uint

OPCODE = 0xc1
# The readers load the record count with movsx, so it is a signed 16-bit value.
MAXIMUM_POINTS = 0x7fff


class Action(Enum):
    BOND_CONFIG = 0x01
    BOND_REDEMPTION = 0x03
    PYRAMID_CONFIG = 0x05
    STOCK_PURCHASE = 0x07
    STOCK_SALE = 0x08
    BOND_PURCHASE = 0x09
    PYRAMID_HISTORY = 0x0a
    BOND_HISTORY = 0x0c


# Arguments after the subcode: (reference u32, count u32) or (count u32).
_LAYOUT = {
    Action.BOND_CONFIG: (), Action.PYRAMID_CONFIG: (), Action.PYRAMID_HISTORY: (), Action.BOND_HISTORY: (),
    Action.BOND_PURCHASE: ('count',),
    Action.BOND_REDEMPTION: ('reference', 'count'),
    Action.STOCK_PURCHASE: ('reference', 'count'),
    Action.STOCK_SALE: ('reference', 'count'),
}


@dataclass(frozen=True)
class Request:
    action: Action
    count: int = 0
    # Redemption: holder selector (0 = the sender). Stocks: pyramid identifier
    # copied from PyramidConfig.pyramid_id at 0xacdc40.
    reference: int = 0


@dataclass(frozen=True)
class BondConfig:
    sale_from: int
    sale_until: int
    redemption_from: int
    redemption_until: int
    redemption_credits: int
    price_credits: int


@dataclass(frozen=True)
class PyramidConfig:
    pyramid_id: int
    selling_price: int  # m868: the pyramid sells stocks to players at this price
    buying_price: int  # m872 when zero: the pyramid is not buying stocks
    # Read by 0x6ffcd8 but not used by the player window; meaning unknown.
    unknown_u32_01: int = 0
    unknown_u32_04: int = 0
    unknown_u32_06: int = 0


@dataclass(frozen=True)
class PyramidPoint:
    observed: int
    values: tuple[int, int, int, int]


def decode_request(packet: bytes) -> Request:
    r = Reader(packet)
    if r.u8() != OPCODE:
        raise PacketError('Expected securities request C1')
    subcode = r.u8()
    if subcode == 0x04:
        raise PacketError('Настройки векселей задаются сервером')
    try:
        action = Action(subcode)
    except ValueError:
        raise PacketError('Unsupported securities request') from None
    fields = {name: r.u32() for name in _LAYOUT[action]}
    r.finish()
    return Request(action, **fields)


def _time(w: Writer, value: int) -> None:
    if type(value) is not int or not -2**63 <= value < 2**63:
        raise PacketError('Expected signed 64-bit Unix time')
    w.data.extend(struct.pack('<q', value))


def _int32(w: Writer, value: int) -> None:
    if type(value) is not int or not -2**31 <= value < 2**31:
        raise PacketError('Expected signed 32-bit value')
    w.data.extend(struct.pack('<i', value))


def _header(subcode: int) -> Writer:
    return Writer().u8(OPCODE).u8(subcode)


def encode_bond_config(config: BondConfig | None) -> bytes:
    w = _header(0x02).u8(int(config is not None))
    if config is None:
        return w.build()
    for value in (config.sale_from, config.sale_until, config.redemption_from, config.redemption_until):
        _time(w, value)
    return w.u32(config.redemption_credits).u32(config.price_credits).build()


def encode_pyramid_config(config: PyramidConfig | None) -> bytes:
    w = _header(0x06).u8(int(config is not None))
    if config is None:
        return w.build()
    for value in (config.unknown_u32_01, config.pyramid_id, config.selling_price,
                  config.unknown_u32_04, config.buying_price, config.unknown_u32_06):
        w.u32(value)
    return w.build()


def _count(w: Writer, points) -> None:
    if len(points) > MAXIMUM_POINTS:
        raise PacketError('Too many quote history points')
    w.u16(len(points))


def encode_bond_history(points: tuple[tuple[int, int], ...]) -> bytes:
    w = _header(0x0d); _count(w, points)
    for observed, price in points:
        _time(w, observed); w.u32(uint(price, 32))
    return w.build()


def encode_pyramid_history(points: tuple[PyramidPoint, ...]) -> bytes:
    w = _header(0x0b); _count(w, points)
    for point in points:
        if len(point.values) != 4:
            raise PacketError('Pyramid history point has four values')
        _time(w, point.observed)
        for value in point.values:
            _int32(w, value)
    return w.build()
