"""Native quotation window (SC Pyramid stocks and bonds) over the shared bank.

Prices, calendar, holdings and receipts stay in tio.bank_economy; this adapter
only maps the original C1 requests onto the existing bank operations. Every
native click is a new intent, so each trade gets a fresh receipt identity.
"""
from collections.abc import Callable, Mapping
import time
import uuid

from tio import bank_economy as bank
from tio.db_transaction import transaction
from tio.protocol import securities as wire
from tio.protocol.asset_count import encode_asset_count
from tio.protocol.system_message import encode_shop_error
from tio.wallets import WalletStore
from .bank_operations import prepare_bank, execute_bank
from .clan_service import enqueue
from .economy_runtime import busy_accounts, city_idle

Action = wire.Action
TRADES = {
    Action.BOND_PURCHASE: 'bonds_buy', Action.BOND_REDEMPTION: 'bonds_sell',
    Action.STOCK_PURCHASE: 'stocks_buy', Action.STOCK_SALE: 'stocks_sell',
}


def handles(packet: bytes) -> bool:
    return packet[:1] == b'\xc1'


def bond_config(quote: Mapping) -> wire.BondConfig:
    # The window enables its buttons for from <= now <= until; the bank
    # calendar uses half-open UTC intervals.
    return wire.BondConfig(quote['sale_starts'], quote['sale_ends'] - 1,
                           quote['redemption_starts'], quote['redemption_ends'] - 1,
                           quote['redemption_credits'], quote['price_credits'])


def pyramid_config(quote: Mapping) -> wire.PyramidConfig:
    # Buy and sell share one quote. The window echoes pyramid_id in C1 07/08,
    # so carrying the quote there lets the bank reject a stale window price.
    price = quote['price']
    return wire.PyramidConfig(pyramid_id=price, selling_price=price, buying_price=price)


def pyramid_history(rows) -> tuple[wire.PyramidPoint, ...]:
    # One observed price per point: the four chart values are identical.
    return tuple(wire.PyramidPoint(r['observed'], (r['price'],) * 4) for r in rows)


def _query(db, action: Action, now: int) -> tuple[bytes, ...]:
    if action in (Action.BOND_CONFIG, Action.BOND_HISTORY):
        if action is Action.BOND_CONFIG:
            return (wire.encode_bond_config(bond_config(bank.bond_quote(db, now=now))),)
        rows = bank.quote_history(db, 'bonds', now=now)
        return (wire.encode_bond_history(tuple((r['observed'], r['price']) for r in rows)),)
    if action is Action.PYRAMID_CONFIG:
        return (wire.encode_pyramid_config(pyramid_config(bank.stock_quote(db, now=now))),)
    return (wire.encode_pyramid_history(pyramid_history(bank.quote_history(db, 'stocks', now=now))),)


def _quote(db, request: wire.Request, now: int) -> int:
    if request.action is Action.BOND_PURCHASE:
        return bank.bond_quote(db, now=now)['price_credits']
    if request.action is Action.BOND_REDEMPTION:
        if request.reference != 0:
            raise bank.BankRejected('Погашать можно только собственные векселя')
        return bank.bond_quote(db, now=now)['redemption_credits']
    return request.reference


def _trade(session, request: wire.Request, now: int) -> None:
    router = session.router
    with router.team_arena.lock, transaction(session.database) as db:
        allowed = city_idle(session)
        blocked = frozenset(busy_accounts(router, db))
        operation = prepare_bank(TRADES[request.action], 'native-' + uuid.uuid4().hex,
                                 dict(count=request.count, quote=_quote(db, request, now)))
        execute_bank(operation, db=db, path=session.database, owner=session.account,
                     allowed=allowed, blocked=blocked, now=now)


def _refresh(session, action: Action, now: int) -> tuple[bytes, ...]:
    query = Action.PYRAMID_CONFIG if action in (Action.STOCK_PURCHASE, Action.STOCK_SALE) else Action.BOND_CONFIG
    with transaction(session.database) as db:
        replies = _query(db, query, now)
    return (encode_asset_count(WalletStore(session.database).ensure(session.account)),) + replies


def respond(session, packet: bytes, *, clock: Callable[[], float] = time.time) -> tuple[bytes, ...]:
    request = wire.decode_request(packet)
    if not getattr(session, 'owned_pet_probe', False) or not session.database:
        raise ValueError('Сначала выберите персонажа')
    now = int(clock())
    if request.action not in TRADES:
        with transaction(session.database) as db:
            return _query(db, request.action, now)
    try:
        _trade(session, request, now)
    except bank.BankRejected as error:
        # A refused trade still refreshes the window, e.g. after a quote change.
        return (encode_shop_error(str(error)),) + _refresh(session, request.action, now)
    return _refresh(session, request.action, now)


def handle(presence, session, packet: bytes, *, clock: Callable[[], float] = time.time) -> bool:
    if not handles(packet):
        return False
    try:
        replies = respond(session, packet, clock=clock)
    except ValueError as error:
        replies = (encode_shop_error(str(error)),)
    enqueue(presence, session, *replies)
    return True
