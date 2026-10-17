"""Services V2 contract facade; deliberately separate from strict CITYV1 DTO.

No HTTP listener, token verification, daemon startup or bank-status amendment.
The caller provides a trusted authenticated principal plus the existing shared
hub lock and a server-derived live-city predicate. Root integrates the route
and native refresh callbacks separately. Body username must match principal;
body cannot provide an internal owner, allowed flag, price or raw command.
"""
import re
from pathlib import Path

from tio.character_identity import owner_for_slot
from tio.db_transaction import transaction
from tio.services_completion import ServiceRejected, ServicesCompletion
from .service_operations import SERVICE_ACTION_FIELDS, prepare_service, execute_service


ACTION_FIELDS = SERVICE_ACTION_FIELDS


class ServicesV2:
    def __init__(self, path, hub_lock, available, *, helper=None):
        if not callable(available):
            raise ServiceRejected('Нужна серверная проверка доступности города')
        self.path, self.lock, self.available = Path(path), hub_lock, available
        self.helper = ServicesCompletion(path) if helper is None else helper
        if self.helper.path.resolve() != self.path.resolve():
            raise ServiceRejected('Услуги принадлежат другой базе данных')

    @staticmethod
    def _actor(db, principal, slot):
        if not isinstance(principal, str) or not re.fullmatch('[a-z0-9_]{3,32}', principal):
            raise ServiceRejected('Нет авторизованного пользователя')
        if type(slot) is not int or not 1 <= slot <= 5:
            raise ServiceRejected('Слот персонажа должен быть 1–5')
        if not db.execute('SELECT 1 FROM accounts WHERE login=?', (principal,)).fetchone():
            raise ServiceRejected('Пользователь не зарегистрирован')
        return owner_for_slot(db, principal, slot)

    def status(self, principal, slot):
        with self.lock, transaction(self.path) as db:
            owner = self._actor(db, principal, slot)
            allowed = self.available(db, principal, slot, owner) is True
            return dict(version=2, services=self.helper.status(owner, allowed=allowed))

    def action(self, principal, payload):
        if not isinstance(payload, dict):
            raise ServiceRejected('Некорректный запрос услуги')
        action = payload.get('action')
        if not isinstance(action, str) or action not in ACTION_FIELDS:
            raise ServiceRejected('Услуга недоступна')
        if set(payload) != {'username', 'slot', 'action', 'requestId'} | ACTION_FIELDS[action]:
            raise ServiceRejected('Неверные поля запроса услуги')
        if payload['username'] != principal:
            raise ServiceRejected('Нельзя действовать от другого пользователя')
        with self.lock, transaction(self.path) as db:
            owner = self._actor(db, principal, payload['slot'])
            allowed = self.available(db, principal, payload['slot'], owner) is True
            command = prepare_service(action, payload['requestId'], {key: payload[key] for key in ACTION_FIELDS[action]})
            outcome = execute_service(command, db=db, path=self.path, helper=self.helper,
                                      owner=owner, allowed=allowed)
            result = outcome.as_dict()
            # Safe DTO is produced inside the same atomic unit. Projection
            # failure rolls back charge/state/receipt instead of half-commit.
            status = dict(version=2, services=self.helper.status(owner, allowed=allowed))
            return dict(status=status, receipt=result['receipt'], replayed=result['replayed'])
