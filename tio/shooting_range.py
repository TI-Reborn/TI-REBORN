"""Native practice lobby and persistent daily admission, separate from PvP rewards."""

from .db_transaction import connect
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from .locations import SHOOTING_RANGE
from .protocol.arena import (ArenaCreateRequest, BattleSettings, decode_room_start,
                            encode_battle_settings_body)
from .protocol.battle_members import BattleMemberRecord, encode_battle_members
from .protocol.asset_count import encode_asset_count
from .wallets import WalletStore

POLICY = json.loads((Path(__file__).resolve().parents[1]/'config/shooting_range.json').read_text())
# 6e8f50 -> a0a79c: mode16, seven zero arguments, fixed soldier byte1.
CREATE_REQUEST = bytes.fromhex('1f100000000000000000010000000000')


def token_assets(db, account, assets, now=None):
    """Project token balances onto every wallet reply, including after purchases."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='range_accounts'").fetchone():
        return assets
    row = db.execute('SELECT used_day,golden FROM range_accounts WHERE account=?', (account,)).fetchone()
    if row is None:
        return assets
    day = int((time.time() if now is None else now)//86400)
    return replace(assets, slug=int(row[0] < day), gold_slug=row[1])


class AdmissionStore:
    def __init__(self, path, *, clock=time.time):
        self.path, self.clock = path, clock
        WalletStore(path)
        with closing(connect(path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS range_accounts (
                account TEXT PRIMARY KEY, used_day INTEGER NOT NULL DEFAULT -1,
                golden INTEGER NOT NULL DEFAULT 0 CHECK(golden>=0),
                credit_day INTEGER NOT NULL DEFAULT -1, credit_visits INTEGER NOT NULL DEFAULT 0)''')
            db.execute('''CREATE TABLE IF NOT EXISTS range_visits (
                id TEXT PRIMARY KEY, account TEXT NOT NULL, payment INTEGER NOT NULL,
                price INTEGER NOT NULL, started REAL NOT NULL)''')

    def assets(self, account):
        assets = WalletStore(self.path).ensure(account)
        with closing(connect(self.path)) as db, db:
            db.execute('INSERT OR IGNORE INTO range_accounts(account) VALUES (?)', (account,))
            return token_assets(db, account, assets, self.clock())

    def quote(self, account):
        assets = self.assets(account)
        day = int(self.clock()//86400)
        with closing(connect(self.path)) as db:
            credit_day, used = db.execute('SELECT credit_day,credit_visits FROM range_accounts WHERE account=?', (account,)).fetchone()
        flags = bytes((assets.slug>0, assets.gold_slug>0,
                       assets.credits>=POLICY['credits_price'] and (credit_day!=day or used<POLICY['credit_visits_per_day']),
                       False))
        return flags, POLICY['credits_price'], 0

    def pay(self, account, selection, visit):
        if selection not in (0,1,2):
            raise ValueError('Choose a practice payment')
        self.assets(account)
        now = self.clock(); day = int(now//86400)
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT account,payment FROM range_visits WHERE id=?', (visit,)).fetchone()
            if prior:
                if prior != (account, selection):raise ValueError('Visit identity mismatch')
                return
            used, golden, credit_day, visits = db.execute('SELECT used_day,golden,credit_day,credit_visits FROM range_accounts WHERE account=?', (account,)).fetchone()
            price = 0
            if selection == 0:
                if used >= day:raise ValueError('Daily practice token already used')
                db.execute('UPDATE range_accounts SET used_day=? WHERE account=?', (day,account))
            elif selection == 1:
                if golden < 1:raise ValueError('No golden practice token')
                db.execute('UPDATE range_accounts SET golden=golden-1 WHERE account=?', (account,))
            else:
                if selection == 2 and credit_day == day and visits >= POLICY['credit_visits_per_day']:
                    raise ValueError('Daily credit practice limit reached')
                column = 'credits' if selection == 2 else 'gold'
                price = POLICY[column+'_price']
                if db.execute(f'UPDATE wallets SET {column}={column}-? WHERE account=? AND {column}>=?', (price,account,price)).rowcount != 1:
                    raise ValueError('Insufficient practice funds')
                if selection == 2:
                    db.execute('UPDATE range_accounts SET credit_day=?,credit_visits=? WHERE account=?', (day,visits+1 if credit_day==day else 1,account))
            db.execute('INSERT INTO range_visits VALUES (?,?,?,?,?)', (visit,account,selection,price,now))


class Practice:
    def __init__(self, field, owner, targets, clock):
        self.owner, self.targets, self.clock = owner, frozenset(targets), clock
        self.deadline = clock()+POLICY['session_seconds']
        self.field = field

    def complete(self):
        field = self.field
        return (self.clock() >= self.deadline or
                not any(field.actor(i).health>0 for i in self.targets) or
                not field.living_actor_ids(self.owner) or
                max((field._ability_turns[i] for i in field.actor_ids(self.owner)), default=0)>POLICY['max_turns'])

    def validate_attack(self, victims):
        if self.complete():raise ValueError('Practice is over')
        if not victims or any(v.actor_id not in self.targets for v in victims):
            raise ValueError('Practice attacks must target range dummies only')


class ShootingRangeService:
    def __init__(self, path, arena, locations, *, clock=time.time):
        self.path, self.arena, self.locations, self.clock = path, arena, locations, clock
        self.admission = AdmissionStore(path, clock=clock)

    def settings(self, account, name, count):
        return b'\x6c'+encode_battle_settings_body(BattleSettings(
            1,1,16,20*count+20,2,name,bytes((1,20,count,0,1)),0,0,self.admission.quote(account)))

    def handle(self, account, character, name, packet, *, searching=False):
        room = next((r for r in self.arena.rooms.snapshot() if character in r.members), None)
        creating = packet[:2] == b'\x1f\x10'
        starting = packet[:1] == b'\x2e' and room is not None and room.request.mode == 16
        if not creating and not starting:return None
        if self.locations.current(account) != SHOOTING_RANGE or self.locations.travelling(account):
            raise ValueError('Travel to Shooting Range first')
        if searching:raise ValueError('Cancel matchmaking before practicing')
        if room is not None and (room.request.mode != 16 or room.room_id in self.arena._loading):
            if starting and room.request.mode == 16:
                decode_room_start(packet, mode=16)
                return None, ()  # repeated Start cannot charge or reset a live session
            raise ValueError('Already in battle')
        from .owned_pets import OwnedPetStore
        from .matchmaking import SurvivalQueue
        ticket = SurvivalQueue().join(character, OwnedPetStore(self.path).list(account))
        count = len(ticket.actors)
        if creating:
            if packet != CREATE_REQUEST:raise ValueError('Invalid native practice request')
            settings = self.settings(account,name,count)
            from .arena_roster import room_soldiers
            record = BattleMemberRecord(character,name,0,bytes((min(ticket.levels),max(ticket.levels),0,0,1,1)),
                                       room_soldiers(OwnedPetStore(self.path).list(account),count,path=self.path,account=account))
            members = encode_battle_members(16,0,(record,))
            if room is None:
                room = self.arena.rooms.create(character,ArenaCreateRequest(16,0,1,2,20*count+20,count,count,0,0))
            self.arena._records[character] = record
            self.arena._return_towns[character] = SHOOTING_RANGE
            return None, (settings,members)
        wire_payment = decode_room_start(packet,mode=16)
        # Native Start callback81db34 maps both token rows to0, credits to1,
        # gold to2. The server uses the daily token before stored golden tokens.
        selection = ((0 if self.admission.assets(account).slug else 1)
                     if wire_payment == 0 else wire_payment+1)
        from .abilities import AbilityCatalog,AbilityLevel
        from tools.shooting_range_scene import prepare_range
        source = json.loads((Path(__file__).resolve().parents[1]/'config/abilities.json').read_text())
        catalog = AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
        prepared = prepare_range(self.path,account,ticket,catalog,clock=self.clock)
        visit = str(uuid4())
        # Preparation/serialization precedes payment. No fallible scene work follows payment.
        self.admission.pay(account,selection,visit)
        self.arena._loading[room.room_id] = set()
        self.arena._fields[room.room_id] = prepared.field
        self.arena._match_ids[room.room_id] = visit
        self.arena._completed.discard(character)
        prepared.field.result_view = prepared.visibility
        self.arena._scene_headers[room.room_id]=(self.settings(account,name,count),
            encode_battle_members(16,0,(self.arena._records[character],)),prepared.packets[0])
        return (room,prepared), (encode_asset_count(self.admission.assets(account)),*prepared.packets)


from server.battle_journal import private_service
ShootingRangeService.handle=private_service(ShootingRangeService.handle)
