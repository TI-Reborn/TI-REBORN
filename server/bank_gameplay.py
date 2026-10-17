"""Private city !bank commands over shared authoritative bank SQL helpers.

This is an explicit emulator command interface, not an original bank action
opcode. Root supplies the authenticated selected save owner, city/busy fences,
and outbound mark projection. Never log raw commands: mark/reclaim contain PINs.
"""
from dataclasses import dataclass
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import re
import time

from tio import bank_economy as bank
from tio.db_transaction import connect, transaction
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore
from tio.protocol.asset_count import encode_asset_count
from tio.protocol.chat import decode_send, encode_system_message
from tio.protocol.warehouse import encode_private_warehouse_snapshot
from .bank_operations import PUBLIC_NAME, recipient, prepare_bank, execute_bank


REQUEST_ID = re.compile(r'[A-Za-z0-9_-]{16,64}\Z')
NUMBER = re.compile(r'[1-9][0-9]{0,9}\Z')


@dataclass(frozen=True)
class BankReply:
    packets: tuple[bytes, ...]
    # Trusted save owners for root-only refresh; never public text or broadcast.
    changed_accounts: tuple[str, ...] = ()


class _GameplayOnly:
    def status(self):
        return dict(configured=False, provider=None, missing=['gameplay has no payment endpoint'])


def is_command(text):
    return isinstance(text, str) and text.split(maxsplit=1)[:1] == ['!bank']


def redact_command(text):
    """Root can use this before any packet21/chat logging or broadcast."""
    return '!bank [private]' if is_command(text) else None


def _number(text, maximum=bank.MAX):
    if not isinstance(text, str) or NUMBER.fullmatch(text) is None:
        raise bank.BankRejected('Нужно положительное целое число без знака')
    return bank.integer(int(text), maximum, positive=True)


def _request(text):
    if not isinstance(text, str) or REQUEST_ID.fullmatch(text) is None:
        raise bank.BankRejected('ID операции: 16–64 латинских букв, цифр, _ или -')
    return text


def _text(text):
    if not isinstance(text, str) or not text or any(ord(c) < 32 for c in text):
        raise bank.BankRejected('Некорректный текст команды банка')
    try:
        units = len(text.encode('utf-16le')) // 2
    except UnicodeError as error:
        raise bank.BankRejected('Некорректный текст команды банка') from error
    if units > 200:
        raise bank.BankRejected('Команда банка: не более 200 символов UTF-16')
    return text.split()


def _chat(lines):
    result = []
    for line in lines:
        # Every generated line is bounded independently of user input. No PIN,
        # request ID, account key or raw command is interpolated into responses.
        if any(ord(c) < 32 for c in line) or len(line.encode('utf-16le')) > 400:
            raise RuntimeError('Invalid generated bank reply')
        result.append(encode_system_message(4, b'Bank', line))
    return tuple(result)


def _date(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


class BankGameSession:
    def __init__(self, database, account, *, clock=None):
        self.path = Path(database)
        self.account = account
        self.clock = time.time if clock is None else clock
        # Constructors create additive schema only. An unknown account is
        # rejected before ensure() could seed a wallet or create a player.
        self.wallets = WalletStore(self.path)
        self.pets = OwnedPetStore(self.path)
        self.warehouse = WarehouseStore(self.path)
        self.store = bank.BankStore(self.path, provider=_GameplayOnly(), clock=self.clock)
        with transaction(self.path) as db:
            bank.owner(db, account)

    @contextmanager
    def _action(self):
        # transaction() joins root's journal; the leased store scope adds a
        # savepoint. A normal invalid command can then be reported privately
        # without committing partial helper writes in an enclosing transaction.
        # Returned PIN failures are normal results and release this savepoint.
        with transaction(self.path):
            with closing(connect(self.path)) as db, db:
                yield db

    def _assets(self, db):
        bank.owner(db, self.account)
        return encode_asset_count(bank.project_assets(db, self.account, self.wallets.ensure(self.account)))

    def _snapshot(self, db, *, items):
        packets = [self._assets(db)]
        if items:
            for _, pet, inventory in self.pets.list(self.account):
                packets.extend((pet, inventory))
            packets.extend(encode_private_warehouse_snapshot(self.warehouse.items(self.account)))
        # Canonical inventories only; root applies marker names/times once on
        # outbound30/6A. These packets must never be saved back into the DB.
        return tuple(packets)

    def snapshot(self, *, items=True):
        """Root refreshes trusted, currently idle recipients after item writes."""
        if type(items) is not bool:
            raise ValueError('items must be boolean')
        with transaction(self.path) as db:
            return self._snapshot(db, items=items)

    def _reply(self, db, lines, *, changed=(), assets=True, items=False):
        return BankReply(_chat(lines) + (self._snapshot(db, items=items) if assets else ()), tuple(changed))

    @staticmethod
    def _recipient(db, name):
        return recipient(db, name)

    def _execute(self, db, kind, identity, arguments, *, allowed, blocked, now, pin=None):
        command = prepare_bank(kind, identity, arguments)
        return execute_bank(command, db=db, path=self.path, owner=self.account,
                            allowed=allowed, blocked=blocked, now=now, pin=pin)

    @staticmethod
    def _public_name(db, account):
        row = db.execute('SELECT name FROM characters WHERE account=? ORDER BY slot LIMIT 1', (account,)).fetchone()
        if row is None:
            return 'неизвестен'
        return bytes(row[0]).decode('cp1251')

    def handle(self, packet, *, city_idle, busy=()):
        """Root consumes recognized packet21 commands before any broadcast."""
        _, text, _ = decode_send(packet)
        return self.command(text, city_idle=city_idle, busy=busy)

    def command(self, text, *, city_idle, busy=()):
        if not is_command(text):
            return None
        try:
            tokens = _text(text)
            if type(city_idle) is not bool:
                raise bank.BankRejected('Состояние города не подтверждено')
            blocked = frozenset(busy)
            if any(not isinstance(a, str) or not a for a in blocked):
                raise bank.BankRejected('Состояние участников не подтверждено')
            action = tokens[1] if len(tokens) > 1 else 'help'
            now = int(self.clock())
            with self._action() as db:
                bank.owner(db, self.account)
                if action == 'help' and len(tokens) <= 2:
                    return self._reply(db, (
                        '!bank quotes | history [stocks|bonds] | marks',
                        '!bank stocks|bonds buy|sell COUNT QUOTE ID',
                        '!bank mark INSTANCE DAYS PIN ID; lend MARK PUBLICNAME ID',
                        '!bank reclaim MARK PIN ID [remove]. ID: 16–64 букв/цифр/_/-.',
                        'Команды банка обрабатывает сервер; ответ виден только вам.',
                    ), assets=False)
                if action == 'quotes' and len(tokens) == 2:
                    stocks = bank.stock_quote(db, now=now)
                    bonds = bank.bond_quote(db, now=now)
                    return self._reply(db, (
                        f"Акции: {stocks['price']} кредитов за штуку, покупка и продажа по одной котировке.",
                        f"Векселя: {bonds['price_gold']} кредитов за штуку; погашение {bonds['redemption_credits']} кредитов.",
                        f"Продажа векселей {'открыта' if bonds['sale_open'] else 'закрыта'}; погашение {'открыто' if bonds['redemption_open'] else 'закрыто'} (UTC).",
                        'Единственная игровая валюта — кредиты. Покупка валюты за деньги отключена.',
                    ))
                if action == 'history' and (len(tokens) == 2 or len(tokens) == 3 and tokens[2] in ('stocks', 'bonds')):
                    kinds = (tokens[2],) if len(tokens) == 3 else ('stocks', 'bonds')
                    lines = []
                    for kind in kinds:
                        rows = bank.quote_history(db, kind, now=now)
                        lines.append(f"{'Акции' if kind == 'stocks' else 'Векселя'}: последние {min(12,len(rows))} зарегистрированных котировок.")
                        lines.extend(f"{_date(r['observed'])}: {r['price']} кредитов" for r in rows[-12:])
                    return self._reply(db, lines)
                if action == 'marks' and len(tokens) == 2:
                    rows = bank.marked_items(db, self.account)
                    lines = ['Ваши метки (не более 100 последних):']
                    lines.extend(f"Метка {r['id']}: предмет {r['template']}, у {self._public_name(db,r['holder'])}, до {_date(r['expires'])}, {r['state']}." for r in rows)
                    if not rows:lines.append('Меток пока нет.')
                    return self._reply(db, lines, assets=False)
                # Mutation fences apply before even a durable replay: root must
                # take its shared city/lease lock before supplying this set.
                if not city_idle or self.account in blocked:
                    raise bank.BankRejected('Операции банка доступны в городе вне боя, поиска и заявок')
                items = False
                if action == 'convert' and len(tokens) == 4:
                    outcome = self._execute(db, 'convert', _request(tokens[3]), dict(gold=_number(tokens[2])),
                                            allowed=city_idle, blocked=blocked, now=now)
                    result = outcome.as_dict()
                    lines = [f"Обмен: {result['gold_spent']} Gold → {result['credits_received']} кредитов."]
                elif action in ('stocks', 'bonds') and len(tokens) == 6 and tokens[2] in ('buy', 'sell'):
                    count, quote, key = _number(tokens[3]), _number(tokens[4]), _request(tokens[5])
                    outcome = self._execute(db, action+'_'+tokens[2], key, dict(count=count, quote=quote),
                                            allowed=city_idle, blocked=blocked, now=now)
                    result = outcome.as_dict()
                    lines = [f"{'Акции' if action == 'stocks' else 'Векселя'}: {'куплено' if tokens[2]=='buy' else 'продано'} {result['count']}; остаток {result['balance']}."]
                elif action == 'mark' and len(tokens) == 6:
                    instance, days, key = _number(tokens[2]), _number(tokens[3], bank.policy()['marks']['maximum_days']), _request(tokens[5])
                    outcome = self._execute(db, 'mark', key, dict(instanceId=instance, days=days),
                                            allowed=city_idle, blocked=blocked, now=now, pin=tokens[4])
                    result = outcome.as_dict()
                    items = True
                    lines = [] if 'rejected' in result else [f"Метка {result['mark_id']}: списано {result['charged']} кредитов; действует до {_date(result['expires'])}."]
                elif action == 'lend' and len(tokens) == 5:
                    mark, key = _number(tokens[2]), _request(tokens[4])
                    outcome = self._execute(db, 'lend', key, dict(markId=mark, recipientName=tokens[3]),
                                            allowed=city_idle, blocked=blocked, now=now)
                    result = outcome.as_dict()
                    items = True
                    lines = [f"Метка {result['mark_id']}: {'предмет уже уничтожен' if result['destroyed'] else 'вещь передана персонажу '+tokens[3] }."]
                elif action == 'reclaim' and (len(tokens) == 5 or len(tokens) == 6 and tokens[5] == 'remove'):
                    mark, key = _number(tokens[2]), _request(tokens[4]);remove = len(tokens) == 6
                    outcome = self._execute(db, 'reclaim', key, dict(markId=mark, remove=remove),
                                            allowed=city_idle, blocked=blocked, now=now, pin=tokens[3])
                    result = outcome.as_dict()
                    items = True
                    lines = [] if 'rejected' in result else [f"Метка {result['mark_id']}: {'предмет уже уничтожен' if result['destroyed'] else 'вещь возвращена'+('; метка снята' if result['removed'] else '')}."]
                else:
                    raise bank.BankRejected('Неизвестная команда или неверные параметры; !bank help')
                if 'rejected' in result:
                    # This is an ordinary result, not an exception: committing
                    # the enclosing gameplay journal preserves PIN rate limits.
                    lines = [result['rejected'] + (f"; повтор через {result['retry_after']} сек." if result.get('retry_after') else '.')]
                    return self._reply(db, lines, assets=False)
                return self._reply(db, lines, changed=outcome.changed_owners, items=items)
        except bank.BankRejected as error:
            return BankReply(_chat(('Банк: ' + str(error),)))
