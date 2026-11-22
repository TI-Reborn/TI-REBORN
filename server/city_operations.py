"""Typed portal city operations inside the authoritative gameplay process.

External callers supply a verified login and owned slot, never a save-owner
key. Scene admission and item writes share the hub lock and SQLite unit.
"""
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import re
import sqlite3
import time
import xml.etree.ElementTree as ET

from .accounts import identity
from .bank_operations import BANK_ACTION_FIELDS, prepare_bank, execute_bank
from . import city_receipts
from .clan_gameplay import schedule
from .economy_runtime import busy_accounts, city_idle, city_location_idle, city_session_idle, retained_accounts
from tio import bank_economy as bank, clan_benefits as benefits
from tio.character_identity import MAX_CHARACTERS, owner_for_slot
from tio.cities import CITIES
from tio.clans import ClanRejected, membership, require
from tio.db_transaction import transaction
from tio.item_boosters import nontransferable
from tio.market_inventory import owned

ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = re.compile(r'[A-Za-z0-9_-]{16,64}\Z')
EVENT_ID = re.compile(r'[A-Za-z0-9:_-]{1,160}\Z')
COMMON = frozenset(('username', 'slot', 'action', 'requestId'))
ACTION_FIELDS = {
    **BANK_ACTION_FIELDS,
    'base_tax': ('townId', 'tax', 'revision'),
    'base_time': ('townId', 'revision', 'defaultStart', 'chosenStart'),
    'base_fund': ('eventId', 'credits'),
}


class CityError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def number(value, maximum=bank.MAX, *, positive=True):
    if type(value) is not int or not int(positive) <= value <= maximum:
        raise CityError('invalid_request')
    return value


def validate_payload(data, *, action=False):
    if not isinstance(data, dict): raise CityError('invalid_request')
    fields = {'username', 'slot'}
    if action:
        kind = data.get('action')
        if not isinstance(kind, str) or kind not in ACTION_FIELDS:
            raise CityError('invalid_request')
        fields = COMMON | set(ACTION_FIELDS[kind])
        if not isinstance(data.get('requestId'), str) or not REQUEST_ID.fullmatch(data['requestId']):
            raise CityError('invalid_request')
    if set(data) != fields: raise CityError('invalid_request')
    try: identity(data['username'])
    except (TypeError, ValueError): raise CityError('invalid_request') from None
    number(data['slot'], MAX_CHARACTERS)
    if not action: return data
    kind = data['action']
    for field in ACTION_FIELDS[kind]:
        if field in ('pin', 'recipientName', 'eventId', 'remove'): continue
        number(data[field], 2**53 if field in ('defaultStart', 'chosenStart') else bank.MAX,
               positive=field not in ('tax', 'revision'))
    if kind == 'base_tax': number(data['tax'], 10, positive=False)
    if kind == 'mark': number(data['days'], bank.policy()['marks']['maximum_days'])
    if 'pin' in data:
        try: bank._pin(data['pin'])
        except bank.BankRejected: raise CityError('invalid_request') from None
    if kind == 'lend':
        from .bank_gameplay import PUBLIC_NAME
        if not isinstance(data['recipientName'], str) or not PUBLIC_NAME.fullmatch(data['recipientName']):
            raise CityError('invalid_request')
    if kind == 'reclaim' and type(data['remove']) is not bool: raise CityError('invalid_request')
    if kind == 'base_fund' and (not isinstance(data['eventId'], str) or not EVENT_ID.fullmatch(data['eventId'])):
        raise CityError('invalid_request')
    return data


@lru_cache(maxsize=1)
def item_names():
    return {int(item.get('id')): item.get('name', str(item.get('id')))[:120]
            for item in ET.parse(ROOT / 'evidence/items_diagnostic.xml').getroot()}


def public_name(db, owner):
    row = db.execute('SELECT name FROM characters WHERE account=? AND slot=1', (owner,)).fetchone()
    return bytes(row[0]).decode('cp1251') if row else None


def quotes(db, now):
    """Project current prices with the same policy, without advancing SQL history."""
    policy = bank.policy();date = datetime.fromtimestamp(now, timezone.utc)
    values = {}
    for kind in ('stocks', 'bonds'):
        row = db.execute('SELECT price,period FROM bank_quotes WHERE kind=?', (kind,)).fetchone() if bank.table(db, 'bank_quotes') else None
        period = now // 86400 if kind == 'stocks' else date.year * 12 + date.month
        p = policy[kind]
        initial = p['initial_credits'] if kind == 'stocks' else p['initial_redemption_credits']
        rise = p['daily_rise_credits'] if kind == 'stocks' else p['monthly_rise_credits']
        values[kind] = min(bank.MAX, row[0] + max(0, period-row[1]) * rise) if row else initial
    p = policy['bonds'];month = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # The field name is part of the website's strict contract; the value is
    # a credit price, as everywhere in the economy.
    return dict(stocks=dict(price=values['stocks'], currency='credits'), bonds=dict(
        priceGold=p['credits_each'], redemptionCredits=values['bonds'], saleOpen=date.day <= p['sale_last_day'],
        redemptionOpen=date.day == p['redemption_day'], saleEnds=int(month.replace(day=p['sale_last_day']+1).timestamp()),
        redemptionStarts=int(month.replace(day=p['redemption_day']).timestamp()),
        redemptionEnds=int(month.replace(day=p['redemption_day']+1).timestamp())))


class CityOperations:
    def __init__(self, router, *, clock=time.time):
        self.router, self.path, self.clock = router, Path(router.config.database), clock

    def _running(self):
        if self.router.server.stopping.is_set(): raise CityError('service_unavailable', 503)

    def _resolve(self, db, data, *, optional=False):
        if not db.execute('SELECT 1 FROM accounts WHERE login=?', (data['username'],)).fetchone():
            raise CityError('account_not_found', 404)
        try: return owner_for_slot(db, data['username'], data['slot'])
        except ValueError:
            if optional: return None
            raise CityError('character_required', 409) from None

    def _available(self, db, owner, blocked, *, unselected: set[str] | None = None):
        if owner in blocked: return False, 'battle_or_search'
        if bank.table(db, 'battle_failure_audit') and db.execute('SELECT 1 FROM battle_failure_audit WHERE account=? AND resolved=0', (owner,)).fetchone():
            return False, 'battle_or_search'
        if not bank.table(db, 'character_locations'): return False, 'city_required'
        row = db.execute('SELECT town_id FROM character_locations WHERE account=?', (owner,)).fetchone()
        if row is None or row[0] not in CITIES: return False, 'city_required'
        if bank.table(db, 'map_journeys') and db.execute('SELECT 1 FROM map_journeys WHERE account=?', (owner,)).fetchone():
            return False, 'travelling'
        if bank.table(db, 'world_prison') and db.execute('SELECT 1 FROM world_prison WHERE account=? AND remaining>0', (owner,)).fetchone():
            return False, 'city_required'
        if unselected is not None:
            return (False, 'session_not_idle') if owner in unselected else (True, None)
        with self.router.lock: sessions = tuple(self.router.active_accounts.values())
        for session in sessions:
            if getattr(session, 'account', None) == owner:
                if getattr(session, 'probe_character_id', None) is None or not city_idle(session):
                    return False, 'session_not_idle'
        return True, None

    def _bases(self, db, clan, owner, allowed, now):
        if not benefits.exists(db, 'territory_claims'): return []
        config = json.loads((ROOT / 'config/territories.json').read_text())
        supported = {row['id']: row for row in config['territories'] if row['enabled'] and row['kind']=='base'}
        wallet=db.execute('SELECT credits FROM wallets WHERE account=?',(owner,)).fetchone() if owner and benefits.exists(db,'wallets') else None
        rows = []
        from tio.base_fund_completion import eligible_event
        for town, tax, revision,base_owner in db.execute('SELECT location,tax_percent,revision,owner_clan FROM territory_claims ORDER BY location'):
            if town not in supported: continue
            benefits.base_claim(db, town)
            leader = bool(clan and clan['id']==base_owner and clan['leader']==owner)
            owned = bool(clan and clan['id']==base_owner)
            try:
                default, options = schedule(db, town, now)
                chosen = benefits.scheduled_start(db, town, default)
            except ClanRejected: default = chosen = None; options = ()
            events = []
            if benefits.exists(db, 'warfare_events'):
                for event, phase, starts, ends, frozen, finalized in db.execute(
                    'SELECT id,phase,starts,ends,claim,finalized FROM warfare_events WHERE town=? ORDER BY starts DESC LIMIT 8', (town,)):
                    claim = json.loads(frozen)
                    fund = db.execute('SELECT credits FROM clan_defense_funds WHERE event_id=?', (event,)).fetchone() if benefits.exists(db, 'clan_defense_funds') else None
                    events.append(dict(id=event, phase=phase, starts=starts, ends=ends, fund=fund[0] if fund else 0,
                        canFund=bool(allowed and wallet and wallet[0]>0 and eligible_event(db,event,now=now))))
            if not owned and not any(event['canFund'] for event in events):continue
            tax_frozen = benefits.exists(db, 'warfare_events') and db.execute('SELECT 1 FROM warfare_events WHERE town=? AND finalized=0', (town,)).fetchone()
            rows.append(dict(townId=town, name=supported[town]['name'], tax=tax, revision=revision,
                canSetTax=bool(allowed and leader and not tax_frozen), canSetTime=bool(allowed and leader and options),
                defaultStart=default, chosenStart=chosen, timeOptions=[stamp for stamp in options if stamp>now], events=events))
        return rows

    def _status(self, db, data, owner, blocked, now, *, unselected: set[str] | None = None):
        characters = []
        for slot in range(1, MAX_CHARACTERS+1):
            try: selected = owner_for_slot(db, data['username'], slot)
            except ValueError: continue
            characters.append(dict(slot=slot, name=public_name(db, selected)))
        wallet = db.execute('SELECT credits,gold FROM wallets WHERE account=?', (owner,)).fetchone() if owner and bank.table(db, 'wallets') else None
        allowed, reason = self._available(db, owner, blocked, unselected=unselected) if owner else (False, 'character_required')
        if owner and not wallet: allowed, reason = False, 'wallet_required'
        town = db.execute('SELECT town_id FROM character_locations WHERE account=?', (owner,)).fetchone() if owner and bank.table(db, 'character_locations') else None
        items = []; marks = []; held = None
        if wallet:
            bank.owner(db, owner)
            all_items = owned(db, owner)
            eligible_items=[]
            for instance, (item, pet, _) in sorted(all_items.items()):
                eligible = (item.count==1 and item.template_id not in (1,2,51) and not nontransferable(item.template_id)
                            and not any(item.unknown_bytes_02[2:]) and item.optional_u32 is None)
                if not eligible:continue
                eligible_items.append((instance,item,pet))
            eligible_items.sort(key=lambda row:(row[2] is None,row[0]))
            for instance,item,pet in eligible_items[:200]:
                items.append(dict(instanceId=instance, templateId=item.template_id, name=item_names().get(item.template_id, str(item.template_id)),
                    upgrade=item.unknown_bytes_03[0], location='warehouse' if pet is None else 'mercenary', canMark=allowed))
            for row in bank.marked_items(db, owner):
                holder_allowed, _ = self._available(db, row['holder'], blocked, unselected=unselected)
                active = row['state']=='active'
                marks.append(dict(id=row['id'], templateId=row['template'], name=item_names().get(row['template'], str(row['template'])),
                    holderName=public_name(db, row['holder']), expires=row['expires'], state=row['state'],
                    canLend=bool(allowed and active and row['expires']>now and row['holder']==owner),
                    canReclaim=bool(allowed and holder_allowed and active)))
            held = db.execute('SELECT stocks,bonds FROM bank_securities WHERE account=?', (owner,)).fetchone() if bank.table(db, 'bank_securities') else None
        clan = membership(db, owner) if owner else None
        bases = self._bases(db, clan, owner, allowed, now)
        p = bank.policy()['marks']
        return dict(username=data['username'], slot=data['slot'], characters=characters, character=public_name(db, owner) if owner else None,
            city=dict(id=town[0] if town else None, name=CITIES[town[0]].name if town and town[0] in CITIES else None, idle=allowed, reason=reason),
            canOperate=allowed, balances=dict(credits=wallet[0], gold=wallet[1]) if wallet else None,
            securities=dict(stocks=held[0] if held else 0, bonds=held[1] if held else 0), quotes=quotes(db, now),
            conversion=dict(creditsPerGold=bank.policy()['gold_to_credits']),
            markPolicy=dict(maximumDays=p['maximum_days'], creditsPerDay=p['credits_per_day'], pinMinDigits=p['pin_digits'][0], pinMaxDigits=p['pin_digits'][1]),
            items=items, itemsLimit=200, itemsHasMore=bool(wallet and len(eligible_items)>200), marks=marks,
            marksLimit=100, marksHasMore=bool(wallet and bank.table(db,'bank_item_marks') and
                db.execute('SELECT COUNT(*) FROM bank_item_marks WHERE owner=?',(owner,)).fetchone()[0]>100),
            clan=dict(id=clan['id'], name=clan['name'].decode('cp1251'), credits=clan['credits'], isLeader=clan['leader']==owner) if clan else None,
            bases=bases)

    @contextmanager
    def status_snapshot(self) -> Iterator[tuple[sqlite3.Connection, set[str], set[str]]]:
        self._running()
        hub = self.router.team_arena
        with hub.lock:
            self._running()
            blocked = set(hub.private)
            blocked.update(account for account in hub.account_owners if hub.retained(account))
            with self.router.lock:
                sessions = tuple(self.router.active_accounts.values())
            unselected = set()
            locations = {}
            for session in sessions:
                account = getattr(session, 'account', None)
                if not account:
                    continue
                if getattr(session, 'probe_character_id', None) is None:
                    unselected.add(account)
                elif not getattr(session, 'locations', None) or not city_session_idle(session, include_assault=False):
                    blocked.add(account)
                else:
                    locations[account] = session.locations

        # Status is advisory. Actions recheck eligibility with the live hub and writer held.
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            blocked.update(retained_accounts(db))
            assault = getattr(hub, 'assault_store', None)
            for account, location in locations.items():
                if account not in blocked and (not city_location_idle(location, account, connection=db)
                        or assault and assault.own_group(account, connection=db) is not None):
                    blocked.add(account)
            yield db, blocked, unselected
        self._running()

    def status(self, data):
        validate_payload(data)
        with self.status_snapshot() as (db, blocked, unselected):
            owner = self._resolve(db, data, optional=True)
            return self._status(db, data, owner, blocked, int(self.clock()), unselected=unselected)

    def _base_action(self, db, owner, data, now):
        action=data['action'];request_id=data['requestId']
        if action=='base_fund':
            benefits.write(db);payload=benefits.canonical(dict(event=data['eventId'], amount=data['credits']))
            old=benefits.prior(db, 'fund', request_id, owner, payload)
            return benefits.fund_defense(db, owner, data['eventId'], data['credits'], request_id,now=now), old is not None
        clan=require(db,owner,leader=True)
        town=data['townId'];claim=benefits.base_claim(db, town)
        if claim[0]!=clan['id']: raise ClanRejected('База принадлежит другому клану')
        supported=json.loads((ROOT/'config/territories.json').read_text())['territories']
        if not any(row['id']==town and row['enabled'] and row['kind']=='base' for row in supported):
            raise ClanRejected('Неизвестная действующая база')
        benefits.write(db)
        payload=benefits.canonical({key:data[key] for key in ACTION_FIELDS[action]})
        old=benefits.prior(db, 'city_'+action, request_id, owner, payload)
        if old is not None:return old, True
        if claim[2]!=data['revision']: raise ClanRejected('Ревизия изменилась')
        if action=='base_tax':
            new=benefits.set_base_tax(db, owner, town, data['tax'], expected_revision=data['revision'])
            result=dict(townId=town, tax=data['tax'], revision=new)
        else:
            default, options=schedule(db, town, now)
            if data['defaultStart']!=default or data['chosenStart'] not in options:raise ClanRejected('Окно штурма изменилось')
            chosen=benefits.set_next_assault(db, owner, town, default, data['chosenStart'], now=now)
            result=dict(townId=town, chosenStart=chosen, revision=claim[2])
        return benefits.receipt(db, 'city_'+action, request_id, owner, payload, result), False

    def _bank_action(self, db, owner, data, blocked, now):
        def require_recipient(connection, target):
            if not self._available(connection, target, blocked)[0]:
                raise CityError('recipient_unavailable', 409)
        kind=data['action']
        command=prepare_bank(kind,data['requestId'],{key:data[key] for key in BANK_ACTION_FIELDS[kind] if key!='pin'})
        return execute_bank(command,db=db,path=self.path,owner=owner,allowed=True,
                            blocked=frozenset(blocked),now=now,pin=data.get('pin'),require_recipient=require_recipient)

    def action(self, data):
        validate_payload(data, action=True);self._running();changed=()
        try:
            with self.router.team_arena.lock:
                with transaction(self.path) as db:
                    self._running();owner=self._resolve(db, data);bank.owner(db, owner)
                    blocked=busy_accounts(self.router, db)
                    if not self._available(db, owner, blocked)[0]:raise CityError('city_unavailable', 409)
                    now=int(self.clock())
                    accepted=city_receipts.before(db,owner,data)
                    if accepted is not None:
                        return dict(status=self._status(db,data,owner,blocked,now),receipt=accepted,replayed=True)
                    outcome=None
                    if data['action'].startswith('base_'):
                        result,replayed=self._base_action(db, owner, data, now)
                    else:
                        outcome=self._bank_action(db, owner, data, blocked, now)
                        result,replayed=outcome.as_dict(),outcome.replayed
                    if 'rejected' in result:
                        # Failed PIN budgets are committed as ordinary results.
                        response=dict(error='pin_rejected', retryAfter=result.get('retry_after', 0))
                    else:
                        changed=(outcome.changed_owners if outcome is not None else
                                 tuple(result.get('changed_accounts', (owner,))) if not replayed else ())
                        credits_delta=gold_delta=0;kind=data['action']
                        if kind=='convert':credits_delta=result['credits_received'];gold_delta=-result['gold_spent']
                        elif kind=='mark':credits_delta=-result['charged']
                        elif kind=='base_fund' and result.get('payer')=='player_credits':credits_delta=-result['charged_credits']
                        elif kind in ('stocks_buy','stocks_sell','bonds_sell'):
                            credits_delta=result['amount']*(-1 if kind=='stocks_buy' else 1)
                        elif kind=='bonds_buy':credits_delta=-result['amount']
                        safe=dict(requestId=data['requestId'],action=kind,creditsDelta=credits_delta,goldDelta=gold_delta)
                        city_receipts.accept(db,owner,data,safe)
                        response=dict(status=self._status(db, data, owner, blocked, now), receipt=safe, replayed=replayed)
                if changed:
                    with self.router.lock:
                        for session in self.router.active_accounts.values():
                            if getattr(session, 'account', None) in changed:session._economy_inventory_digest=None
                return response
        except (bank.BankRejected, ClanRejected):raise CityError('operation_rejected', 409) from None
