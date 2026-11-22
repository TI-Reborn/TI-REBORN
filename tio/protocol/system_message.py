"""Confirmed subset of TI F0 SystemMessage: town command98, integer argument.

Native dispatch7d1afc maps98 to7d2e78. Town selection and town view are
separate: this packet alone does not guarantee that the city UI opens.
"""
from .binary import Reader, Writer, PacketError

MODERATION_ROLE_DISABLED = 0x54494F30
MODERATION_ROLE_ENABLED = 0x54494F31


def encode_moderation_role(enabled: bool) -> bytes:
    """Private server-to-client projection for the native moderation menu."""
    command = MODERATION_ROLE_ENABLED if enabled else MODERATION_ROLE_DISABLED
    return Writer().u8(0xf0).u32(command).u32(0).build()


def encode_current_town(town_id: int) -> bytes:
    # Consumer uses a one-based town table. Zero/negative IDs are not valid here.
    if type(town_id) is not int or not 1 <= town_id <= 255:
        raise PacketError('Town ID must be 1..255')
    return Writer().u8(0xf0).u32(98).u32(1).u32(1).u32(town_id).build()


def decode_current_town(data: bytes) -> int:
    r = Reader(data)
    if (r.u8(), r.u32(), r.u32(), r.u32()) != (0xf0, 98, 1, 1):
        raise PacketError('Expected F0 command98 with one type1 argument')
    town_id = r.u32()
    r.finish()
    encode_current_town(town_id)
    return town_id


def encode_open_town_view() -> bytes:
    """F0 command117, no arguments; native branch7d26e2 calls8596e0."""
    return Writer().u8(0xf0).u32(117).u32(0).build()


def encode_leave_room() -> bytes:
    """F0 command24: branch7d2661 ->7d4a88 clears membership and closes room."""
    return Writer().u8(0xf0).u32(24).u32(0).build()


def encode_finish_battle_view() -> bytes:
    """F0/449 ->7d2481 closes results and dispatches scene event13."""
    return Writer().u8(0xf0).u32(449).u32(0).build()


def encode_shop_error(parameter: str) -> bytes:
    from tio.localization import LocalizedPacket,english
    return LocalizedPacket(_encode_shop_error(parameter),lambda: _encode_shop_error(english(parameter)[:255]))


def _encode_shop_error(parameter: str) -> bytes:
    """F0/394 s394: localized parameter error, one type5 UTF16 CString.

    Reader7d0aa8 uses605df4, the same UTF16 reader as chat text.
    Type0 treats high bytes as Latin characters, corrupting Russian text.
    Consumer7d1d91 clears waiting;
    command394 uses the generic localized-message branch7d3d52.
    """
    if not isinstance(parameter, str):
        raise PacketError('Expected error parameter text')
    try:
        raw = parameter.encode('cp1251')
    except UnicodeEncodeError as error:
        raise PacketError('Parameter is not cp1251') from error
    if not raw or len(raw)>255 or b'\0' in raw:
        raise PacketError('Invalid error parameter CString')
    w=Writer().u8(0xf0).u32(394).u32(1).u32(5)
    w.data.extend(parameter.encode('utf-16-le')+b'\0\0')
    return w.build()


def encode_insufficient_credits():
    """F0/47 requires a numeric item template ID, resolved by a75f24."""
    return Writer().u8(0xf0).u32(47).u32(1).u32(1).u32(1).build()
