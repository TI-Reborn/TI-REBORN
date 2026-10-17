"""Shared city-service commands for native and authenticated portal adapters."""
from dataclasses import dataclass
from collections.abc import Mapping
from types import MappingProxyType
from .game_operations import (OperationRegistry, OperationSpec, OperationResult,
                              OperationRejected)
from tio.db_transaction import current, key
from tio.services_completion import ServiceRejected


@dataclass(frozen=True)
class ServiceContext:
    db: object
    path: object
    helper: object
    owner: str
    allowed: bool

    def check(self):
        # A service cannot accidentally open/commit a different database.
        if current() is not self.db or not self.db.in_transaction:
            raise RuntimeError('City operation requires the caller transaction')
        if key(self.helper.path) != key(self.path):
            raise RuntimeError('City service belongs to another database')
        main = next((row[2] for row in self.db.execute('PRAGMA database_list') if row[1] == 'main'), None)
        if not main or key(main) != key(self.path):
            raise RuntimeError('City transaction belongs to another database')
        if type(self.allowed) is not bool:
            raise RuntimeError('City gate must be server-derived boolean')
        self.helper._gate(self.db, self.owner, self.allowed)


def _fields(arguments):
    for name, value in arguments.items():
        if name == 'newName':
            if not isinstance(value, str) or not 1 <= len(value) <= 16:
                raise OperationRejected('Некорректное имя бойца')
        elif name == 'command':
            if not isinstance(value, str) or not value.startswith('/changename ') or len(value) > 300:
                raise OperationRejected('Некорректная команда переименования')
        elif type(value) is not int or not 1 <= value <= 0xffffffff:
            raise OperationRejected('Некорректный ID или параметр услуги')
    if 'service' in arguments and (arguments['service'] not in (3, 4) or arguments['wanted'] not in (1, 2)):
        raise OperationRejected('Некорректный вид услуги склада')


def _result(command, context, result):
    if (not isinstance(result, Mapping) or type(result.get('replayed')) is not bool
            or not isinstance(result.get('receipt'), Mapping)):
        raise RuntimeError('Service returned an invalid result')
    receipt = result['receipt']
    action = 'service_rename' if command.name == 'service_rename_command' else command.name
    if (receipt.get('requestId') != command.identity or receipt.get('action') != action
            or type(receipt.get('creditsDelta')) is not int or type(receipt.get('goldDelta')) is not int):
        raise RuntimeError('Service returned an unrelated receipt')
    replayed = result['replayed']
    return OperationResult(command, result, replayed, () if replayed else (context.owner,))


def _rename(command, context):
    a = command.arguments
    return _result(command, context, context.helper.rename(context.owner, a['petId'], a['newName'],
        identity=command.identity, allowed=context.allowed))


def _native_rename(command, context):
    return _result(command, context, context.helper.rename_command(context.owner, command.arguments['command'],
        identity=command.identity, allowed=context.allowed))


def _dismiss(command, context):
    return _result(command, context, context.helper.schedule_dismiss(context.owner, command.arguments['petId'],
        identity=command.identity, allowed=context.allowed))


def _avatar(command, context):
    a = command.arguments
    return _result(command, context, context.helper.purchase_avatar(context.owner, a['petId'], a['avatarId'],
        identity=command.identity, allowed=context.allowed))


def _dogmeat(command, context):
    a = command.arguments
    return _result(command, context, context.helper.claim_dogmeat(context.owner, a['dismissedPetId'], a['petId'],
        identity=command.identity, allowed=context.allowed))


def _warehouse(command, context):
    from tio import warehouse_completion as warehouse
    a = command.arguments
    result = warehouse.clan_purchase(context.db, context.owner, a['service'], a['wanted'],
        expected_clan=a['expectedClan'], identity=command.identity)
    result = dict(result, receipt=dict(requestId=command.identity, action=command.name,
        creditsDelta=-result['charged_credits'], goldDelta=0))
    return _result(command, context, result)


SERVICE_OPERATIONS = OperationRegistry((
    OperationSpec('service_rename', frozenset(('petId', 'newName')), _fields, _rename),
    OperationSpec('service_rename_command', frozenset(('command',)), _fields, _native_rename),
    OperationSpec('service_dismiss', frozenset(('petId',)), _fields, _dismiss),
    OperationSpec('service_avatar', frozenset(('petId', 'avatarId')), _fields, _avatar),
    OperationSpec('service_claim_dogmeat', frozenset(('dismissedPetId', 'petId')), _fields, _dogmeat),
    OperationSpec('warehouse_purchase', frozenset(('service', 'wanted', 'expectedClan')), _fields, _warehouse),
))

# Transport schemas derive from the same immutable operation descriptions.
# The raw native chat adapter is deliberately absent from both HTTP contracts.
CITY_SERVICE_FIELDS = MappingProxyType({name: spec.fields for name, spec in SERVICE_OPERATIONS.specs.items()
                                      if name != 'service_rename_command'})
SERVICE_ACTION_FIELDS = MappingProxyType({name: fields for name, fields in CITY_SERVICE_FIELDS.items()
                                        if name != 'warehouse_purchase'})


def prepare_service(name, identity, arguments):
    try:
        return SERVICE_OPERATIONS.prepare(name, identity, arguments)
    except OperationRejected as exc:
        raise ServiceRejected(str(exc)) from None


def execute_service(command, *, db, path, helper, owner, allowed):
    context = ServiceContext(db, path, helper, owner, allowed)
    try:
        return SERVICE_OPERATIONS.execute(command, context)
    except OperationRejected as exc:
        raise ServiceRejected(str(exc)) from None
