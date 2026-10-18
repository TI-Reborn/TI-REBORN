"""Durable, private cooperative clearance contracts.

The caller supplies an authoritative party snapshot inside its gameplay unit.
If a PartyStore is available, its current snapshot is checked in the same SQLite
transaction. Frozen mission data and award intents never modify player wallets.
The catalogue's geometry, combat profiles and rewards are emulator design.
"""
from copy import deepcopy
from contextlib import closing, contextmanager
import json
import math
from pathlib import Path
import random
import re
import time
import uuid

from .db_transaction import connect, current, transaction


DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / 'config/pve_contracts.json'
TERMINAL = frozenset(('completed', 'failed', 'cancelled', 'expired'))
ACTIVE = frozenset(('accepted', 'travelling', 'arrived', 'active'))
TRANSITIONS = {
    'accepted': frozenset(('travelling', 'arrived', 'cancelled', 'expired')),
    'travelling': frozenset(('arrived', 'cancelled', 'expired')),
    'arrived': frozenset(('active', 'cancelled', 'expired')),
    'active': frozenset(('completed', 'failed')),
}
_SLUG = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')


def _text(value, label, maximum=256):
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid ' + label)
    return value


def _integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid ' + label)
    return value


def _pair(value, label, low, high):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError('Invalid ' + label)
    a, b = (_integer(v, label, low, high) for v in value)
    if a > b:
        raise ValueError('Invalid ' + label)
    return [a, b]


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _party_id(value):
    if type(value) is int:
        return str(_integer(value, 'party id', 1, 2**63 - 1))
    return _text(value, 'party id')


def validate_catalog(source):
    """Reject invalid or unsafe slots before a store can offer a contract."""
    if not isinstance(source, dict) or set(source) != {'version', 'source', 'arrival_ttl_seconds', 'safe_margin', 'templates'}:
        raise ValueError('Invalid contract catalogue')
    result = deepcopy(source)
    _integer(result['version'], 'catalogue version', 1, 1_000_000)
    _text(result['source'], 'catalogue source', 2048)
    _integer(result['arrival_ttl_seconds'], 'arrival expiry', 60, 86400)
    margin = _integer(result['safe_margin'], 'safe margin', 15, 128)
    records = result['templates']
    if not isinstance(records, list) or not 1 <= len(records) <= 64:
        raise ValueError('Invalid contract templates')
    from .locations import TOWNS
    seen_ids, seen_zones, rectangles = set(), set(), []
    fields = {'id', 'version', 'name', 'objective', 'zone_id', 'bounds', 'levels',
              'recommended_party_size', 'map_profile', 'map_size', 'enemies', 'reward'}
    for record in records:
        if not isinstance(record, dict) or set(record) != fields:
            raise ValueError('Invalid contract template')
        identity = _text(record['id'], 'template id', 64)
        if not _SLUG.fullmatch(identity) or identity in seen_ids:
            raise ValueError('Duplicate or invalid contract template id')
        seen_ids.add(identity)
        _integer(record['version'], 'template version', 1, 1_000_000)
        _text(record['name'], 'template name')
        _text(record['objective'], 'objective', 1024)
        zone = _integer(record['zone_id'], 'hidden zone id', 18, 255)
        # Private contract markers have their own scene namespace. Existing
        # local IDs18..20 remain valid when a new public town reuses an ID at
        # different coordinates. The geometry/safe-zone check below still
        # reserves every actual public rectangle, including the matching ID.
        if zone in seen_zones:
            raise ValueError('Duplicate contract zone')
        seen_zones.add(zone)
        bounds = record['bounds']
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
            raise ValueError('Invalid contract bounds')
        x1, y1, x2, y2 = (_integer(v, 'contract coordinate', -512, 511) for v in bounds)
        if not (x1 < x2 and y1 < y2 and x2 - x1 <= 64 and y2 - y1 <= 64):
            raise ValueError('Invalid contract bounds')
        for a, b, c, d in (*TOWNS.values(), *rectangles):
            if x1 <= c + margin and x2 >= a - margin and y1 <= d + margin and y2 >= b - margin:
                raise ValueError('Contract bounds overlap an existing or safe zone')
        rectangles.append((x1, y1, x2, y2))
        record['bounds'] = [x1, y1, x2, y2]
        record['levels'] = _pair(record['levels'], 'contract levels', 1, 20)
        record['recommended_party_size'] = _pair(record['recommended_party_size'], 'party size', 2, 4)
        profile = _text(record['map_profile'], 'map profile', 64)
        if not _SLUG.fullmatch(profile):
            raise ValueError('Invalid contract map profile')
        size = record['map_size']
        if not isinstance(size, (tuple, list)) or len(size) != 2:
            raise ValueError('Invalid contract map size')
        record['map_size'] = [_integer(v, 'contract map size', 16, 64) for v in size]
        enemies = record['enemies']
        if not isinstance(enemies, dict) or not enemies or set(enemies) - {'scout', 'rifleman', 'heavy'}:
            raise ValueError('Invalid contract enemies')
        if sum(_integer(v, 'enemy count', 1, 16) for v in enemies.values()) > 24:
            raise ValueError('Invalid total enemy count')
        reward = record['reward']
        if not isinstance(reward, dict) or set(reward) != {'credits', 'experience'}:
            raise ValueError('Invalid contract reward')
        _integer(reward['credits'], 'contract credits', 0, 1_000_000)
        _integer(reward['experience'], 'contract experience', 0, 100_000)
    return result


def load_catalog(path=DEFAULT_CATALOG):
    try:
        return validate_catalog(json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Cannot load contract catalogue') from exc


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS pve_contract_instances (
        id TEXT PRIMARY KEY, party_id TEXT NOT NULL, leader TEXT NOT NULL,
        party_revision INTEGER NOT NULL, town_id INTEGER NOT NULL,
        template_id TEXT NOT NULL, template_version INTEGER NOT NULL,
        catalog_version INTEGER NOT NULL, template_json TEXT NOT NULL,
        seed INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN
        ('accepted','travelling','arrived','active','completed','failed','cancelled','expired')),
        accepted_at REAL NOT NULL, expires_at REAL NOT NULL,
        updated_at REAL NOT NULL, started_at REAL, finished_at REAL,
        match_id TEXT UNIQUE, battle_roster_json TEXT, outcome TEXT)''')
    db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS pve_contract_one_active_party
        ON pve_contract_instances(party_id) WHERE state IN ('accepted','travelling','arrived','active')''')
    db.execute('''CREATE TABLE IF NOT EXISTS pve_contract_members (
        instance_id TEXT NOT NULL, owner TEXT NOT NULL, login TEXT NOT NULL,
        selected_json TEXT NOT NULL, reward_json TEXT NOT NULL,
        PRIMARY KEY(instance_id,owner), UNIQUE(instance_id,login))''')
    db.execute('''CREATE TABLE IF NOT EXISTS pve_contract_locks (
        owner TEXT PRIMARY KEY, login TEXT NOT NULL UNIQUE, instance_id TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS pve_contract_requests (
        party_id TEXT NOT NULL, leader TEXT NOT NULL, request_id TEXT NOT NULL,
        template_id TEXT NOT NULL, instance_id TEXT NOT NULL,
        PRIMARY KEY(party_id,leader,request_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS pve_contract_events (
        instance_id TEXT NOT NULL, sequence INTEGER NOT NULL, state TEXT NOT NULL,
        happened_at REAL NOT NULL, PRIMARY KEY(instance_id,sequence))''')
    db.execute('''CREATE TABLE IF NOT EXISTS pve_contract_awards (
        instance_id TEXT NOT NULL, owner TEXT NOT NULL, login TEXT NOT NULL,
        award_json TEXT NOT NULL, claimed INTEGER NOT NULL DEFAULT 0 CHECK(claimed IN (0,1)),
        claimed_at REAL, PRIMARY KEY(instance_id,login), UNIQUE(instance_id,owner))''')


def _party(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError('Authoritative party snapshot required')
    party = {name: snapshot.get(name) for name in ('id', 'leader', 'town_id', 'state', 'revision', 'members')}
    party['id'] = _party_id(party['id'])
    _text(party['leader'], 'party leader')
    if party['town_id'] is not None:
        _integer(party['town_id'], 'party town', 1, 255)
    if party['state'] not in ('city', 'travelling', 'at_target', 'loading', 'battle'):
        raise ValueError('Invalid party state')
    _integer(party['revision'], 'party revision', 0, 2**63 - 1)
    if not isinstance(party['members'], (list, tuple)) or not 2 <= len(party['members']) <= 4:
        raise ValueError('Contracts require two to four real accounts')
    members, owners, logins = [], set(), set()
    for raw in party['members']:
        if not isinstance(raw, dict):
            raise ValueError('Invalid party member')
        member = {name: raw.get(name) for name in ('owner', 'login', 'selected', 'online', 'ready')}
        owner = _text(member['owner'], 'save owner')
        login = _text(member['login'], 'authenticated login')
        if login.startswith('@character:') or owner in owners or login.casefold() in logins:
            raise ValueError('Each contract member needs a distinct authenticated account')
        # Trusted server snapshots still cannot bind a known slot to another login.
        if owner != login and not (owner.startswith('@character:' + login + ':') and owner.rsplit(':', 1)[1] in ('2', '3', '4', '5')):
            raise ValueError('Party save owner does not belong to its login')
        selected = member['selected']
        if not isinstance(selected, (tuple, list)) or not 1 <= len(selected) <= 2:
            raise ValueError('Choose one or two fighters per contract member')
        member['selected'] = [_integer(actor, 'selected fighter', 1, 2**32 - 1) for actor in selected]
        if len(set(member['selected'])) != len(member['selected']):
            raise ValueError('Duplicate selected fighter')
        if type(member['online']) is not bool or type(member['ready']) is not bool:
            raise ValueError('Invalid party presence or readiness')
        owners.add(owner)
        logins.add(login.casefold())
        members.append(member)
    if party['leader'] not in owners:
        raise ValueError('Party leader is not a member')
    party['members'] = sorted(members, key=lambda member: member['owner'])
    return party


class ContractStore:
    def __init__(self, path, *, clock=time.time, rng=None, catalog_path=DEFAULT_CATALOG, catalog=None, party_store=None):
        self.path, self.clock = path, clock
        self.rng = rng or random.SystemRandom()
        self.policy = load_catalog(catalog_path) if catalog is None else validate_catalog(catalog)
        self.templates = {record['id']: record for record in self.policy['templates']}
        self.party_store = party_store
        with transaction(path) as db:
            schema(db)

    def _now(self):
        value = self.clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Invalid contract clock')
        return value

    def catalog(self):
        return deepcopy(self.policy['templates'])

    def _verified_party(self, db, snapshot):
        supplied = _party(snapshot)
        store = self.party_store
        if store is None and db.execute("SELECT 1 FROM sqlite_master WHERE name='travel_party_groups'").fetchone():
            from .travel_party import PartyStore
            store = PartyStore(self.path, clock=self.clock)
        if store is not None:
            actual = store.snapshot(supplied['id'], connection=db)
            if actual is None or _party(actual) != supplied:
                raise ValueError('Party changed; refresh before using a contract')
        return supplied

    @staticmethod
    def _record(db, identity):
        row = db.execute('''SELECT id,party_id,leader,party_revision,town_id,template_id,
            template_version,catalog_version,template_json,seed,state,accepted_at,
            expires_at,updated_at,started_at,finished_at,match_id,battle_roster_json,outcome
            FROM pve_contract_instances WHERE id=?''', (identity,)).fetchone()
        if row is None:
            return None
        names = ('id', 'party_id', 'leader', 'party_revision', 'town_id', 'template_id',
                 'template_version', 'catalog_version', 'template', 'seed', 'state',
                 'accepted_at', 'expires_at', 'updated_at', 'started_at', 'finished_at',
                 'match_id', 'battle_roster', 'outcome')
        result = dict(zip(names, row))
        result['template'] = json.loads(result['template'])
        result['battle_roster'] = json.loads(result['battle_roster']) if result['battle_roster'] is not None else None
        result['roster'], result['rewards'] = [], []
        for owner, login, selected, reward in db.execute('''SELECT owner,login,selected_json,reward_json
            FROM pve_contract_members WHERE instance_id=? ORDER BY owner''', (identity,)):
            result['roster'].append(dict(owner=owner, login=login, selected=json.loads(selected)))
            result['rewards'].append(dict(owner=owner, login=login, **json.loads(reward)))
        template = result['template']
        a, b, c, d = template['bounds']
        result['target'] = dict(instance_id=identity, zone_id=template['zone_id'], name=template['name'],
                                bounds=template['bounds'][:], x=(a + c) // 2, y=(b + d) // 2,
                                levels=template['levels'][:], map_profile=template['map_profile'])
        return result

    @staticmethod
    def _event(db, identity, state, now):
        sequence = db.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM pve_contract_events WHERE instance_id=?', (identity,)).fetchone()[0]
        db.execute('INSERT INTO pve_contract_events VALUES (?,?,?,?)', (identity, sequence, state, now))

    def _expire(self, db, now, party_id=None):
        sql = "SELECT id FROM pve_contract_instances WHERE state IN ('accepted','travelling','arrived') AND expires_at<=?"
        args = [now]
        if party_id is not None:
            sql += ' AND party_id=?'
            args.append(party_id)
        expired = []
        for (identity,) in db.execute(sql, args).fetchall():
            db.execute("UPDATE pve_contract_instances SET state='expired',outcome='expired',updated_at=?,finished_at=? WHERE id=?", (now, now, identity))
            db.execute('DELETE FROM pve_contract_locks WHERE instance_id=?', (identity,))
            self._event(db, identity, 'expired', now)
            expired.append(self._record(db, identity))
        return expired

    @staticmethod
    def _expiration_due(db, now, party_id=None):
        sql="SELECT 1 FROM pve_contract_instances WHERE state IN ('accepted','travelling','arrived') AND expires_at<=?"
        args=[now]
        if party_id is not None:
            sql+=' AND party_id=?';args.append(party_id)
        return db.execute(sql+' LIMIT 1',args).fetchone() is not None

    @contextmanager
    def _read_after_expiration(self, party_id=None):
        # A negative result and the returned record share one read snapshot.
        # Close it before requesting a writer; never upgrade a read lock.
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN')
            if not self._expiration_due(db,self._now(),party_id):
                yield db
                return
        with transaction(self.path) as db:
            self._expire(db,self._now(),party_id)
            yield db

    def expire(self):
        with closing(connect(self.path)) as db:
            if not self._expiration_due(db,self._now()):return []
        with transaction(self.path) as db:
            return self._expire(db, self._now())

    def get(self, instance_id):
        _text(instance_id, 'contract instance')
        with self._read_after_expiration() as db:
            return self._record(db, instance_id)

    def active(self, party_id):
        party_id = _party_id(party_id)
        with self._read_after_expiration(party_id) as db:
            row = db.execute("SELECT id FROM pve_contract_instances WHERE party_id=? AND state IN ('accepted','travelling','arrived','active')", (party_id,)).fetchone()
            return self._record(db, row[0]) if row else None

    def accept(self, party_snapshot, actor_owner, template_id, request_id):
        _text(actor_owner, 'contract actor')
        _text(template_id, 'template id', 64)
        _text(request_id, 'request id', 128)
        with transaction(self.path) as db:
            party = self._verified_party(db, party_snapshot)
            if actor_owner != party['leader']:
                raise ValueError('Only the party leader can accept a contract')
            previous = db.execute('''SELECT template_id,instance_id FROM pve_contract_requests
                WHERE party_id=? AND leader=? AND request_id=?''', (party['id'], actor_owner, request_id)).fetchone()
            if previous:
                if previous[0] != template_id:
                    raise ValueError('Contract request id reused for another template')
                self._expire(db, self._now(), party['id'])
                return self._record(db, previous[1])
            if template_id not in self.templates:
                raise ValueError('Unknown contract template')
            if party['state'] != 'city' or party['town_id'] is None:
                raise ValueError('Accept a contract while gathered in a city')
            from .cities import CITIES
            if party['town_id'] not in (*CITIES, 9):
                raise ValueError('Contracts can only be accepted in a city')
            if not all(member['online'] for member in party['members']):
                raise ValueError('All contract members must be online')
            now = self._now()
            self._expire(db, now)
            if db.execute("SELECT 1 FROM pve_contract_instances WHERE party_id=? AND state IN ('accepted','travelling','arrived','active')", (party['id'],)).fetchone():
                raise ValueError('Party already has an active contract')
            for member in party['members']:
                if db.execute('SELECT 1 FROM pve_contract_locks WHERE owner=? OR login=?', (member['owner'], member['login'].casefold())).fetchone():
                    raise ValueError('Account already belongs to an active contract')
            template = deepcopy(self.templates[template_id])
            from .contract_scene import freeze_policy
            template['scene_policy'] = freeze_policy(template)
            identity = uuid.uuid4().hex
            seed = _integer(self.rng.randrange(2**63), 'contract seed', 0, 2**63 - 1)
            db.execute('''INSERT INTO pve_contract_instances VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL)''',
                (identity, party['id'], actor_owner, party['revision'], party['town_id'], template_id,
                 template['version'], self.policy['version'], _dump(template), seed, 'accepted',
                 now, now + self.policy['arrival_ttl_seconds'], now))
            for member in party['members']:
                db.execute('INSERT INTO pve_contract_members VALUES (?,?,?,?,?)',
                           (identity, member['owner'], member['login'], _dump(member['selected']), _dump(template['reward'])))
                db.execute('INSERT INTO pve_contract_locks VALUES (?,?,?)', (member['owner'], member['login'].casefold(), identity))
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='travel_party_invitations'").fetchone():
                db.execute('DELETE FROM travel_party_invitations WHERE party_id=?', (party['id'],))
            db.execute('INSERT INTO pve_contract_requests VALUES (?,?,?,?,?)', (party['id'], actor_owner, request_id, template_id, identity))
            self._event(db, identity, 'accepted', now)
            return self._record(db, identity)

    def target_for(self, owner):
        _text(owner, 'save owner')
        with self._read_after_expiration() as db:
            row = db.execute('SELECT instance_id FROM pve_contract_locks WHERE owner=?', (owner,)).fetchone()
            if row is None:
                return None
            record = self._record(db, row[0])
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='travel_party_members'").fetchone():
                if db.execute('SELECT 1 FROM travel_party_members WHERE owner=? AND party_id=?', (owner, record['party_id'])).fetchone() is None:
                    return None
            # Locks are the exact frozen owners, never a login or slot wildcard.
            return deepcopy(record['target']) if record is not None and record['state'] in ACTIVE else None

    def cancel(self, party_snapshot, actor_owner):
        with transaction(self.path) as db:
            party = self._verified_party(db, party_snapshot)
            if actor_owner != party['leader']:
                raise ValueError('Only the party leader can cancel a contract')
            record = self.active(party['id'])
            if record is None:
                return None
            if record['state'] == 'active':
                raise ValueError('An active battle cannot be cancelled')
            return self.transition(record['id'], record['state'], 'cancelled')

    def transition(self, instance_id, expected_state, new_state, *, match_id=None, outcome=None):
        """Server-side CAS; starting a battle requires start(), not this method."""
        _text(instance_id, 'contract instance')
        if expected_state not in ACTIVE or new_state not in ACTIVE | TERMINAL:
            raise ValueError('Invalid contract state')
        if new_state == 'active':
            raise ValueError('Use start with the authoritative party roster')
        with transaction(self.path) as db:
            self._expire(db, self._now())
            record = self._record(db, instance_id)
            if record is None:
                raise ValueError('Unknown contract instance')
            if match_id is not None and match_id != record['match_id']:
                raise ValueError('Contract battle identity mismatch')
            if record['state'] == new_state:
                if outcome is not None and record['outcome'] != outcome:
                    raise ValueError('Contract outcome already frozen')
                return record
            if record['state'] != expected_state or new_state not in TRANSITIONS.get(expected_state, ()):
                raise ValueError('Contract state changed or transition is invalid')
            if new_state == 'completed' and outcome not in (None, 'victory'):
                raise ValueError('Completed contracts require victory')
            if new_state == 'failed' and outcome not in (None, 'defeat', 'aborted'):
                raise ValueError('Invalid failed contract outcome')
            if new_state not in TERMINAL and outcome is not None:
                raise ValueError('Only terminal contracts have an outcome')
            if new_state in ('cancelled', 'expired') and outcome not in (None, new_state):
                raise ValueError('Invalid terminal contract outcome')
            terminal_outcome = ('victory' if new_state == 'completed' else 'defeat' if new_state == 'failed' else new_state) if outcome is None else outcome
            now = self._now()
            db.execute('''UPDATE pve_contract_instances SET state=?,updated_at=?,finished_at=?,outcome=? WHERE id=?''',
                       (new_state, now, now if new_state in TERMINAL else None, terminal_outcome if new_state in TERMINAL else None, instance_id))
            self._event(db, instance_id, new_state, now)
            if new_state in TERMINAL:
                db.execute('DELETE FROM pve_contract_locks WHERE instance_id=?', (instance_id,))
            if new_state == 'completed':
                if not record['match_id'] or record['battle_roster'] is None:
                    raise ValueError('A completed contract needs its frozen battle')
                for member, reward in zip(record['roster'], record['rewards']):
                    award = dict(instance_id=instance_id, match_id=record['match_id'], template_id=record['template_id'],
                                 template_version=record['template_version'], seed=record['seed'], selected=member['selected'],
                                 credits=reward['credits'], experience=reward['experience'], outcome='victory')
                    db.execute('INSERT INTO pve_contract_awards VALUES (?,?,?,?,0,NULL)',
                               (instance_id, member['owner'], member['login'], _dump(award)))
            return self._record(db, instance_id)

    def start(self, instance_id, party_snapshot, actor_owner, match_id):
        _text(instance_id, 'contract instance')
        _text(actor_owner, 'contract actor')
        _text(match_id, 'battle match id', 128)
        with transaction(self.path) as db:
            party = self._verified_party(db, party_snapshot)
            if party['leader'] != actor_owner:
                raise ValueError('Only the party leader can start a contract')
            self._expire(db, self._now())
            record = self._record(db, instance_id)
            if record is None or record['party_id'] != party['id']:
                raise ValueError('Contract does not belong to this party')
            roster = [dict(owner=m['owner'], login=m['login'], selected=m['selected']) for m in party['members']]
            if roster != record['roster']:
                raise ValueError('Contract roster changed; cancel and accept again')
            if record['state'] == 'active':
                if record['match_id'] != match_id:
                    raise ValueError('Contract already started another battle')
                return record
            if record['state'] != 'arrived' or party['state'] not in ('at_target', 'loading'):
                raise ValueError('Party must reach the contract target before battle')
            if not all(m['online'] and m['ready'] for m in party['members']):
                raise ValueError('Every contract member must be online and ready')
            now = self._now()
            db.execute("UPDATE pve_contract_instances SET state='active',match_id=?,battle_roster_json=?,started_at=?,updated_at=? WHERE id=?",
                       (match_id, _dump(roster), now, now, instance_id))
            self._event(db, instance_id, 'active', now)
            return self._record(db, instance_id)

    def pending_awards(self, instance_id):
        _text(instance_id, 'contract instance')
        with transaction(self.path) as db:
            return [dict(owner=owner, login=login, **json.loads(award)) for owner, login, award in db.execute(
                'SELECT owner,login,award_json FROM pve_contract_awards WHERE instance_id=? AND claimed=0 ORDER BY owner', (instance_id,))]

    def claim_award(self, instance_id, owner):
        """Claim once inside the caller's wallet/experience settlement unit.

        A failing wallet write must roll back the enclosing transaction. This
        method intentionally refuses a standalone claim with no settlement unit.
        """
        _text(instance_id, 'contract instance')
        _text(owner, 'save owner')
        if current() is None:
            raise ValueError('Claim an award inside the settlement transaction')
        with transaction(self.path) as db:
            row = db.execute('SELECT login,award_json,claimed FROM pve_contract_awards WHERE instance_id=? AND owner=?', (instance_id, owner)).fetchone()
            if row is None or row[2]:
                return None
            db.execute('UPDATE pve_contract_awards SET claimed=1,claimed_at=? WHERE instance_id=? AND owner=? AND claimed=0', (self._now(), instance_id, owner))
            return dict(owner=owner, login=row[0], **json.loads(row[1]))
