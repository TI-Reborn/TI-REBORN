"""Authoritative city services; joins the caller's shared SQLite transaction.

The caller owns authentication and the hub lock and must derive `allowed` from
the live session, battle/lobby/result retention and city availability. Browser
input is never permitted to select the internal save owner or this gate.
Durable travel/prison/checkpoint/city guards are checked again in this module.
No login migration or constructor removes actors. Due dismissals require an
explicit server tick under the same hub lock. Avatar offers fail closed until a
verified exact original catalog is configured; manual approximate prices are
not a production catalog.
"""
from dataclasses import replace
import json
from pathlib import Path
import re
import sqlite3
import time

from .db_transaction import transaction
from .owned_pets import OwnedPetStore
from .protocol.character_create import decode_character_create, encode_character_create
from .protocol.hire import encode_pet_deleted
from .protocol.pet_info import decode_pet_info, encode_pet_info
from .protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from .item_ids import next_item_id


class ServiceRejected(ValueError):
    pass


def _exists(db, name):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _u32(value):
    if type(value) is not int or not 1 <= value <= 0xffffffff:
        raise ServiceRejected('Некорректный ID бойца/аватара')
    return value


class ServicesCompletion:
    def __init__(self, path, *, config=None, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        policy_path = Path(__file__).resolve().parents[1] / 'config/services_completion.json'
        self.policy = json.loads(policy_path.read_text(encoding='utf-8')) if config is None else json.loads(json.dumps(config))
        exact = dict(version=1, rename_main_gold=30, rename_recruit_credits=3000,
                     dismiss_seconds=172800, dog_meat_template=32, dog_meat_count=1)
        if any(type(self.policy.get(k)) is not int or self.policy[k] != v for k, v in exact.items()):
            raise ServiceRejected('Политика услуг отличается от подтверждённого руководства')
        self.offers = self._offers(self.policy.get('avatar_offers'))
        with transaction(self.path) as db:
            statements = (
                '''CREATE TABLE IF NOT EXISTS service_completion_receipts(
                  account TEXT NOT NULL,identity TEXT NOT NULL,action TEXT NOT NULL,
                  request TEXT NOT NULL,receipt TEXT NOT NULL,PRIMARY KEY(account,identity))''',
                '''CREATE TABLE IF NOT EXISTS service_dismissals(
                  account TEXT NOT NULL,pet_id INTEGER NOT NULL,scheduled_at INTEGER NOT NULL,
                  due_at INTEGER NOT NULL,completed_at INTEGER,PRIMARY KEY(account,pet_id))''',
                '''CREATE TABLE IF NOT EXISTS service_retired_pets(
                  account TEXT NOT NULL,pet_id INTEGER NOT NULL,human INTEGER NOT NULL,
                  pet_packet BLOB NOT NULL,inventory_packet BLOB NOT NULL,
                  completed_at INTEGER NOT NULL,PRIMARY KEY(account,pet_id))''',
                '''CREATE TABLE IF NOT EXISTS service_dog_meat_rewards(
                  account TEXT NOT NULL,pet_id INTEGER NOT NULL,claimed_at INTEGER,
                  target_pet_id INTEGER,item_id INTEGER,PRIMARY KEY(account,pet_id))''')
            for sql in statements:
                db.execute(sql)
            for table in ('service_completion_receipts', 'service_retired_pets'):
                for verb in ('UPDATE', 'DELETE'):
                    db.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_no_{verb.lower()}
                      BEFORE {verb} ON {table} BEGIN SELECT RAISE(ABORT,'Service history is immutable'); END''')

    @staticmethod
    def _offers(offers):
        # Approximate manual prices cannot establish original offers/assets.
        # Refuse an invented catalog even if supplied through local config.
        if offers != [] or not isinstance(offers, list):
            raise ServiceRejected('Точный оригинальный каталог аватаров не восстановлен; предложения отключены')
        return {}

    def _now(self):
        value = self.clock()
        if type(value) not in (int, float) or not 0 <= value <= 0x7fffffffffffffff - 172800:
            raise ServiceRejected('Некорректные серверные часы')
        return int(value)

    @staticmethod
    def _owner(db, owner):
        if not isinstance(owner, str) or not owner or len(owner) > 255:
            raise ServiceRejected('Нет авторизованного владельца')
        if not _exists(db, 'characters') or not db.execute('SELECT 1 FROM characters WHERE account=? AND slot=1', (owner,)).fetchone():
            raise ServiceRejected('Нет сохранённого персонажа')
        if not _exists(db, 'wallets') or not db.execute('SELECT 1 FROM wallets WHERE account=?', (owner,)).fetchone():
            raise ServiceRejected('Нет кошелька персонажа')

    @classmethod
    def _gate(cls, db, owner, allowed):
        cls._owner(db, owner)
        if allowed is not True:
            raise ServiceRejected('Городские услуги сейчас недоступны')
        from .cities import CITIES
        town = db.execute('SELECT town_id FROM character_locations WHERE account=?', (owner,)).fetchone() if _exists(db, 'character_locations') else None
        if town is None or town[0] not in (*CITIES, 9):
            raise ServiceRejected('Для услуги нужно находиться в городе')
        for table in ('map_journeys', 'battle_checkpoint_members', 'battle_settlement_jobs'):
            if _exists(db, table) and db.execute(f'SELECT 1 FROM {table} WHERE account=?', (owner,)).fetchone():
                raise ServiceRejected('Дождитесь завершения пути или боя')
        if _exists(db, 'world_prison') and db.execute('SELECT 1 FROM world_prison WHERE account=? AND remaining>0', (owner,)).fetchone():
            raise ServiceRejected('Услуги недоступны в тюрьме')

    @staticmethod
    def _pet(db, owner, pet_id):
        _u32(pet_id)
        row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?', (owner, pet_id)).fetchone()
        if row is None:
            raise ServiceRejected('Боец не принадлежит персонажу')
        if OwnedPetStore.validate(bytes(row[1]), bytes(row[2]), bool(row[0])) != pet_id:
            raise ServiceRejected('Повреждённый ID бойца')
        pet = decode_pet_info(bytes(row[1]), human_equipment=bool(row[0]))
        if (pet.fields['0x8c446f'] in (1, 2, 6)) != bool(row[0]):
            raise ServiceRejected('Повреждённый тип бойца')
        return row, pet

    @staticmethod
    def _dismissable(db, owner, pet_id, row):
        from .roster_rules import require_dismissable, DismissalRejected
        try:
            require_dismissable(pet_id, decode_item_list(bytes(row[2]))[1])
        except DismissalRejected as error:
            raise ServiceRejected(str(error)) from error

    @staticmethod
    def _request(identity, action, arguments):
        if not isinstance(identity, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}', identity):
            raise ServiceRejected('Некорректный ID операции')
        return json.dumps(arguments, sort_keys=True, separators=(',', ':'), ensure_ascii=False)

    @staticmethod
    def _prior(db, owner, identity, action, request):
        row = db.execute('SELECT action,request,receipt FROM service_completion_receipts WHERE account=? AND identity=?', (owner, identity)).fetchone()
        if row is None:
            return None
        if row[:2] != (action, request):
            raise ServiceRejected('ID операции уже использован для другого запроса')
        return {'receipt': json.loads(row[2]), 'replayed': True}

    @staticmethod
    def _finish(db, owner, identity, action, request, *, credits=0, gold=0, **extra):
        receipt = dict(requestId=identity, action=action, creditsDelta=-credits, goldDelta=-gold, **extra)
        db.execute('INSERT INTO service_completion_receipts VALUES (?,?,?,?,?)', (owner, identity, action, request, json.dumps(receipt, sort_keys=True, ensure_ascii=False)))
        return {'receipt': receipt, 'replayed': False}

    @staticmethod
    def _charge(db, owner, credits, gold):
        if db.execute('UPDATE wallets SET credits=credits-?,gold=gold-? WHERE account=? AND credits>=? AND gold>=?', (credits, gold, owner, credits, gold)).rowcount != 1:
            raise ServiceRejected('Недостаточно средств')

    @staticmethod
    def _name(new_name, main):
        if not isinstance(new_name, str):
            raise ServiceRejected('Некорректное имя')
        # Main public-profile/character-selection codec currently requires ASCII.
        pattern = r'[A-Za-z][A-Za-z0-9]{2,15}' if main else r'[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9 ]{2,15}'
        if not re.fullmatch(pattern, new_name) or new_name.endswith(' ') or '  ' in new_name:
            raise ServiceRejected('Имя: 3–16 букв/цифр; главный персонаж — латиница')
        return new_name.encode('ascii' if main else 'cp1251')

    def rename(self, owner, pet_id, new_name, *, identity, allowed=False):
        _u32(pet_id)
        self._name(new_name, pet_id == 1)
        action = 'service_rename'
        request = self._request(identity, action, dict(petId=pet_id, newName=new_name))
        with transaction(self.path) as db:
            self._gate(db, owner, allowed)
            prior = self._prior(db, owner, identity, action, request)
            if prior is not None:
                return prior
            return self._rename(db, owner, pet_id, new_name, identity, request)

    def _rename(self, db, owner, pet_id, new_name, identity, request):
        name = self._name(new_name, pet_id == 1)
        _, pet = self._pet(db, owner, pet_id)
        current = pet.fields['0x8c4489']
        credits = 3000 if pet_id != 1 and current != name else 0
        gold = 0
        if pet_id == 1 and current != name: credits = 3000
        if pet_id == 1:
            name_key = new_name.lower()
            other = db.execute('SELECT account FROM characters WHERE name_key=?', (name_key,)).fetchone()
            if other and other[0] != owner:
                raise ServiceRejected('Имя уже занято')
            raw = db.execute('SELECT request FROM characters WHERE account=? AND slot=1', (owner,)).fetchone()[0]
            create = decode_character_create(bytes(raw))
            updated_request = encode_character_create(replace(create, name_bytes=name))
        self._charge(db, owner, credits, gold)
        packet = encode_pet_info(replace(pet, fields={**pet.fields, '0x8c4489': name}))
        db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?', (packet, owner, pet_id))
        if pet_id == 1:
            db.execute('UPDATE characters SET name=?,name_key=?,request=? WHERE account=? AND slot=1', (name, name_key, updated_request, owner))
        return self._finish(db, owner, identity, 'service_rename', request, credits=credits, gold=gold, petId=pet_id, newName=new_name)

    def rename_command(self, owner, command, *, identity, allowed=False):
        """Original paid GUI sends `/changename <old name> <new name>`.

        Match against the current owned roster, never global name/account input.
        Reject ambiguity; B9/05 free-name packets must not enter this adapter.
        """
        if not isinstance(command, str) or not command.startswith('/changename ') or len(command) > 300:
            raise ServiceRejected('Некорректная команда переименования')
        tail = command[len('/changename '):]
        request = self._request(identity, 'service_rename', dict(command=command))
        with transaction(self.path) as db:
            self._gate(db, owner, allowed)
            prior = self._prior(db, owner, identity, 'service_rename', request)
            if prior is not None:
                return prior
            candidates = []
            for (pet_id,) in db.execute('SELECT pet_id FROM owned_pets WHERE account=? ORDER BY pet_id', (owner,)):
                _, pet = self._pet(db, owner, pet_id)
                old = pet.fields['0x8c4489'].decode('cp1251')
                if tail.startswith(old + ' '):
                    candidates.append((pet_id, tail[len(old) + 1:]))
            if len(candidates) != 1:
                raise ServiceRejected('Имя бойца неизвестно или неоднозначно')
            return self._rename(db, owner, *candidates[0], identity, request)

    def schedule_dismiss(self, owner, pet_id, *, identity, allowed=False):
        _u32(pet_id)
        action = 'service_dismiss'
        request = self._request(identity, action, dict(petId=pet_id))
        with transaction(self.path) as db:
            self._gate(db, owner, allowed)
            prior = self._prior(db, owner, identity, action, request)
            if prior is not None:
                return prior
            row, _ = self._pet(db, owner, pet_id)
            self._dismissable(db, owner, pet_id, row)
            pending = db.execute('SELECT due_at,completed_at FROM service_dismissals WHERE account=? AND pet_id=?', (owner, pet_id)).fetchone()
            if pending and pending[1] is not None:
                raise ServiceRejected('ID уволенного бойца повторно использован')
            due = pending[0] if pending else self._now() + 172800
            if pending is None:
                db.execute('INSERT INTO service_dismissals VALUES (?,?,?,?,NULL)', (owner, pet_id, due - 172800, due))
            return self._finish(db, owner, identity, action, request, petId=pet_id, dismissAt=due)

    def finalize_due(self, owner, *, allowed=False):
        """Called under hub lock after busy/result/online gates; never by login."""
        with transaction(self.path) as db:
            self._gate(db, owner, allowed)
            now = self._now()
            completed, blocked = [], []
            for (pet_id,) in db.execute('SELECT pet_id FROM service_dismissals WHERE account=? AND completed_at IS NULL AND due_at<=? ORDER BY pet_id', (owner, now)).fetchall():
                row, pet = self._pet(db, owner, pet_id)
                try:
                    self._dismissable(db, owner, pet_id, row)
                except ServiceRejected:
                    blocked.append(pet_id)
                    continue
                db.execute('INSERT INTO service_retired_pets VALUES (?,?,?,?,?,?)', (owner, pet_id, *row, now))
                if pet.fields['0x8c446f'] in (3, 4, 5):
                    db.execute('INSERT INTO service_dog_meat_rewards(account,pet_id) VALUES (?,?)', (owner, pet_id))
                db.execute('DELETE FROM owned_pets WHERE account=? AND pet_id=?', (owner, pet_id))
                db.execute('UPDATE service_dismissals SET completed_at=? WHERE account=? AND pet_id=? AND completed_at IS NULL', (now, owner, pet_id))
                completed.append(pet_id)
            return dict(completed=completed, blocked=blocked, packets=tuple(encode_pet_deleted(i) for i in completed))

    def due_owners(self, *, limit=100):
        """Internal worker hints only; every owner still needs hub/live gates."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ServiceRejected('Некорректный лимит очереди увольнения')
        with transaction(self.path) as db:
            return tuple(row[0] for row in db.execute('''SELECT account FROM service_dismissals
                WHERE completed_at IS NULL AND due_at<=? GROUP BY account
                ORDER BY MIN(due_at),account LIMIT ?''', (self._now(), limit)))

    def claim_dogmeat(self, owner, dismissed_pet_id, target_pet_id, *, identity, allowed=False):
        _u32(dismissed_pet_id)
        _u32(target_pet_id)
        action = 'service_claim_dogmeat'
        request = self._request(identity, action, dict(dismissedPetId=dismissed_pet_id, petId=target_pet_id))
        with transaction(self.path) as db:
            self._gate(db, owner, allowed)
            prior = self._prior(db, owner, identity, action, request)
            if prior is not None:
                return prior
            row, _ = self._pet(db, owner, target_pet_id)
            reward = db.execute('SELECT claimed_at FROM service_dog_meat_rewards WHERE account=? AND pet_id=?', (owner, dismissed_pet_id)).fetchone()
            if reward is None or reward[0] is not None:
                raise ServiceRejected('Подарок отсутствует или уже получен')
            owner_id, items, unknown = decode_item_list(bytes(row[2]))
            db.execute('CREATE TABLE IF NOT EXISTS item_sequences(account TEXT PRIMARY KEY,next_id INTEGER NOT NULL)')
            highest = next_item_id(db, owner) - 1
            if highest >= 0xffffffff:
                raise ServiceRejected('ID предметов исчерпаны')
            item = ItemRecord(highest + 1, 32, b'\0' * 2, 1, 0, 0, (1, 1, 1), b'\0' * 4, None, b'\0' * 3)
            from .item_stacking import merge_stacks
            from .inventory_capacity import validate_capacity
            merged = merge_stacks(items + (item,))
            validate_capacity(items, merged, error=ServiceRejected)
            packet = encode_item_list(owner_id, merged, unknown)
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?', (packet, owner, target_pet_id))
            db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=excluded.next_id', (owner, highest + 2))
            db.execute('UPDATE service_dog_meat_rewards SET claimed_at=?,target_pet_id=?,item_id=? WHERE account=? AND pet_id=? AND claimed_at IS NULL', (self._now(), target_pet_id, item.instance_id, owner, dismissed_pet_id))
            return self._finish(db, owner, identity, action, request, petId=target_pet_id, dismissedPetId=dismissed_pet_id, templateId=32, count=1)

    def purchase_avatar(self, owner, pet_id, avatar_id, *, identity, allowed=False):
        _u32(pet_id)
        _u32(avatar_id)
        action = 'service_avatar'
        request = self._request(identity, action, dict(petId=pet_id, avatarId=avatar_id))
        with transaction(self.path) as db:
            self._gate(db, owner, allowed)
            prior = self._prior(db, owner, identity, action, request)
            if prior is not None:
                return prior
            self._pet(db, owner, pet_id)
            raise ServiceRejected('Точный оригинальный каталог аватаров не восстановлен; услуга отключена')

    def status(self, owner, *, allowed=False, connection: sqlite3.Connection | None = None):
        if connection is None:
            with transaction(self.path) as db:
                return self.status(owner, allowed=allowed, connection=db)
        db = connection
        self._owner(db, owner)
        available = True
        try:
            self._gate(db, owner, allowed)
        except ServiceRejected:
            available = False
        pets = []
        for (pet_id,) in db.execute('SELECT pet_id FROM owned_pets WHERE account=? ORDER BY pet_id', (owner,)).fetchall():
            row, pet = self._pet(db, owner, pet_id)
            can_dismiss = available
            try:
                self._dismissable(db, owner, pet_id, row)
            except ServiceRejected:
                can_dismiss = False
            pending = db.execute('SELECT due_at FROM service_dismissals WHERE account=? AND pet_id=? AND completed_at IS NULL', (owner, pet_id)).fetchone()
            pets.append(dict(petId=pet_id, name=pet.fields['0x8c4489'].decode('cp1251'), canRename=available,
                             canDismiss=can_dismiss and pending is None, dismissAt=pending[0] if pending else None))
        rewards = [dict(dismissedPetId=i, templateId=32, count=1) for (i,) in db.execute('SELECT pet_id FROM service_dog_meat_rewards WHERE account=? AND claimed_at IS NULL ORDER BY pet_id', (owner,))]
        return dict(pets=pets, renamePrices=dict(mainGold=3000, recruitCredits=3000), avatarsEnabled=False, avatars=[], pendingDogMeat=rewards)
