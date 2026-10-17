"""Shared authoritative bank mutations; PINs never enter command snapshots.

Adapters keep their authentication, hub lock, transaction/savepoint, private
response encoding and existing receipt namespaces. Queries are unchanged.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from types import MappingProxyType

from .game_operations import OperationRegistry, OperationSpec, OperationResult, OperationRejected
from tio import bank_economy as bank
from tio.db_transaction import Lease, current, key

PUBLIC_NAME = re.compile(r'[A-Za-z][A-Za-z0-9]{2,15}\Z')


def recipient(db, name):
    if not isinstance(name, str) or PUBLIC_NAME.fullmatch(name) is None:
        raise bank.BankRejected('Укажите точное публичное имя персонажа')
    row = db.execute('SELECT account FROM characters WHERE name=?', (name.encode('ascii'),)).fetchone()
    if row is None:
        raise bank.BankRejected('Персонаж с таким публичным именем не найден')
    bank.owner(db, row[0])
    return row[0]


@dataclass(frozen=True)
class BankContext:
    db: object
    path: object
    owner: str
    allowed: bool
    blocked: frozenset
    now: int
    pin: object = field(default=None, repr=False)
    require_recipient: object = field(default=None, repr=False)

    def check(self):
        if current() is not self.db or not self.db.in_transaction:
            raise RuntimeError('Bank operation requires the caller transaction')
        main = next((r[2] for r in self.db.execute('PRAGMA database_list') if r[1] == 'main'), None)
        if not main or key(main) != key(self.path):
            raise RuntimeError('Bank transaction belongs to another database')
        if type(self.allowed) is not bool or not isinstance(self.blocked, frozenset):
            raise RuntimeError('Bank gates must be server-derived')
        if any(not isinstance(a, str) or not a for a in self.blocked):
            raise RuntimeError('Invalid bank participant gates')
        if type(self.now) is not int or not 0 <= self.now <= 2**53:
            raise RuntimeError('Invalid bank clock')
        if self.require_recipient is not None and not callable(self.require_recipient):
            raise RuntimeError('Invalid recipient gate')
        bank.owner(self.db, self.owner)
        if not self.allowed or self.owner in self.blocked:
            raise bank.BankRejected('Операции банка доступны в городе вне боя, поиска и заявок')

    def check_recipient(self, owner):
        if self.require_recipient is not None:
            self.require_recipient(self.db, owner)


def _fields(arguments):
    for name, value in arguments.items():
        if name == 'recipientName':
            if not isinstance(value, str) or PUBLIC_NAME.fullmatch(value) is None:
                raise OperationRejected('Укажите точное публичное имя персонажа')
        elif name == 'remove':
            if type(value) is not bool:
                raise OperationRejected('Некорректный признак снятия метки')
        else:
            bank.integer(value, bank.policy()['marks']['maximum_days'] if name == 'days' else bank.MAX,
                         positive=True)


def _result(command, context, value, old):
    if not isinstance(value, Mapping):
        raise RuntimeError('Invalid bank result')
    if 'rejected' in value:
        if (command.name not in ('mark', 'reclaim')
                or not isinstance(value['rejected'], str) or not value['rejected']
                or type(value.get('retry_after', 0)) is not int or value.get('retry_after', 0) < 0):
            raise RuntimeError('Invalid bank PIN result')
        # PIN failures are committed domain results, with no item/wallet refresh.
        return OperationResult(command, value, old is not None, ())
    kind = command.name
    required = ('gold_spent', 'credits_received') if kind == 'convert' else (
        ('count', 'amount', 'balance') if kind.startswith(('stocks_', 'bonds_')) else
        ('mark_id', 'charged', 'expires') if kind == 'mark' else ('mark_id',))
    if any(type(value.get(k)) is not int or value[k] < 0 for k in required):
        raise RuntimeError('Invalid bank receipt')
    if kind.startswith(('stocks_', 'bonds_')):
        security, verb = kind.split('_')
        if (value.get('kind') != security or value.get('operation') != verb
                or value['count'] != command.arguments['count']):
            raise RuntimeError('Unrelated securities receipt')
    if kind in ('lend', 'reclaim') and value['mark_id'] != command.arguments['markId']:
        raise RuntimeError('Unrelated marked-item receipt')
    changed = tuple(value.get('changed_accounts', (context.owner,))) if old is None else ()
    return OperationResult(command, value, old is not None, changed)


def _perform(command, context):
    db, owner, now = context.db, context.owner, context.now
    args, identity, kind = command.arguments, command.identity, command.name
    bank.write(db)
    if kind == 'convert':
        operation = 'convert'; payload = dict(gold=args['gold'])
        invoke = lambda: bank.convert_gold(db, owner, args['gold'], identity)
    elif kind.startswith(('stocks_', 'bonds_')):
        security, verb = kind.split('_'); operation = 'securities'
        payload = dict(kind=security, operation=verb, count=args['count'], quote=args['quote'])
        invoke = lambda: bank.securities_trade(db, owner, security, verb, args['count'], identity,
                                              quote=args['quote'], now=now)
    elif kind == 'mark':
        operation = 'mark'; payload = dict(instance=args['instanceId'], days=args['days'])
        invoke = lambda: bank.mark_item(db, owner, args['instanceId'], args['days'], context.pin,
                                       identity, now=now, allowed=context.allowed)
    elif kind == 'lend':
        target = recipient(db, args['recipientName']); context.check_recipient(target)
        operation = 'lend'; payload = dict(mark=args['markId'], recipient=target)
        invoke = lambda: bank.lend_marked(db, owner, args['markId'], target, identity, now=now,
                                         busy=context.blocked)
    else:
        mark = bank._mark(db, owner, args['markId']); context.check_recipient(mark['holder'])
        operation = 'reclaim'; payload = dict(mark=args['markId'], remove=args['remove'])
        invoke = lambda: bank.reclaim_marked(db, owner, args['markId'], context.pin, identity,
                                            remove=args['remove'], now=now, busy=context.blocked)
    old = bank.prior(db, operation, identity, owner, bank.canonical(payload))
    return _result(command, context, invoke(), old)


BANK_OPERATIONS = OperationRegistry(tuple(
    OperationSpec(name, frozenset(fields), _fields, _perform) for name, fields in (
        ('convert', ('gold',)),
        ('stocks_buy', ('count', 'quote')), ('stocks_sell', ('count', 'quote')),
        ('bonds_buy', ('count', 'quote')), ('bonds_sell', ('count', 'quote')),
        ('mark', ('instanceId', 'days')), ('lend', ('markId', 'recipientName')),
        ('reclaim', ('markId', 'remove')),
    )
))
BANK_ACTION_FIELDS = MappingProxyType({name: spec.fields | ({'pin'} if name in ('mark', 'reclaim') else set())
                                     for name, spec in BANK_OPERATIONS.specs.items()})


def prepare_bank(name, identity, arguments):
    try:
        return BANK_OPERATIONS.prepare(name, identity, arguments)
    except OperationRejected as exc:
        raise bank.BankRejected(str(exc)) from None


def execute_bank(command, *, db, path, owner, allowed, blocked, now, pin=None, require_recipient=None):
    if isinstance(db, Lease):
        db = db.db
    context = BankContext(db, path, owner, allowed, blocked, now, pin, require_recipient)
    try:
        return BANK_OPERATIONS.execute(command, context)
    except OperationRejected as exc:
        raise bank.BankRejected(str(exc)) from None
