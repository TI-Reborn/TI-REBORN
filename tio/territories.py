"""Persisted Assault 4 windows, frozen four-account groups and territory claims.

The primary 2013 announcement supplies three tours and kill/flag anchors. The
missing ratio table, ownership tie-break, influence conversion and UTC timetable
are explicit server policies in config/territories.json, not original formulas.
This store accepts results only from an already bound authoritative match. It
does not create battles, grant unopposed victories or trust client score packets.
All mutations join the enclosing gameplay transaction when one is present.
"""
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import random
import sqlite3
import time
import uuid

from .db_transaction import connect
from .clans import ClanRejected, schema as clan_schema, membership, record
from .mine_claims import schema as mine_schema, frozen_claim
from .protocol.pet_info import decode_pet_info
from .protocol.item_list import decode_item_list

CONFIG = Path(__file__).resolve().parents[1] / 'config/territories.json'
MAX_U32 = 0xffffffff
EDIT_PHASES = {'REGISTRATION', 'TOUR2_PAUSE', 'TOUR3_PAUSE'}
TOUR_PHASES = {'TOUR1', 'TOUR2', 'TOUR3'}


class TerritoryRejected(ClanRejected):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def uint(value, maximum=MAX_U32):
    if type(value) is not int or not 0 <= value <= maximum:
        raise TerritoryRejected('Некорректное число в штурме')
    return value


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS warfare_events (
        id TEXT PRIMARY KEY,town INTEGER NOT NULL,starts INTEGER NOT NULL,ends INTEGER NOT NULL,
        phase TEXT NOT NULL,tour INTEGER NOT NULL,phase_ends INTEGER NOT NULL,
        rules TEXT NOT NULL,claim TEXT NOT NULL,finalized INTEGER NOT NULL DEFAULT 0,
        UNIQUE(town,starts))''')
    db.execute('''CREATE TABLE IF NOT EXISTS warfare_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL,leader TEXT NOT NULL,
        coalition TEXT NOT NULL,alliance_id INTEGER,clan_ids TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS warfare_group_members (
        event_id TEXT NOT NULL,account TEXT NOT NULL,group_id INTEGER NOT NULL,clan_id INTEGER NOT NULL,
        pet_ids TEXT NOT NULL,levels TEXT NOT NULL,name BLOB NOT NULL,
        ready INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,joined REAL NOT NULL,
        PRIMARY KEY(event_id,account))''')
    db.execute('CREATE INDEX IF NOT EXISTS warfare_group_rosters ON warfare_group_members(group_id,active)')
    db.execute('''CREATE TABLE IF NOT EXISTS warfare_clan_locks (
        clan_id INTEGER PRIMARY KEY,event_id TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS warfare_matches (
        id TEXT PRIMARY KEY,event_id TEXT NOT NULL,tour INTEGER NOT NULL,
        group_a INTEGER NOT NULL,group_b INTEGER NOT NULL,match_id TEXT UNIQUE,
        status TEXT NOT NULL,roster TEXT NOT NULL,created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS warfare_match_receipts (
        match_id TEXT PRIMARY KEY,event_id TEXT NOT NULL,request TEXT NOT NULL,
        receipt TEXT NOT NULL,created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS warfare_scores (
        event_id TEXT NOT NULL,clan_id INTEGER NOT NULL,account TEXT NOT NULL,
        ov_units INTEGER NOT NULL DEFAULT 0,kills INTEGER NOT NULL DEFAULT 0,
        deaths INTEGER NOT NULL DEFAULT 0,damage_dealt INTEGER NOT NULL DEFAULT 0,
        damage_taken INTEGER NOT NULL DEFAULT 0,contested INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(event_id,account))''')
    db.execute('''CREATE TABLE IF NOT EXISTS warfare_event_receipts (
        event_id TEXT PRIMARY KEY,receipt TEXT NOT NULL,created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS territory_claims (
        location INTEGER PRIMARY KEY,owner_clan INTEGER,tax_percent INTEGER NOT NULL,
        revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 4294967295),
        CHECK(tax_percent BETWEEN 0 AND 10),CHECK(owner_clan IS NOT NULL OR tax_percent=0))''')
    db.execute('''CREATE TABLE IF NOT EXISTS territory_claim_history (
        location INTEGER NOT NULL,revision INTEGER NOT NULL,owner_clan INTEGER,
        tax_percent INTEGER NOT NULL,actor TEXT NOT NULL,reason TEXT NOT NULL,created REAL NOT NULL,
        PRIMARY KEY(location,revision))''')
    for table in ('warfare_match_receipts', 'warfare_event_receipts', 'territory_claim_history'):
        for operation in ('UPDATE', 'DELETE'):
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()}
                BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Warfare audit is immutable'); END''')


def load_config(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data['ruleset'] != 'assault4' or data['players_per_group'] != 4 or data['tours'] != 3:
        raise ValueError('Only the pinned Assault 4 group/tour rules are supported')
    for key in ('registration_seconds', 'tour_seconds', 'pause_seconds', 'period_seconds'):
        if type(data[key]) is not int or not 0 < data[key] <= 604800:
            raise ValueError('Invalid warfare duration')
    if data['period_seconds'] <= data['registration_seconds'] + 3*data['tour_seconds'] + 2*data['pause_seconds']:
        raise ValueError('Overlapping territory periods')
    if data['soldiers_per_player'] != [1, 3] or data['kill_ov_units'] != 6 or data['death_ov_units'] != -3:
        raise ValueError('Invalid pinned scoring or soldier limits')
    table = data['emulator_policy']['ratio_to_ov_units']
    if not table or table[0] != [0, -4] or table[-1] != [1000, 32] or [449, 8] not in table or [551, 20] not in table:
        raise ValueError('Ratio policy must retain documented endpoints')
    previous = -1
    for threshold, units in table:
        if type(threshold) is not int or not previous < threshold <= 1000 or type(units) is not int or units % 4 or not -4 <= units <= 32:
            raise ValueError('Invalid bounded half-OV policy')
        previous = threshold
    explicit = data['emulator_policy']
    if explicit['zero_flag_total_ov_units'] != 0 or type(explicit['new_owner_tax_percent']) is not int or not 0 <= explicit['new_owner_tax_percent'] <= 10:
        raise ValueError('Invalid zero-participation or claim-tax policy')
    locations = {}
    for entry in data['territories']:
        town = uint(entry['id'])
        if not town or town in locations or entry['kind'] not in ('base', 'checkpoint'):
            raise ValueError('Duplicate/invalid territory')
        lo, hi = entry['levels']
        if type(lo) is not int or type(hi) is not int or not 4 <= lo <= hi <= 20:
            raise ValueError('Invalid territory level band')
        entry = dict(entry)
        if entry['enabled']:
            stamp = datetime.fromisoformat(entry['first_start_utc'].replace('Z', '+00:00'))
            if stamp.utcoffset().total_seconds() != 0:
                raise ValueError('UTC territory schedule required')
            entry['first_start'] = int(stamp.timestamp())
        locations[town] = entry
    if locations.get(7, {}).get('enabled'):
        from .world_completion import location
        base=location(7)
        from .crystal_market import POLICY as mining
        if base is None or not base['capture'] or base['kind']!='base':
            raise ValueError('Enabled Outpost Base requires canonical world location')
        a=base['bounds']
        for mine in mining['locations']:
            b=mine['bounds']
            if max(a[0],b[0])<=min(a[2],b[2]) and max(a[1],b[1])<=min(a[3],b[3]):
                raise ValueError('Outpost Base overlaps an active mine')
    return data, locations


class TerritoriesStore:
    def __init__(self, path, config_path=None, *, clock=time.time, rng=None):
        self.path, self.clock = Path(path), clock
        self.policy, self.locations = load_config(config_path or CONFIG)
        self.rng = rng or random.SystemRandom()
        with closing(connect(self.path)) as db, db:
            clan_schema(db); mine_schema(db); schema(db)

    def _location(self, town, *, enabled=True):
        if type(town) is not int or town not in self.locations:
            raise TerritoryRejected('Неизвестная территория')
        location = self.locations[town]
        if enabled and not location['enabled']:
            raise TerritoryRejected('Эта территория отключена')
        return location

    def _claim(self, db, town):
        if self.locations[town]['kind'] == 'checkpoint':
            return frozen_claim(db, town)
        row = db.execute('SELECT owner_clan,tax_percent,revision FROM territory_claims WHERE location=?', (town,)).fetchone()
        claim = dict(location=town, owner_clan=row[0] if row else None, tax_percent=row[1] if row else 0, revision=row[2] if row else 0)
        if row and db.execute('SELECT owner_clan,tax_percent FROM territory_claim_history WHERE location=? AND revision=?', (town, row[2])).fetchone() != row[:2]:
            raise TerritoryRejected('История владельца территории повреждена')
        return claim

    @staticmethod
    def _phase(starts, rules, now):
        cursor = starts
        sequence = [('REGISTRATION', 0, rules['registration_seconds']),
                    ('TOUR1', 1, rules['tour_seconds']), ('TOUR2_PAUSE', 1, rules['pause_seconds']),
                    ('TOUR2', 2, rules['tour_seconds']), ('TOUR3_PAUSE', 2, rules['pause_seconds']),
                    ('TOUR3', 3, rules['tour_seconds'])]
        for phase, tour, seconds in sequence:
            cursor += seconds
            if now < cursor:
                return phase, tour, cursor
        return 'FINISHED', 3, cursor

    def _event(self, db, event_id):
        row = db.execute('SELECT id,town,starts,ends,phase,tour,phase_ends,rules,claim,finalized FROM warfare_events WHERE id=?', (event_id,)).fetchone()
        if not row:
            raise TerritoryRejected('Событие штурма не найдено')
        result = dict(zip(('id', 'town', 'starts', 'ends', 'phase', 'tour', 'phase_ends', 'rules', 'claim', 'finalized'), row))
        result['rules'], result['claim'] = json.loads(result['rules']), json.loads(result['claim'])
        result['finalized'] = bool(result['finalized'])
        return result

    def _sync(self, db):
        now = self.clock()
        for town, location in self.locations.items():
            if not location['enabled']:
                continue
            default=self._default_start(location,now)
            starts=self._scheduled_start(db,town,default)
            if now<starts:continue
            event_id = f'territory:{town}:{starts}'
            if not db.execute('SELECT 1 FROM warfare_events WHERE id=?', (event_id,)).fetchone():
                phase, tour, end = self._phase(starts, self.policy, now)
                ends = starts+self.policy['registration_seconds']+3*self.policy['tour_seconds']+2*self.policy['pause_seconds']
                rules = {**self.policy, 'territory': location}
                db.execute('INSERT INTO warfare_events VALUES (?,?,?,?,?,?,?,?,?,0)',
                           (event_id, town, starts, ends, phase, tour, end, canonical(rules), canonical(self._claim(db, town))))
        for event_id, starts, rules in db.execute('SELECT id,starts,rules FROM warfare_events WHERE finalized=0').fetchall():
            event = self._event(db, event_id)
            phase, tour, end = self._phase(starts, json.loads(rules), now)
            # A backwards wall clock cannot reopen a completed phase.
            if end >= event['phase_ends']:
                db.execute('UPDATE warfare_events SET phase=?,tour=?,phase_ends=? WHERE id=?', (phase, tour, end, event_id))
            for pair_id, a, b in db.execute("SELECT id,group_a,group_b FROM warfare_matches WHERE event_id=? AND status='reserved' AND tour!=?", (event_id, tour if phase in TOUR_PHASES else -1)).fetchall():
                db.execute("UPDATE warfare_matches SET status='cancelled' WHERE id=?", (pair_id,))
                db.execute("UPDATE warfare_groups SET status='open' WHERE id IN (?,?) AND status='paired'", (a, b))

    def sync(self):
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            return tuple(self._event(db, r[0]) for r in db.execute('SELECT id FROM warfare_events WHERE finalized=0 ORDER BY starts,town'))

    def _default_start(self,location,now):
        # The owner's earlier/later choice stays on the fixed weekly day.
        day=location['first_start']//86400*86400
        period=max(0,int((now-day)//self.policy['period_seconds']))
        return location['first_start']+period*self.policy['period_seconds']

    def _scheduled_start(self,db,town,default):
        if self.locations[town]['kind']!='base':return default
        from .clan_benefits import scheduled_start
        return scheduled_start(db,town,default)

    def _current(self, db, town):
        location = self._location(town)
        now = self.clock()
        rows = db.execute('SELECT id FROM warfare_events WHERE town=? AND finalized=0 ORDER BY starts DESC', (town,)).fetchall()
        if rows:
            event = self._event(db, rows[0][0])
            if event['phase'] != 'FINISHED' or now >= event['ends']:
                return event
        default=self._default_start(location,now)
        starts=self._scheduled_start(db,town,default)
        if now>=starts:starts=self._scheduled_start(db,town,default+self.policy['period_seconds'])
        return dict(id=f'territory:{town}:{starts}', town=town, starts=starts,
                    ends=starts+self.policy['registration_seconds']+3*self.policy['tour_seconds']+2*self.policy['pause_seconds'],
                    phase='WAIT_ASSAULT', tour=0, phase_ends=starts, finalized=False,
                    claim=self._claim(db, town), rules={**self.policy, 'territory': location})

    def current_event(self, town):
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            return self._current(db, town)

    def info(self, town):
        location = self._location(town, enabled=False)
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            return {**location, 'claim': self._claim(db, town),
                    'event': self._current(db, town) if location['enabled'] else None}

    def _participant(self, db, account, town, pet_ids):
        if not isinstance(account, str) or not account:
            raise TerritoryRejected('Аккаунт не указан')
        clan = membership(db, account)
        if clan is None:
            raise TerritoryRejected('Для штурма нужно состоять в клане')
        ids = tuple(pet_ids)
        if not 1 <= len(ids) <= 3 or len(set(ids)) != len(ids):
            raise TerritoryRejected('Выберите от одного до трёх бойцов')
        lo, hi = self.locations[town]['levels']; levels = []
        from .enhancement_limits import enhancement_cap
        from .passive_stats import project_saved_pet
        cap = self.locations[town].get('max_upgrade', enhancement_cap(hi))
        for pet_id in ids:
            uint(pet_id)
            row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?', (account, pet_id)).fetchone()
            if not row:
                raise TerritoryRejected('Боец не принадлежит аккаунту')
            pet = decode_pet_info(project_saved_pet(db, account, pet_id, bytes(row[1]), bool(row[0])), human_equipment=bool(row[0]))
            if pet.fields['0x8c43eb'] != pet_id or pet.fields['0x8c4ab1'] <= 0 or pet.fields['0x8c4ab1'] != pet.fields['0x8c4a07']:
                raise TerritoryRejected('Для штурма нужны полностью здоровые бойцы')
            inventory_owner, items, _ = decode_item_list(bytes(row[2]))
            if inventory_owner != pet_id:
                raise TerritoryRejected('Инвентарь не принадлежит выбранному бойцу')
            if any(i.equipped and i.unknown_bytes_03[0] > cap for i in items):
                raise TerritoryRejected('Улучшение экипировки превышает предел территории')
            level = pet.fields['0x8c4aef']
            if not lo <= level <= hi:
                raise TerritoryRejected('Уровень бойца не подходит для территории')
            levels.append(level)
        from .alliances import alliance_for_clan
        allied = alliance_for_clan(db, clan['id'])
        return dict(account=account, clan_id=clan['id'], pet_ids=ids, levels=tuple(levels),
                    alliance_id=allied['id'] if allied else None,
                    coalition=f"alliance:{allied['id']}" if allied else f"clan:{clan['id']}",
                    clan_ids=tuple(sorted(allied['clans'])) if allied else (clan['id'],),
                    max_upgrade=cap,
                    name=bytes(db.execute('SELECT name FROM characters WHERE account=? ORDER BY slot LIMIT 1', (account,)).fetchone()[0]))

    def participant(self, account, town, pet_ids=(1,)):
        self._location(town)
        with closing(connect(self.path)) as db:
            return self._participant(db, account, town, pet_ids)

    @staticmethod
    def _lock(db, event_id, clans):
        for clan in clans:
            old = db.execute('SELECT event_id FROM warfare_clan_locks WHERE clan_id=?', (clan,)).fetchone()
            if old and old[0] != event_id:
                raise TerritoryRejected('Клан уже участвует в другом штурме')
            db.execute('INSERT OR IGNORE INTO warfare_clan_locks VALUES (?,?)', (clan, event_id))

    def _group(self, db, group_id):
        uint(group_id)
        row = db.execute('SELECT id,event_id,leader,coalition,alliance_id,clan_ids,status FROM warfare_groups WHERE id=?', (group_id,)).fetchone()
        if not row:
            raise TerritoryRejected('Боевая группа не найдена')
        result = dict(zip(('id', 'event_id', 'leader', 'coalition', 'alliance_id', 'clan_ids', 'status'), row))
        result['clan_ids'] = tuple(json.loads(result['clan_ids']))
        result['town'] = self._event(db, result['event_id'])['town']
        result['members'] = tuple(dict(account=a, clan_id=c, pet_ids=tuple(json.loads(p)), levels=tuple(json.loads(l)), name=bytes(n), ready=bool(r))
                                  for a, c, p, l, n, r in db.execute('SELECT account,clan_id,pet_ids,levels,name,ready FROM warfare_group_members WHERE group_id=? AND active=1 ORDER BY joined,account', (group_id,)))
        return result

    def group(self, group_id):
        with closing(connect(self.path)) as db:
            return self._group(db, group_id)

    def own_group(self, account, event_id=None, *, connection: sqlite3.Connection | None = None):
        if connection is None:
            with closing(connect(self.path)) as db:
                return self.own_group(account, event_id, connection=db)
        db = connection
        sql = '''SELECT m.group_id FROM warfare_group_members m JOIN warfare_events e ON e.id=m.event_id
                 WHERE m.account=? AND m.active=1 AND e.finalized=0'''
        args = [account]
        if event_id is not None:
            sql += ' AND m.event_id=?'; args.append(event_id)
        row = db.execute(sql+' ORDER BY e.starts DESC LIMIT 1', args).fetchone()
        return self._group(db, row[0]) if row else None

    def _member_group(self, db, account):
        row = db.execute('''SELECT m.group_id FROM warfare_group_members m JOIN warfare_events e ON e.id=m.event_id
            WHERE m.account=? AND m.active=1 AND e.finalized=0 ORDER BY e.starts DESC LIMIT 1''', (account,)).fetchone()
        if not row:
            raise TerritoryRejected('Вы не состоите в боевой группе')
        return self._group(db, row[0])

    def _editable(self, db, group):
        event = self._event(db, group['event_id'])
        if event['finalized'] or event['phase'] not in EDIT_PHASES or group['status'] in ('paired', 'running', 'closed'):
            raise TerritoryRejected('Состав группы сейчас закреплён')
        return event

    def _add_member(self, db, group, member):
        if member['coalition'] != group['coalition'] or member['clan_ids'] != group['clan_ids']:
            raise TerritoryRejected('В группу входят только сокланы или участники того же альянса')
        old = db.execute('SELECT group_id,clan_id,active FROM warfare_group_members WHERE event_id=? AND account=?', (group['event_id'], member['account'])).fetchone()
        if old and (old[0] != group['id'] or old[1] != member['clan_id'] or old[2]):
            raise TerritoryRejected('Аккаунт уже закреплён за группой этого штурма')
        if len(group['members']) >= 4:
            raise TerritoryRejected('В боевой группе уже четыре игрока')
        self._lock(db, group['event_id'], member['clan_ids'])
        if old:
            db.execute('UPDATE warfare_group_members SET active=1,ready=0,pet_ids=?,levels=? WHERE event_id=? AND account=?',
                       (canonical(member['pet_ids']), canonical(member['levels']), group['event_id'], member['account']))
        else:
            db.execute('INSERT INTO warfare_group_members VALUES (?,?,?,?,?,?,?,0,1,?)',
                       (group['event_id'], member['account'], group['id'], member['clan_id'], canonical(member['pet_ids']), canonical(member['levels']), member['name'], self.clock()))
        db.execute("UPDATE warfare_groups SET status='open' WHERE id=?", (group['id'],))

    def create_group(self, account, town, pet_ids=(1,)):
        self._location(town)
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            event = self._current(db, town)
            if event['phase'] not in EDIT_PHASES or event['finalized']:
                raise TerritoryRejected('Сейчас нет регистрации боевых групп')
            if db.execute('SELECT 1 FROM warfare_group_members WHERE event_id=? AND account=?', (event['id'], account)).fetchone():
                raise TerritoryRejected('Аккаунт уже закреплён за группой этого штурма')
            member = self._participant(db, account, town, pet_ids)
            self._lock(db, event['id'], member['clan_ids'])
            key = db.execute("INSERT INTO warfare_groups(event_id,leader,coalition,alliance_id,clan_ids,created) VALUES (?,?,?,?,?,?)",
                             (event['id'], account, member['coalition'], member['alliance_id'], canonical(member['clan_ids']), self.clock())).lastrowid
            self._add_member(db, self._group(db, key), member)
            return self._group(db, key)

    def join_group(self, account, group_id, pet_ids=(1,)):
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            group = self._group(db, group_id); self._editable(db, group)
            self._add_member(db, group, self._participant(db, account, group['town'], pet_ids))
            return self._group(db, group_id)

    def select(self, account, pet_ids):
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            group = self._member_group(db, account); self._editable(db, group)
            member = self._participant(db, account, group['town'], pet_ids)
            if member['coalition'] != group['coalition']:
                raise TerritoryRejected('Состав клана или альянса изменился')
            db.execute('UPDATE warfare_group_members SET pet_ids=?,levels=?,ready=0 WHERE event_id=? AND account=?',
                       (canonical(member['pet_ids']), canonical(member['levels']), group['event_id'], account))
            db.execute("UPDATE warfare_groups SET status='open' WHERE id=?", (group['id'],))
            return self._group(db, group['id'])

    def ready(self, account, value):
        if type(value) is not bool:
            raise TerritoryRejected('Некорректная готовность')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            group = self._member_group(db, account)
            event = self._event(db, group['event_id'])
            if event['finalized'] or event['phase'] == 'FINISHED' or group['status'] in ('paired', 'running', 'closed'):
                raise TerritoryRejected('Готовность группы сейчас закреплена')
            member = next(m for m in group['members'] if m['account'] == account)
            if value:
                checked = self._participant(db, account, group['town'], member['pet_ids'])
                if checked['clan_id'] != member['clan_id'] or checked['coalition'] != group['coalition']:
                    raise TerritoryRejected('Состав клана или альянса изменился')
                db.execute('UPDATE warfare_group_members SET levels=? WHERE event_id=? AND account=?',
                           (canonical(checked['levels']), group['event_id'], account))
            db.execute('UPDATE warfare_group_members SET ready=? WHERE event_id=? AND account=?', (int(value), group['event_id'], account))
            if not value:
                db.execute("UPDATE warfare_groups SET status='open' WHERE id=?", (group['id'],))
            return self._group(db, group['id'])

    def start_group(self, account):
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            group = self._member_group(db, account); event = self._event(db, group['event_id'])
            if group['leader'] != account or group['status'] not in ('open', 'ready') or event['phase'] not in EDIT_PHASES | TOUR_PHASES or event['finalized']:
                raise TerritoryRejected('Группу может подготовить только её командир')
            if len(group['members']) != 4 or not all(m['ready'] for m in group['members']):
                raise TerritoryRejected('Нужны четыре готовых игрока')
            for member in group['members']:
                checked = self._participant(db, member['account'], group['town'], member['pet_ids'])
                if checked['clan_id'] != member['clan_id'] or checked['coalition'] != group['coalition']:
                    raise TerritoryRejected('Состав клана или альянса изменился')
            db.execute("UPDATE warfare_groups SET status='ready' WHERE id=?", (group['id'],))
            return self._group(db, group['id'])

    def leave_group(self, account):
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            group = self._member_group(db, account)
            if group['status'] in ('paired', 'running'):
                raise TerritoryRejected('Нельзя выйти из закреплённого боя')
            db.execute('UPDATE warfare_group_members SET active=0,ready=0 WHERE event_id=? AND account=?', (group['event_id'], account))
            remaining = [m for m in group['members'] if m['account'] != account]
            leader = remaining[0]['account'] if remaining and group['leader'] == account else group['leader']
            db.execute('UPDATE warfare_groups SET leader=?,status=? WHERE id=?', (leader, 'open' if remaining else 'closed', group['id']))
            return self._group(db, group['id'])

    def disconnect(self, account):
        """Readiness is live; the bound match's frozen roster never changes."""
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            row = db.execute('''SELECT m.group_id FROM warfare_group_members m JOIN warfare_events e ON e.id=m.event_id
                WHERE m.account=? AND m.active=1 AND e.finalized=0 ORDER BY e.starts DESC LIMIT 1''', (account,)).fetchone()
            if not row:
                return None
            group = self._group(db, row[0])
            db.execute('UPDATE warfare_group_members SET ready=0 WHERE event_id=? AND account=?', (group['event_id'], account))
            if group['status'] == 'paired':
                pair = db.execute("SELECT id,group_a,group_b FROM warfare_matches WHERE status='reserved' AND (group_a=? OR group_b=?)", (group['id'], group['id'])).fetchone()
                if pair:
                    db.execute("UPDATE warfare_matches SET status='cancelled' WHERE id=?", (pair[0],))
                    db.execute("UPDATE warfare_groups SET status='open' WHERE id IN (?,?)", pair[1:])
            elif group['status'] == 'ready':
                db.execute("UPDATE warfare_groups SET status='open' WHERE id=?", (group['id'],))
            return self._group(db, group['id'])

    def groups(self, town, coalition=None):
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            event = self._current(db, town)
            sql = "SELECT id FROM warfare_groups WHERE event_id=? AND status!='closed'"; args = [event['id']]
            if coalition is not None:
                sql += ' AND coalition=?'; args.append(coalition)
            return tuple(self._group(db, r[0]) for r in db.execute(sql+' ORDER BY id', args))

    @staticmethod
    def _freeze(groups):
        return [dict(id=g['id'], coalition=g['coalition'], alliance_id=g['alliance_id'], clan_ids=g['clan_ids'],
                     members=[{k: m[k] for k in ('account', 'clan_id', 'pet_ids', 'levels')} for m in g['members']]) for g in groups]

    @staticmethod
    def _match(db, pair_id):
        row = db.execute('SELECT id,event_id,tour,group_a,group_b,match_id,status,roster FROM warfare_matches WHERE id=?', (pair_id,)).fetchone()
        if not row:
            raise TerritoryRejected('Пара боевых групп не найдена')
        result = dict(zip(('id', 'event_id', 'tour', 'group_a', 'group_b', 'match_id', 'status', 'roster'), row))
        result['roster'] = json.loads(result['roster'])
        return result

    def pair_ready(self, event_id):
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            event = self._event(db, event_id)
            if event['finalized'] or event['phase'] not in TOUR_PHASES:
                return None
            ready = [self._group(db, r[0]) for r in db.execute("SELECT id FROM warfare_groups WHERE event_id=? AND status='ready' ORDER BY id", (event_id,))]
            ready = [g for g in ready if len(g['members']) == 4 and all(m['ready'] for m in g['members'])]
            eligible = []
            for group in ready:
                valid = True
                for member in group['members']:
                    try:
                        checked = self._participant(db, member['account'], group['town'], member['pet_ids'])
                        if checked['clan_id'] != member['clan_id'] or checked['coalition'] != group['coalition']:
                            raise TerritoryRejected('Состав клана или альянса изменился')
                    except TerritoryRejected:
                        # Ordinary city gear/HP changes invalidate readiness,
                        # rather than throwing through the server's periodic tick.
                        db.execute('UPDATE warfare_group_members SET ready=0 WHERE event_id=? AND account=?', (event_id, member['account']))
                        db.execute("UPDATE warfare_groups SET status='open' WHERE id=?", (group['id'],))
                        valid = False
                    else:
                        db.execute('UPDATE warfare_group_members SET levels=? WHERE event_id=? AND account=?',
                                   (canonical(checked['levels']), event_id, member['account']))
                if valid:
                    eligible.append(self._group(db, group['id']))
            ready = eligible
            self.rng.shuffle(ready)
            selected = next(((a, b) for i, a in enumerate(ready) for b in ready[i+1:] if a['coalition'] != b['coalition']), None)
            if selected is None:
                return None
            pair_id = str(uuid.uuid4())
            a, b = selected
            db.execute('INSERT INTO warfare_matches VALUES (?,?,?,?,?,NULL,?,?,?)',
                       (pair_id, event_id, event['tour'], a['id'], b['id'], 'reserved', canonical(self._freeze(selected)), self.clock()))
            db.execute("UPDATE warfare_groups SET status='paired' WHERE id IN (?,?)", (a['id'], b['id']))
            return dict(id=pair_id, event_id=event_id, tour=event['tour'], groups=tuple(self._group(db, g['id']) for g in selected))

    def bind_match(self, match_id, groups):
        if not isinstance(match_id, str) or not match_id or len(match_id) > 128:
            raise TerritoryRejected('Некорректный идентификатор боя')
        ids = tuple(g['id'] if isinstance(g, dict) else g for g in (groups['groups'] if isinstance(groups, dict) else groups))
        if len(ids) != 2 or ids[0] == ids[1]:
            raise TerritoryRejected('Нужны две разные группы')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            existing = db.execute('SELECT id FROM warfare_matches WHERE match_id=?', (match_id,)).fetchone()
            if existing:
                found = self._match(db, existing[0])
                if (found['group_a'], found['group_b']) != ids:
                    raise TerritoryRejected('Бой уже связан с другой парой')
                return found
            row = db.execute("SELECT id FROM warfare_matches WHERE group_a=? AND group_b=? AND status='reserved' ORDER BY created DESC LIMIT 1", ids).fetchone()
            if not row:
                raise TerritoryRejected('Группы не прошли общий подбор')
            pair = self._match(db, row[0]); event = self._event(db, pair['event_id'])
            if event['phase'] not in TOUR_PHASES or event['tour'] != pair['tour'] or event['finalized']:
                raise TerritoryRejected('Тур уже завершён')
            db.execute("UPDATE warfare_matches SET match_id=?,status='running' WHERE id=?", (match_id, pair['id']))
            db.execute("UPDATE warfare_groups SET status='running' WHERE id IN (?,?)", ids)
            return self._match(db, pair['id'])

    def cancel_pair(self, pair_id):
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            pair = self._match(db, pair_id)
            if pair['status'] == 'cancelled':
                return pair
            if pair['status'] != 'reserved':
                raise TerritoryRejected('Рождённый бой нельзя отменить как заявку')
            event = self._event(db, pair['event_id'])
            db.execute("UPDATE warfare_matches SET status='cancelled' WHERE id=?", (pair_id,))
            status = 'ready' if event['phase'] in TOUR_PHASES and event['tour'] == pair['tour'] else 'open'
            db.execute('UPDATE warfare_groups SET status=? WHERE id IN (?,?)', (status, pair['group_a'], pair['group_b']))
            return self._match(db, pair_id)

    def matches(self, event_id):
        with closing(connect(self.path)) as db:
            return tuple(self._match(db, r[0]) for r in db.execute('SELECT id FROM warfare_matches WHERE event_id=? ORDER BY created,id', (event_id,)))

    @staticmethod
    def _flag_units(rules, own, other):
        if own+other == 0:
            return rules['emulator_policy']['zero_flag_total_ov_units']
        # The primary examples display one decimal percent: 280/624 is 44.9%,
        # not the truncated 44.8% that would miss the documented policy anchor.
        ratio = (1000*own+(own+other)//2)//(own+other)
        return next(units for threshold, units in reversed(rules['emulator_policy']['ratio_to_ov_units']) if ratio >= threshold)

    def settle_match(self, event_id, match_id, results, flag_points=(0, 0), decisive=None):
        if not isinstance(results, dict) or not isinstance(flag_points, (tuple, list)) or len(flag_points) != 2:
            raise TerritoryRejected('Некорректный результат штурма')
        flags = [uint(n) for n in flag_points]
        if decisive is not None:
            uint(decisive)
        normalized = {}
        for account, values in results.items():
            if not isinstance(account, str) or not isinstance(values, dict) or set(values) != {'kills', 'deaths', 'damage_dealt', 'damage_taken'}:
                raise TerritoryRejected('Нужны авторитетные данные каждого участника')
            normalized[account] = {k: uint(values[k]) for k in ('kills', 'deaths', 'damage_dealt', 'damage_taken')}
        request = canonical(dict(event_id=event_id, results=normalized, flag_points=flags, decisive=decisive))
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            old = db.execute('SELECT event_id,request,receipt FROM warfare_match_receipts WHERE match_id=?', (match_id,)).fetchone()
            if old:
                if old[:2] != (event_id, request):
                    raise TerritoryRejected('Повтор боя отличается от сохранённого результата')
                return json.loads(old[2])
            event = self._event(db, event_id)
            row = db.execute('SELECT id FROM warfare_matches WHERE match_id=? AND event_id=?', (match_id, event_id)).fetchone()
            if not row or event['finalized']:
                raise TerritoryRejected('Бой не принадлежит открытому штурму')
            match = self._match(db, row[0]); groups = match['roster']
            accounts = {m['account'] for g in groups for m in g['members']}
            if match['status'] != 'running' or accounts != set(normalized) or len(accounts) != 8 or groups[0]['coalition'] == groups[1]['coalition']:
                raise TerritoryRejected('Результат не соответствует закреплённым противникам')
            if decisive is not None and decisive not in (match['group_a'], match['group_b']):
                raise TerritoryRejected('Победитель не участвовал в этом бою')
            contested = bool(sum(flags) or any(v['kills'] or v['damage_dealt'] for v in normalized.values()))
            account_scores = {}; clan_scores = {}
            for side, group in enumerate(groups):
                enemy = groups[1-side]
                enemy_count = sum(len(m['pet_ids']) for m in enemy['members'])
                if sum(normalized[m['account']]['kills'] for m in group['members']) > enemy_count:
                    raise TerritoryRejected('Число убийств превышает состав соперника')
                flag_units = (32 if group['id'] == decisive else -4) if decisive is not None else self._flag_units(event['rules'], flags[side], flags[1-side])
                for member in group['members']:
                    account = member['account']; values = normalized[account]
                    if values['deaths'] > len(member['pet_ids']):
                        raise TerritoryRejected('Потери превышают выбранный отряд')
                    units = values['kills']*6-values['deaths']*3+flag_units//4
                    clan = member['clan_id']; account_scores[account] = dict(clan_id=clan, ov_units=units, **values)
                    clan_scores[clan] = clan_scores.get(clan, 0)+units
                    db.execute('''INSERT INTO warfare_scores VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id,account)
                        DO UPDATE SET ov_units=ov_units+excluded.ov_units,kills=kills+excluded.kills,
                        deaths=deaths+excluded.deaths,damage_dealt=damage_dealt+excluded.damage_dealt,
                        damage_taken=damage_taken+excluded.damage_taken,contested=MAX(contested,excluded.contested)''',
                        (event_id, clan, account, units, values['kills'], values['deaths'], values['damage_dealt'], values['damage_taken'], int(contested)))
            receipt = dict(event_id=event_id, match_id=match_id, tour=match['tour'], contested=contested,
                           accounts=account_scores, clans={str(k): v for k, v in clan_scores.items()}, flag_points=flags)
            db.execute('INSERT INTO warfare_match_receipts VALUES (?,?,?,?,?)', (match_id, event_id, request, canonical(receipt), self.clock()))
            db.execute("UPDATE warfare_matches SET status='settled' WHERE id=?", (match['id'],))
            db.execute("UPDATE warfare_groups SET status='open' WHERE id IN (?,?)", (match['group_a'], match['group_b']))
            db.execute('UPDATE warfare_group_members SET ready=0 WHERE group_id IN (?,?)', (match['group_a'], match['group_b']))
            return receipt

    def abort_match(self, event_id, match_id, reason):
        """Fail closed for a server fault: a durable outcome with no score award.

        Ordinary PvP forfeits must use settle_match with actual combat counters;
        this method cannot turn loading/quarantine/recovery faults into wins.
        """
        if reason not in {'loading_timeout', 'quarantine', 'graceful_shutdown', 'birth_failed', 'recovery_missing', 'server_fault', 'no_active_humans'}:
            raise TerritoryRejected('Неизвестная причина отмены серверного боя')
        request = canonical(dict(event_id=event_id, kind='aborted', reason=reason))
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            old = db.execute('SELECT event_id,request,receipt FROM warfare_match_receipts WHERE match_id=?', (match_id,)).fetchone()
            if old:
                if old[:2] != (event_id, request):
                    raise TerritoryRejected('Отмена отличается от сохранённого результата боя')
                return json.loads(old[2])
            event = self._event(db, event_id)
            row = db.execute('SELECT id FROM warfare_matches WHERE match_id=? AND event_id=?', (match_id, event_id)).fetchone()
            if not row or event['finalized']:
                raise TerritoryRejected('Бой не принадлежит открытому штурму')
            match = self._match(db, row[0])
            if match['status'] != 'running':
                raise TerritoryRejected('Бой уже завершён')
            receipt = dict(event_id=event_id, match_id=match_id, tour=match['tour'], status='aborted',
                           reason=reason, contested=False, accounts={}, clans={}, flag_points=[0, 0])
            db.execute('INSERT INTO warfare_match_receipts VALUES (?,?,?,?,?)', (match_id, event_id, request, canonical(receipt), self.clock()))
            db.execute("UPDATE warfare_matches SET status='aborted' WHERE id=?", (match['id'],))
            db.execute("UPDATE warfare_groups SET status='open' WHERE id IN (?,?)", (match['group_a'], match['group_b']))
            db.execute('UPDATE warfare_group_members SET ready=0 WHERE group_id IN (?,?)', (match['group_a'], match['group_b']))
            return receipt

    def _capture(self, db, event, winner):
        previous = self._claim(db, event['town'])
        if previous != event['claim']:
            return previous, False, 'claim_changed'
        if winner is None or previous['owner_clan'] == winner:
            return previous, False, 'no_positive_contender' if winner is None else 'owner_retained'
        if not db.execute('SELECT 1 FROM clans WHERE id=?', (winner,)).fetchone():
            raise TerritoryRejected('Клан победителя больше не существует')
        revision = previous['revision']+1
        if revision > MAX_U32:
            raise TerritoryRejected('Исчерпана ревизия территории')
        result = dict(location=event['town'], owner_clan=winner, tax_percent=event['rules']['emulator_policy']['new_owner_tax_percent'], revision=revision)
        checkpoint = self.locations[event['town']]['kind'] == 'checkpoint'
        claims, history = ('mine_claims', 'mine_claim_history') if checkpoint else ('territory_claims', 'territory_claim_history')
        db.execute(f'''INSERT INTO {history} VALUES (?,?,?,?,?,?,?)''',
                   (event['town'], revision, winner, result['tax_percent'], 'assault:'+event['id'], 'positive contested event OV', self.clock()))
        if previous['revision']:
            changed = db.execute(f'UPDATE {claims} SET owner_clan=?,tax_percent=?,revision=? WHERE location=? AND revision=?',
                                 (winner, result['tax_percent'], revision, event['town'], previous['revision'])).rowcount
            if changed != 1:
                raise TerritoryRejected('Владелец территории изменился одновременно')
        else:
            db.execute(f'INSERT INTO {claims} VALUES (?,?,?,?)', (event['town'], winner, result['tax_percent'], revision))
        return result, True, 'captured'

    def finalize(self, event_id):
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._sync(db)
            old = db.execute('SELECT receipt FROM warfare_event_receipts WHERE event_id=?', (event_id,)).fetchone()
            if old:
                receipt=json.loads(old[0])
                if receipt.get('benefits_version')==1:
                    self._settle_benefits(db,self._event(db,event_id),receipt)
                return receipt
            event = self._event(db, event_id)
            if event['phase'] != 'FINISHED' or event['finalized']:
                raise TerritoryRejected('Штурм ещё не завершён')
            if db.execute("SELECT 1 FROM warfare_matches WHERE event_id=? AND status IN ('reserved','running')", (event_id,)).fetchone():
                raise TerritoryRejected('Ожидается результат уже начатого боя')
            scores = list(db.execute('SELECT clan_id,SUM(ov_units),MAX(contested) FROM warfare_scores WHERE event_id=? GROUP BY clan_id ORDER BY clan_id', (event_id,)))
            contenders = [(clan, units) for clan, units, contested in scores if contested and units > 0]
            highest = max((units for _, units in contenders), default=0)
            tied = [clan for clan, units in contenders if units == highest]
            winner = event['claim']['owner_clan'] if event['claim']['owner_clan'] in tied else min(tied, default=None)
            claim, captured, reason = self._capture(db, event, winner)
            influence = {}
            for clan, units, contested in scores:
                amount = max(units, 0)//2 if contested else 0
                if not amount:
                    continue
                row = db.execute('SELECT influence,leader FROM clans WHERE id=?', (clan,)).fetchone()
                if not row:
                    raise TerritoryRejected('Участник штурма больше не существует')
                amount = min(amount, MAX_U32-row[0])
                if not amount:
                    continue
                db.execute('UPDATE clans SET influence=influence+? WHERE id=?', (amount, clan))
                record(db, clan, row[1], 'assault_influence', canonical(dict(event_id=event_id, amount=amount, ov_units=units)))
                influence[str(clan)] = amount
            receipt = dict(event_id=event_id, town=event['town'], winner_clan=winner,
                           captured=captured, reason=reason, claim=claim, influence=influence,
                           scores={str(clan): units for clan, units, _ in scores},benefits_version=1)
            db.execute('INSERT INTO warfare_event_receipts VALUES (?,?,?)', (event_id, canonical(receipt), self.clock()))
            db.execute('UPDATE warfare_events SET finalized=1 WHERE id=?', (event_id,))
            db.execute("UPDATE warfare_groups SET status='closed' WHERE event_id=?", (event_id,))
            db.execute('DELETE FROM warfare_clan_locks WHERE event_id=?', (event_id,))
            self._settle_benefits(db,event,receipt)
            return receipt

    def _settle_benefits(self,db,event,final):
        """New finalized receipts only, within the existing shared transaction."""
        from .clan_benefits import settle_assault
        from .achievements import assault_result
        prizes=settle_assault(db,event['id'])
        owner=event['claim']['owner_clan'];base=self.locations[event['town']]['kind']=='base'
        for clan,account,contested in db.execute('SELECT clan_id,account,contested FROM warfare_scores WHERE event_id=? ORDER BY account',(event['id'],)).fetchall():
            if not contested:continue
            place=prizes['players'].get(account,{}).get('place')
            captured=base and final['captured'] and clan==final['winner_clan']
            defended=base and not final['captured'] and owner is not None and final['winner_clan']==owner and clan==owner
            assault_result(db,account,event['id'],captured=captured,defended=defended,place=place)

    def ranking(self, event_id=None, limit=20):
        uint(limit, 100)
        with closing(connect(self.path)) as db:
            sql = 'SELECT s.clan_id,c.name,SUM(s.ov_units) AS score FROM warfare_scores s JOIN clans c ON c.id=s.clan_id'
            args = []
            if event_id is not None:
                sql += ' WHERE s.event_id=?'; args.append(event_id)
            sql += ' GROUP BY s.clan_id ORDER BY score DESC,s.clan_id LIMIT ?'; args.append(limit)
            return tuple(dict(clan_id=c, name=bytes(n), ov_units=u) for c, n, u in db.execute(sql, args))
