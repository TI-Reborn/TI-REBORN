"""Transport-independent commands, checks and immutable operation results.

The caller retains the existing authoritative lock/transaction and receipt
policy. Checking a command never authorizes a later execution: execute always
checks again in the current context. Storage failures are not business errors.
"""
from collections.abc import Mapping
from dataclasses import dataclass
import math
import re
from types import MappingProxyType


class OperationRejected(ValueError):
    """Invalid command shape; adapters retain their existing error encoding."""


def _freeze(value):
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise OperationRejected('Ключи команды должны быть строками')
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise OperationRejected('Недопустимое значение команды')


def _plain(value):
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


@dataclass(frozen=True)
class OperationCommand:
    name: str
    identity: str
    arguments: Mapping

    def __post_init__(self):
        if not isinstance(self.name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', self.name):
            raise OperationRejected('Неизвестная игровая операция')
        if not isinstance(self.identity, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}', self.identity):
            raise OperationRejected('Некорректный ID операции')
        if not isinstance(self.arguments, Mapping):
            raise OperationRejected('Параметры операции должны быть объектом')
        object.__setattr__(self, 'arguments', _freeze(self.arguments))


@dataclass(frozen=True)
class OperationResult:
    command: OperationCommand
    data: Mapping
    replayed: bool
    changed_owners: tuple

    def __post_init__(self):
        if type(self.replayed) is not bool or not isinstance(self.data, Mapping):
            raise RuntimeError('Invalid operation result')
        if (not isinstance(self.changed_owners, tuple)
                or any(not isinstance(owner, str) or not owner for owner in self.changed_owners)
                or self.replayed and self.changed_owners):
            raise RuntimeError('Invalid changed owners')
        try:
            object.__setattr__(self, 'data', _freeze(self.data))
        except OperationRejected as exc:
            raise RuntimeError('Invalid operation result data') from exc

    def as_dict(self):
        return _plain(self.data)


@dataclass(frozen=True)
class OperationSpec:
    name: str
    fields: frozenset
    validate: object
    perform: object

    def __post_init__(self):
        if not isinstance(self.fields, frozenset) or not callable(self.validate) or not callable(self.perform):
            raise TypeError('Operation spec requires immutable fields and callables')


class OperationRegistry:
    def __init__(self, specs):
        entries = {}
        for spec in specs:
            if spec.name in entries:
                raise ValueError('Duplicate operation: '+spec.name)
            entries[spec.name] = spec
        self.specs = MappingProxyType(entries)

    def _spec(self, command):
        if not isinstance(command, OperationCommand):
            raise OperationRejected('Ожидается игровая команда')
        spec = self.specs.get(command.name)
        if spec is None or set(command.arguments) != spec.fields:
            raise OperationRejected('Неверные поля игровой операции')
        spec.validate(command.arguments)
        return spec

    def prepare(self, name, identity, arguments):
        command = OperationCommand(name, identity, arguments)
        self._spec(command)
        return command

    def check(self, command, context):
        self._spec(command)
        context.check()

    def execute(self, command, context):
        spec = self._spec(command)
        context.check()
        result = spec.perform(command, context)
        if not isinstance(result, OperationResult) or result.command != command:
            raise RuntimeError('Operation returned an unrelated result')
        return result
