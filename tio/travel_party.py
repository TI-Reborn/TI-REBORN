"""Durable, consent-based travel groups for distinct authenticated players.

Save owners are fixed while joined: another character slot of the same login
cannot replace a participant. This store never edits accounts, rosters, saves,
wallets or locations. Shared travel and combat remain the service's responsibility.
"""
from contextlib import closing
from pathlib import Path
import time

from . import character_identity
from .cities import CITIES
from .db_transaction import connect, transaction
from .protocol.pet_info import decode_pet_info


STATES = frozenset(('city', 'travelling', 'at_target', 'loading', 'battle'))
MAX_MEMBERS = 4


class PartyStore:
    def __init__(self, path, *, clock=time.time, invitation_ttl=120):
        if not 0 < invitation_ttl <= 3600:
            raise ValueError('Срок приглашения должен быть от 1 до 3600 секунд')
        self.path = Path(path)
        self.clock = clock
        self.invitation_ttl = invitation_ttl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with transaction(self.path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS travel_party_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT, leader TEXT NOT NULL,
                town_id INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN
                ('city','travelling','at_target','loading','battle')),
                revision INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS travel_party_members (
                party_id INTEGER NOT NULL, owner TEXT PRIMARY KEY,
                login TEXT NOT NULL UNIQUE, ready INTEGER NOT NULL DEFAULT 0
                CHECK(ready IN (0,1)), online INTEGER NOT NULL DEFAULT 1
                CHECK(online IN (0,1)), joined_at REAL NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS travel_party_selected (
                owner TEXT NOT NULL, actor_id INTEGER NOT NULL,
                position INTEGER NOT NULL CHECK(position BETWEEN 0 AND 1),
                PRIMARY KEY(owner,actor_id), UNIQUE(owner,position))''')
            db.execute('''CREATE TABLE IF NOT EXISTS travel_party_invitations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, party_id INTEGER NOT NULL,
                leader TEXT NOT NULL, target_owner TEXT NOT NULL,
                target_login TEXT NOT NULL, expires_at REAL NOT NULL,
                UNIQUE(party_id,target_login))''')
            db.execute('''CREATE TABLE IF NOT EXISTS travel_party_disconnects (
                owner TEXT PRIMARY KEY, since REAL NOT NULL)''')

    @staticmethod
    def _has_table(db, name):
        return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                               (name,)).fetchone())

    def _identity(self, db, owner):
        login = character_identity.auth_account(self.path, owner, connection=db)
        character_identity.alias(login, 1)
        if not self._has_table(db, 'accounts') or not db.execute(
                'SELECT 1 FROM accounts WHERE login=?', (login,)).fetchone():
            raise ValueError('Нужна зарегистрированная учётная запись игрока')
        if not self._has_table(db, 'characters') or not db.execute(
                'SELECT 1 FROM characters WHERE account=? AND slot=1', (owner,)).fetchone():
            raise ValueError('Нужен сохранённый персонаж этой учётной записи')
        return login

    def _city(self, db, owner):
        if self._has_table(db, 'map_journeys') and db.execute(
                'SELECT 1 FROM map_journeys WHERE account=?', (owner,)).fetchone():
            raise ValueError('Сначала остановитесь и войдите в город')
        row = db.execute('SELECT town_id FROM character_locations WHERE account=?',
                         (owner,)).fetchone() if self._has_table(db, 'character_locations') else None
        # LocationStore gives a new saved character Reservation by default.
        town = 3 if row is None else row[0]
        if town not in CITIES:
            raise ValueError('Группу можно собирать только в городе')
        return town

    @staticmethod
    def _membership(db, owner):
        return db.execute('SELECT party_id FROM travel_party_members WHERE owner=?',
                          (owner,)).fetchone()

    def _room(self, db, owner, *, leader=False, city=False):
        self._identity(db, owner)
        member = self._membership(db, owner)
        if member is None:
            raise ValueError('Вы не состоите в группе этим персонажем')
        room = self._snapshot(db, member[0])
        if room is None:
            raise ValueError('Группа больше не существует')
        if leader and room['leader'] != owner:
            raise ValueError('Это действие доступно только лидеру группы')
        if city and room['state'] != 'city':
            raise ValueError('Изменять группу можно только до выхода из города')
        if city:
            self._reject_frozen(db, room['id'])
        return room

    def _reject_frozen(self, db, party_id):
        if self._has_table(db, 'pve_contract_instances') and db.execute(
                "SELECT 1 FROM pve_contract_instances WHERE party_id=? AND "
                "(state='active' OR state IN ('accepted','travelling','arrived') AND expires_at>?)",
                (str(party_id), self.clock())).fetchone():
            raise ValueError('Сначала отмените контракт, чтобы изменить состав или бойцов')

    def _unjoined(self, db, login):
        if db.execute('SELECT 1 FROM travel_party_members WHERE login=?', (login,)).fetchone():
            raise ValueError('Учётная запись уже состоит в группе; сначала выйдите из неё')

    def _selected(self, db, owner, actor_ids, *, automatic=False):
        if not self._has_table(db, 'owned_pets'):
            raise ValueError('У персонажа нет сохранённых бойцов')
        ids = tuple(actor_ids)
        rows = db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=? ORDER BY pet_id',
                          (owner,)).fetchall()
        pets = {}
        for identity, human, packet in rows:
            pet = decode_pet_info(bytes(packet), human_equipment=bool(human))
            if pet.fields['0x8c43eb'] != identity:
                raise ValueError('Идентификатор сохранённого бойца повреждён')
            pets[identity] = pet
        if automatic and not ids:
            alive = [identity for identity, pet in pets.items()
                     if pet.fields['0x8c4ab1'] > 0 and pet.fields['0x8c44a6'] != 4]
            active = [identity for identity in alive if pets[identity].fields['0x8c44a6'] in (1, 2, 3)]
            ids = tuple((active or alive)[:2])
        if not 1 <= len(ids) <= 2 or any(type(identity) is not int or identity <= 0 for identity in ids):
            raise ValueError('Выберите одного или двух бойцов')
        if len(set(ids)) != len(ids):
            raise ValueError('Один боец не может занимать два места')
        for identity in ids:
            pet = pets.get(identity)
            if pet is None:
                raise ValueError('Боец не принадлежит выбранному персонажу')
            if pet.fields['0x8c4ab1'] <= 0 or pet.fields['0x8c44a6'] == 4:
                raise ValueError('Боец должен быть живым и пригодным к бою')
        return ids

    @staticmethod
    def _save_selection(db, owner, ids):
        db.execute('DELETE FROM travel_party_selected WHERE owner=?', (owner,))
        db.executemany('INSERT INTO travel_party_selected VALUES (?,?,?)',
                       ((owner, identity, position) for position, identity in enumerate(ids)))

    @staticmethod
    def _changed(db, party_id, *, reset_ready=False):
        if reset_ready:
            db.execute('UPDATE travel_party_members SET ready=0 WHERE party_id=?', (party_id,))
        db.execute('UPDATE travel_party_groups SET revision=revision+1 WHERE id=?', (party_id,))

    @staticmethod
    def _snapshot(db, party_id):
        row = db.execute('SELECT id,leader,town_id,state,revision FROM travel_party_groups WHERE id=?',
                         (party_id,)).fetchone()
        if row is None:
            return None
        result = dict(zip(('id', 'leader', 'town_id', 'state', 'revision'), row))
        result['members'] = []
        for owner,login,ready,online,actor in db.execute(
                '''SELECT m.owner,m.login,m.ready,m.online,s.actor_id
                   FROM travel_party_members m LEFT JOIN travel_party_selected s ON s.owner=m.owner
                   WHERE m.party_id=? ORDER BY m.joined_at,m.owner,s.position''', (party_id,)):
            if not result['members'] or result['members'][-1]['owner']!=owner:
                result['members'].append(dict(owner=owner,login=login,ready=bool(ready),online=bool(online),selected=()))
            if actor is not None:
                member=result['members'][-1];member['selected']+= (actor,)
        return result

    def snapshot(self, party_id, connection=None):
        """Internal consistent snapshot; callers can pass their gameplay transaction."""
        if connection is not None:
            return self._snapshot(connection, party_id)
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN')
            return self._snapshot(db, party_id)

    def _info(self, db, owner):
        self._identity(db, owner)
        row = self._membership(db, owner)
        return None if row is None else self._snapshot(db, row[0])

    def info(self, owner, connection=None):
        if connection is not None:return self._info(connection, owner)
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN')
            return self._info(db, owner)

    def blocked_login(self, login):
        """A login cannot switch save owners while any of its slots is grouped."""
        character_identity.alias(login, 1)
        with closing(connect(self.path)) as db:
            return bool(db.execute('SELECT 1 FROM travel_party_members WHERE login=?', (login,)).fetchone())

    def validate_departure(self, party_id, connection=None, *, solo=False):
        """Revalidate city consent and saved fighters under the route writer's lock."""
        if connection is None:
            with transaction(self.path) as db:
                return self.validate_departure(party_id, db, solo=solo)
        room = self._snapshot(connection, party_id)
        if room is None or room['state'] != 'city':
            raise ValueError('Группа должна находиться в городе перед выходом')
        if not (1 if solo else 2) <= len(room['members']) <= MAX_MEMBERS:
            raise ValueError('Для выхода нужны от одного до четырёх игроков')
        if not all(member['online'] and member['ready'] for member in room['members']):
            raise ValueError('Все участники должны быть в сети и подтвердить готовность')
        for member in room['members']:
            if self._identity(connection, member['owner']) != member['login']:
                raise ValueError('Участник группы больше не принадлежит учётной записи')
            if self._city(connection, member['owner']) != room['town_id']:
                raise ValueError('Все участники должны находиться в городе группы')
            self._selected(connection, member['owner'], member['selected'])
        return room

    def create(self, owner, selected=()):
        with transaction(self.path) as db:
            login = self._identity(db, owner)
            self._unjoined(db, login)
            town = self._city(db, owner)
            ids = self._selected(db, owner, selected, automatic=True)
            now = self.clock()
            party_id = db.execute('INSERT INTO travel_party_groups(leader,town_id,state,created_at) VALUES (?,?,?,?)',
                                  (owner, town, 'city', now)).lastrowid
            db.execute('INSERT INTO travel_party_members(party_id,owner,login,joined_at) VALUES (?,?,?,?)',
                       (party_id, owner, login, now))
            self._save_selection(db, owner, ids)
            return self._snapshot(db, party_id)

    @staticmethod
    def _invitation(row):
        return dict(zip(('id', 'party_id', 'leader', 'target_owner', 'target_login', 'expires_at'), row))

    def invite(self, owner, target_owner):
        with transaction(self.path) as db:
            room = self._room(db, owner, leader=True, city=True)
            login = self._identity(db, target_owner)
            self._unjoined(db, login)
            if self._city(db, owner) != room['town_id'] or self._city(db, target_owner) != room['town_id']:
                raise ValueError('Все участники должны находиться в одном городе')
            if len(room['members']) >= MAX_MEMBERS:
                raise ValueError('В группе уже четыре игрока')
            expires = self.clock() + self.invitation_ttl
            db.execute('''INSERT INTO travel_party_invitations(party_id,leader,target_owner,target_login,expires_at)
                          VALUES (?,?,?,?,?) ON CONFLICT(party_id,target_login) DO UPDATE SET
                          leader=excluded.leader,target_owner=excluded.target_owner,expires_at=excluded.expires_at''',
                       (room['id'], owner, target_owner, login, expires))
            return self._invitation(db.execute('SELECT * FROM travel_party_invitations WHERE party_id=? AND target_login=?',
                                              (room['id'], login)).fetchone())

    def invitations(self, target_owner):
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN')
            self._identity(db, target_owner)
            return tuple(self._invitation(row) for row in db.execute('''
                SELECT i.* FROM travel_party_invitations i JOIN travel_party_groups p ON p.id=i.party_id
                WHERE i.target_owner=? AND i.expires_at>? AND p.state='city' AND p.leader=i.leader ORDER BY i.id''',
                (target_owner, self.clock())).fetchall())

    def accept(self, target_owner, invitation_id, selected=()):
        with transaction(self.path) as db:
            login = self._identity(db, target_owner)
            self._unjoined(db, login)
            row = db.execute('SELECT * FROM travel_party_invitations WHERE id=?', (invitation_id,)).fetchone()
            if row is None or row[3] != target_owner or row[4] != login:
                raise ValueError('Это приглашение не адресовано выбранному персонажу')
            invitation = self._invitation(row)
            room = self._snapshot(db, invitation['party_id'])
            if invitation['expires_at'] <= self.clock():
                raise ValueError('Срок приглашения истёк')
            if room is None or room['state'] != 'city' or room['leader'] != invitation['leader']:
                raise ValueError('Группа изменилась; нужно новое приглашение')
            self._reject_frozen(db, room['id'])
            if len(room['members']) >= MAX_MEMBERS:
                raise ValueError('В группе уже четыре игрока')
            if any(self._city(db, member['owner']) != room['town_id'] for member in room['members']) or self._city(db, target_owner) != room['town_id']:
                raise ValueError('Все участники должны находиться в одном городе')
            ids = self._selected(db, target_owner, selected, automatic=True)
            db.execute('INSERT INTO travel_party_members(party_id,owner,login,joined_at) VALUES (?,?,?,?)',
                       (room['id'], target_owner, login, self.clock()))
            self._save_selection(db, target_owner, ids)
            db.execute('DELETE FROM travel_party_invitations WHERE target_login=?', (login,))
            self._changed(db, room['id'], reset_ready=True)
            return self._snapshot(db, room['id'])

    def decline(self, target_owner, invitation_id):
        with transaction(self.path) as db:
            self._identity(db, target_owner)
            row = db.execute('SELECT target_owner FROM travel_party_invitations WHERE id=?',
                             (invitation_id,)).fetchone()
            if row is None:
                return False
            if row[0] != target_owner:
                raise ValueError('Это приглашение адресовано другому персонажу')
            db.execute('DELETE FROM travel_party_invitations WHERE id=?', (invitation_id,))
            return True

    def select(self, owner, actor_ids):
        with transaction(self.path) as db:
            room = self._room(db, owner, city=True)
            ids = self._selected(db, owner, actor_ids)
            self._save_selection(db, owner, ids)
            self._changed(db, room['id'], reset_ready=True)
            return self._snapshot(db, room['id'])

    def ready(self, owner, value):
        if type(value) is not bool:
            raise ValueError('Готовность должна быть логическим значением')
        with transaction(self.path) as db:
            room = self._room(db, owner)
            if room['state'] not in ('city', 'at_target'):
                raise ValueError('Готовность можно подтвердить в городе или у цели')
            member = next(member for member in room['members'] if member['owner'] == owner)
            if value:
                if not member['online']:
                    raise ValueError('Игрок должен быть подключён')
                self._selected(db, owner, member['selected'])
                if room['state'] == 'city' and self._city(db, owner) != room['town_id']:
                    raise ValueError('Вернитесь в город группы')
            if member['ready'] != value:
                db.execute('UPDATE travel_party_members SET ready=? WHERE owner=?', (int(value), owner))
                self._changed(db, room['id'])
            return self._snapshot(db, room['id'])

    def transfer(self, owner, target_owner):
        with transaction(self.path) as db:
            room = self._room(db, owner, leader=True, city=True)
            if target_owner == owner or not any(member['owner'] == target_owner for member in room['members']):
                raise ValueError('Выберите другого участника своей группы')
            db.execute('UPDATE travel_party_groups SET leader=? WHERE id=?', (target_owner, room['id']))
            db.execute('DELETE FROM travel_party_invitations WHERE party_id=?', (room['id'],))
            self._changed(db, room['id'], reset_ready=True)
            return self._snapshot(db, room['id'])

    @staticmethod
    def _delete_room(db, party_id):
        db.execute('DELETE FROM travel_party_disconnects WHERE owner IN (SELECT owner FROM travel_party_members WHERE party_id=?)',
                   (party_id,))
        db.execute('DELETE FROM travel_party_selected WHERE owner IN (SELECT owner FROM travel_party_members WHERE party_id=?)',
                   (party_id,))
        db.execute('DELETE FROM travel_party_members WHERE party_id=?', (party_id,))
        db.execute('DELETE FROM travel_party_invitations WHERE party_id=?', (party_id,))
        db.execute('DELETE FROM travel_party_groups WHERE id=?', (party_id,))

    def leave(self, owner):
        with transaction(self.path) as db:
            room = self._room(db, owner, city=True)
            if room['leader'] == owner:
                if len(room['members']) > 1:
                    raise ValueError('Перед выходом передайте лидерство или распустите группу')
                self._delete_room(db, room['id'])
                return None
            db.execute('DELETE FROM travel_party_selected WHERE owner=?', (owner,))
            db.execute('DELETE FROM travel_party_disconnects WHERE owner=?', (owner,))
            db.execute('DELETE FROM travel_party_members WHERE owner=?', (owner,))
            self._changed(db, room['id'], reset_ready=True)
            return self._snapshot(db, room['id'])

    def kick(self, owner, target_owner):
        with transaction(self.path) as db:
            room = self._room(db, owner, leader=True, city=True)
            if target_owner == owner or not any(member['owner'] == target_owner for member in room['members']):
                raise ValueError('Выберите другого участника своей группы')
            db.execute('DELETE FROM travel_party_selected WHERE owner=?', (target_owner,))
            db.execute('DELETE FROM travel_party_disconnects WHERE owner=?', (target_owner,))
            db.execute('DELETE FROM travel_party_members WHERE owner=?', (target_owner,))
            self._changed(db, room['id'], reset_ready=True)
            return self._snapshot(db, room['id'])

    def disband(self, owner):
        with transaction(self.path) as db:
            room = self._room(db, owner, leader=True, city=True)
            self._delete_room(db, room['id'])
            return None

    def set_online(self, owner, value):
        if type(value) is not bool:
            raise ValueError('Статус подключения должен быть логическим значением')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN')
            room=self.info(owner,connection=db)
            if room is None:return None
            member=next(member for member in room['members'] if member['owner']==owner)
            disconnected=db.execute('SELECT 1 FROM travel_party_disconnects WHERE owner=?',(owner,)).fetchone() is not None
            if member['online']==value and disconnected== (not value):return room
        # Revalidate membership, online status and disconnect bookkeeping under
        # the writer lock, including when another session changed them meanwhile.
        with transaction(self.path) as db:
            self._identity(db, owner)
            row = self._membership(db, owner)
            if row is None:
                return None
            room = self._snapshot(db, row[0])
            member = next(member for member in room['members'] if member['owner'] == owner)
            if member['online'] != value:
                db.execute('UPDATE travel_party_members SET online=?,ready=0 WHERE owner=?', (int(value), owner))
                self._changed(db, room['id'], reset_ready=not value)
            if value:
                db.execute('DELETE FROM travel_party_disconnects WHERE owner=?', (owner,))
            else:
                db.execute('INSERT OR IGNORE INTO travel_party_disconnects VALUES (?,?)', (owner, self.clock()))
            return self._snapshot(db, room['id'])

    def reset_online(self):
        """Runtime startup hook: persisted membership survives, connection consent does not."""
        with transaction(self.path) as db:
            groups = [row[0] for row in db.execute('SELECT DISTINCT party_id FROM travel_party_members WHERE online=1 OR ready=1')]
            db.execute('UPDATE travel_party_members SET online=0,ready=0')
            db.execute('INSERT OR IGNORE INTO travel_party_disconnects SELECT owner,? FROM travel_party_members', (self.clock(),))
            for party_id in groups:
                self._changed(db, party_id)

    def _replacement_leader(self, db, room, grace_seconds):
        if room is None or room['state'] in ('loading','battle'):return None
        leader=next(member for member in room['members'] if member['owner']==room['leader'])
        row=db.execute('SELECT since FROM travel_party_disconnects WHERE owner=?',(room['leader'],)).fetchone()
        candidates=[member for member in room['members'] if member['online']]
        if leader['online'] or row is None or self.clock()-row[0]<grace_seconds or not candidates:return None
        return candidates[0]['owner']

    def recover_leader(self, party_id, *, grace_seconds=60):
        """Allow a connected member to return a stranded group after a grace period."""
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN')
            room=self._snapshot(db,party_id)
            if self._replacement_leader(db,room,grace_seconds) is None:return room
        with transaction(self.path) as db:
            room=self._snapshot(db,party_id)
            replacement=self._replacement_leader(db,room,grace_seconds)
            if replacement is None:return room
            db.execute('UPDATE travel_party_groups SET leader=? WHERE id=?', (replacement, party_id))
            db.execute('DELETE FROM travel_party_invitations WHERE party_id=?', (party_id,))
            self._changed(db, party_id, reset_ready=True)
            return self._snapshot(db, party_id)

    def change_state(self, party_id, state, expected_state, connection=None):
        """Internal compare-and-set; domain services own transition preconditions."""
        if state not in STATES or expected_state not in STATES:
            raise ValueError('Неизвестное состояние группы')
        if connection is None:
            with transaction(self.path) as db:
                return self.change_state(party_id, state, expected_state, db)
        changed = connection.execute('UPDATE travel_party_groups SET state=?,revision=revision+1 WHERE id=? AND state=?',
                                     (state, party_id, expected_state)).rowcount
        if changed != 1:
            raise ValueError('Состояние группы изменилось')
        if state == 'city':
            connection.execute('UPDATE travel_party_members SET ready=0 WHERE party_id=?', (party_id,))
        return self._snapshot(connection, party_id)
