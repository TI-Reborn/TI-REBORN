"""Shared FIFO requests for native checkpoint defense and raid assistance.

The hub owns one RLock, sessions and battle lifecycle. Queues contain frozen
account-bound selections, never sockets, money holds or durable battle state.
Root MineArena supplies mine_instances/mine_seat/join_mine/mine_unit.
"""
from contextlib import closing
from dataclasses import dataclass
import json
import os
from pathlib import Path

from tio.character_identity import auth_account
from tio.db_transaction import connect
from tio.matchmaking import SearchTicket, SurvivalQueue
from tio.mine_claims import MineClaimsStore
from tio.owned_pets import OwnedPetStore
from tio.protocol.mine_requests import QueueMember, cancel_notice, queue_change
from tio.protocol.mining import player_state
from tio.protocol.system_message import encode_shop_error

POLICY = json.loads((Path(__file__).resolve().parents[1] / 'config/mine_requests.json').read_text(encoding='utf-8'))
if (type(POLICY['per_city_role_limit']) is not int or not 1 <= POLICY['per_city_role_limit'] <= 128
        or type(POLICY['total_limit']) is not int or not POLICY['per_city_role_limit'] <= POLICY['total_limit'] <= 256):
    raise ValueError('Invalid mine request queue policy')


def database_key(path):
    return os.path.normcase(str(Path(path).resolve()))


def real_account(path, account):
    """Canonical login, restricted to an actually persisted owned character."""
    human = auth_account(path, account)
    with closing(connect(path)) as db:
        if not db.execute('SELECT 1 FROM characters WHERE account=? AND slot=1', (account,)).fetchone():
            raise ValueError('Для заявки требуется собственный сохранённый персонаж')
    return human


def revalidate_owned(path, account, ticket):
    """Read fresh HP, selection, levels and inventory before any admission."""
    if (not isinstance(ticket, SearchTicket) or ticket.mode != 0 or not ticket.actors
            or not isinstance(ticket.actors, tuple) or not isinstance(ticket.levels, tuple)):
        raise ValueError('Некорректный сохранённый отряд шахты')
    real_account(path, account)
    roster = OwnedPetStore(path).list(account)
    current = SurvivalQueue(group_wait=0).join(ticket.character_id, roster)
    if (current.actors, current.levels) != (ticket.actors, ticket.levels):
        raise ValueError('Отряд изменился: отмените заявку и подайте её заново')
    return ticket


@dataclass(frozen=True)
class MineRequest:
    owner: int
    town: int
    role: int
    ticket: SearchTicket
    database: str
    account: str
    human: str
    sequence: int


class MineRequestRejected(ValueError):
    """An invalidated applicant, distinct from a battle/storage failure."""


class MineRequests:
    def init_mine_requests(self):
        self.mine_requests = {}
        self._mine_request_sequence = 0
        self._mine_last_role = {}
        self._mine_busy_probe = None

    def mine_waiting(self, owner):
        # While holding the hub lock, admission checks every OTHER busy reason
        # through the hub's ordinary busy() API without rejecting its own queue.
        return owner in self.mine_requests and owner != self._mine_busy_probe

    def _mine_identity(self, owner):
        if owner in getattr(self, 'offline', {}) or owner not in self.players:
            raise ValueError('Игрок отключён от сервера')
        session = self.players[owner]
        return session, database_key(session.database), real_account(session.database, session.account)

    def _mine_busy(self, owner, session):
        previous = self._mine_busy_probe
        self._mine_busy_probe = owner
        try:
            if self.busy(session):
                return True
        finally:
            self._mine_busy_probe = previous
        survival = getattr(session, 'survival', None)
        if survival is not None and survival.searching(session.probe_character_id):
            return True
        arena = getattr(session, 'arena', None)
        return bool(arena and any(session.probe_character_id in r.members for r in arena.rooms.snapshot()))

    def _mine_validate(self, owner, town, ticket, role, *, queued=None):
        from tio.crystal_market import POLICY as market_policy
        from tio.locations import MINE_LOCATIONS
        from tio.mining import band
        if type(town) is not int or town not in MINE_LOCATIONS or type(role) is not int or role not in (2, 3):
            raise ValueError('Некорректная роль или блокпост шахты')
        if not isinstance(ticket, SearchTicket) or ticket.character_id != owner:
            raise ValueError('Отряд заявки принадлежит другому игроку')
        session, database, human = self._mine_identity(owner)
        if queued is not None and (database, session.account, human) != (queued.database, queued.account, queued.human):
            raise ValueError('Персонаж заявки изменился')
        if not session.locations or session.locations.current(session.account) != town:
            raise ValueError('Для заявки перейдите к соответствующему блокпосту шахты')
        if self._mine_busy(owner, session):
            raise ValueError('Сначала завершите текущий бой или поиск')
        for other, other_session in self.players.items():
            if other == owner or database_key(other_session.database) != database:
                continue
            if auth_account(other_session.database, other_session.account) == human and (
                    other in self.mine_requests or self._mine_busy(other, other_session)):
                raise ValueError('Другой персонаж этого аккаунта уже занят')
        revalidate_owned(session.database, session.account, ticket)
        if band(ticket.levels) != tuple(market_policy['bands'][MINE_LOCATIONS[town]['band']]):
            raise ValueError('Отряд не соответствует диапазону уровней шахты')
        if role == 3:
            claims = MineClaimsStore(session.database)
            claims.authorize_defender(session.account, claims.freeze(town))
        return session, database, human

    def enqueue_mine_request(self, owner, town, ticket, role):
        with self.lock:
            old = self.mine_requests.get(owner)
            session, database, human = self._mine_validate(owner, town, ticket, role, queued=old)
            if old is not None:
                if (old.town, old.role, old.ticket.actors, old.ticket.levels) != (town, role, ticket.actors, ticket.levels):
                    raise ValueError('Сначала отмените предыдущую заявку шахты')
                self.put(owner, *self.queue_packets(owner, town))
                return old
            if len(self.mine_requests) >= POLICY['total_limit'] or sum(
                    r.town == town and r.role == role and r.database == database
                    for r in self.mine_requests.values()) >= POLICY['per_city_role_limit']:
                raise ValueError('Очередь шахты заполнена')
            self._mine_request_sequence += 1
            request = MineRequest(owner, town, role, ticket, database, session.account, human,
                                  self._mine_request_sequence)
            self.mine_requests[owner] = request
            self._mine_last_role[owner] = role
            self._notify_mine_requests(town, database)
            return request

    def cancel_mine_request(self, owner):
        with self.lock:
            request = self.mine_requests.pop(owner, None)
            session = self.players.get(owner)
            if session is not None and owner not in getattr(self, 'offline', {}):
                self.put(owner, cancel_notice(session.probe_character_id),
                         queue_change((QueueMember(session.probe_character_id,
                                                   request.role if request else self._mine_last_role.get(owner, 2), -1),)))
            if request is not None:
                self._notify_mine_requests(request.town, request.database)
            return request is not None

    def _mine_rows(self, town, database):
        return sorted((r for r in self.mine_requests.values() if r.town == town and r.database == database),
                      key=lambda r: r.sequence)

    def _mine_counts(self, town, database):
        counts = {1: 0, 2: 0, 3: 0}
        for battle in self.mine_instances(town):
            persistence = battle['field'].combat.persistence
            if not persistence or database_key(next(iter(persistence.values()))[0]) != database:
                continue
            for owner in battle['mine_active']:
                role = battle['field'].mining.roles[owner]
                if role in counts:
                    counts[role] += 1
        return counts

    def queue_packets(self, owner, town):
        with self.lock:
            session, database, _ = self._mine_identity(owner)
            rows = self._mine_rows(town, database)
            positions = {2: 0, 3: 0}; members = []
            for row in rows:
                identity = session.probe_character_id if row.owner == owner else row.owner
                # Every recipient has its own character-ID namespace. Foreign
                # owners remain server IDs; only the own row is remapped.
                if identity == session.probe_character_id and row.owner != owner:
                    raise ValueError('Коллизия идентификаторов очереди шахты')
                members.append(QueueMember(identity, row.role, positions[row.role]))
                positions[row.role] += 1
            if owner not in {r.owner for r in rows}:
                members.append(QueueMember(session.probe_character_id, self._mine_last_role.get(owner, 2), -1))
            counts = self._mine_counts(town, database)
            can_defend = False
            try:
                claims = MineClaimsStore(session.database)
                claims.authorize_defender(session.account, claims.freeze(town))
                can_defend = True
            except ValueError:
                pass
            return (queue_change(members), player_state(can_raid=True, can_defend=can_defend,
                miners=counts[1], defenders=counts[3], raiders=counts[2],
                waiting_defenders=positions[3], waiting_raiders=positions[2]))

    def _notify_mine_requests(self, town, database):
        for request in tuple(self._mine_rows(town, database)):
            if request.owner in self.players and request.owner not in getattr(self, 'offline', {}):
                self.put(request.owner, *self.queue_packets(request.owner, town))

    def _mine_admission(self, battle, request):
        try:
            self._mine_check_admission(battle, request)
        except ValueError as exc:
            raise MineRequestRejected(str(exc)) from exc

    def _mine_check_admission(self, battle, request):
        session, database, human = self._mine_validate(request.owner, request.town,
                                                      request.ticket, request.role, queued=request)
        persistence = battle['field'].combat.persistence
        if not persistence or database != database_key(next(iter(persistence.values()))[0]):
            raise ValueError('Шахта должна использовать одну серверную базу')
        if any(auth_account(session.database, record[0]) == human for record in battle['reward_roster'].values()):
            raise ValueError('Повторный вход персонажем того же аккаунта запрещён')
        if request.role == 3:
            MineClaimsStore(session.database).authorize_defender(session.account, battle['mine_claim'])

    def try_mine_requests(self, battle):
        """Admit eligible FIFO entries; consume only after journal commit.

        Returns admitted owner IDs. Invalidated entries get native cancel and a
        private error. Storage/journal failures propagate and preserve the entry.
        The caller routes those failures through its normal battle failure policy.
        """
        with self.lock:
            if battle.get('kind') != 'mine' or battle.get('finished') or battle.get('faulted'):
                return ()
            persistence = battle['field'].combat.persistence
            if not persistence:
                return ()
            database = database_key(next(iter(persistence.values()))[0])
            town = battle['city_id']; admitted = []
            for role in (3, 2):
                candidates = tuple(r for r in self._mine_rows(town, database) if r.role == role)
                for request in candidates:
                    roles = battle['field'].mining.roles
                    raiders = sum(roles[o] == 2 for o in battle['mine_active'])
                    needs_help = role == 3 or raiders >= 1
                    if (needs_help and battle.get('mine_help', {}).get(role) is not True
                            or not self.mine_seat(battle, role)):
                        break
                    try:
                        self._mine_admission(battle, request)
                        with self.mine_unit(battle):
                            # Fresh saves and frozen-claim checks participate
                            # in the same transaction as battlefield admission.
                            self._mine_admission(battle, request)
                            self.join_mine(battle, request.owner, request.ticket, role)
                            if needs_help:
                                battle.setdefault('mine_help', {})[role] = False
                    except MineRequestRejected as exc:
                        self.cancel_mine_request(request.owner)
                        self.put(request.owner, encode_shop_error(str(exc)))
                        continue
                    # Queue state has no funds and is deliberately not journaled.
                    # Removal waits until the durable battle unit has committed.
                    self.cancel_mine_request(request.owner)
                    admitted.append(request.owner)
            return tuple(admitted)
