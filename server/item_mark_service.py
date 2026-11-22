"""Route the original item mark windows to the authoritative bank."""
from collections.abc import Callable
from contextlib import closing
import time
from uuid import uuid4

from tio import bank_economy as bank
from tio.db_transaction import connect, transaction
from tio.protocol import item_marks as wire
from tio.protocol.system_message import encode_shop_error
from .economy_runtime import busy_accounts, city_idle


def handles(packet: bytes) -> bool:
    return packet[:2] in (b'\xb8\x01', b'\xb8\x02', b'\xb8\x03', b'\xb8\x04')


def listing(db, account: str, now: int) -> bytes:
    rows = bank.window_mark_rows(db, account, now) if bank.table(db, 'bank_item_marks') else ()
    return wire.encode_list(rows)


def _mutate(db, session, request: wire.Request, now: int) -> dict:
    account = session.account
    key = 'native-mark-' + uuid4().hex
    if request.action is wire.Action.SET:
        days = request.days or bank.policy()['marks']['window_days']
        return bank.mark_item(db, account, request.instance, days, request.pin, key, now=now)
    blocked = busy_accounts(session.router, db)
    if request.action is wire.Action.REMOVE:
        return bank.remove_window_mark(db, account, request.instance, request.pin, key, now=now, busy=blocked)
    return bank.return_window_mark(db, account, request.instance, key, busy=blocked)


def respond(session, packet: bytes, *, clock: Callable[[], float] = time.time) -> tuple[bytes, ...]:
    try:
        request = wire.decode_request(packet)
        if not getattr(session, 'owned_pet_probe', False):
            raise bank.BankRejected('Сначала выберите персонажа')
        now = int(clock())
        if request.action is wire.Action.LIST:
            with closing(connect(session.database)) as db:
                db.execute('BEGIN')
                return (listing(db, session.account, now),)

        with session.router.team_arena.lock:
            with transaction(session.database) as db:
                if not city_idle(session):
                    raise bank.BankRejected('Операции с метками доступны в городе вне боя и поиска')
                result = _mutate(db, session, request, now)
                if 'rejected' in result:
                    return (encode_shop_error(result['rejected']),)
                # Encode before commit so a bad list cannot leave the window
                # reporting failure for a successful mark or money debit.
                mark_list = listing(db, session.account, now)
                snapshot = session.bank_session._snapshot(db, items=True)
            with session.router.lock:
                for peer in session.router.active_accounts.values():
                    if peer.account in result['changed_accounts']:
                        peer._economy_inventory_digest = None
        if request.action is wire.Action.SET:
            notice = f"Метка установлена. Списано {result['charged']} кр."
        elif result['destroyed']:
            notice = 'Предмет уничтожен.'
        else:
            notice = 'Метка снята.' if request.action is wire.Action.REMOVE else 'Предмет возвращён владельцу.'
        return (*snapshot, mark_list, encode_shop_error(notice))
    except ValueError as error:
        return (encode_shop_error(str(error)),)
