"""Private city 6E routing; battles retain their turn-bound exchange handler."""
from collections.abc import Callable
import time

from tio.city_item_transfer import transfer
from tio.protocol.system_message import encode_shop_error
from .clan_service import enqueue
from .economy_runtime import city_idle


def handle(presence, session, packet: bytes, *, clock: Callable[[], float] = time.monotonic) -> bool:
    if packet[:1] != b'\x6e':
        return False
    hub = session.router.team_arena
    with hub.lock:
        if hub.busy(session) or hub.retained(session.account) or session.arena._fields:
            return False
        try:
            if not city_idle(session):
                raise ValueError('Передача доступна только в городе вне боя и поиска')
            now = clock()
            recent = getattr(session, '_city_item_transfer_recent', None)
            # shortcut: native6E has no nonce; suppress identical packets for 1s.
            if recent is not None and recent[0] == packet and 0 <= now-recent[1] < 1:
                raise ValueError('Повторный запрос передачи предметов')
            replies = transfer(session.database, session.account, packet)
            session._city_item_transfer_recent = (packet, now)
        except ValueError as error:
            replies = (encode_shop_error(str(error)),)
        enqueue(presence, session, *replies)
    return True
