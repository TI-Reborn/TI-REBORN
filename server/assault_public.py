"""Read-only player views of accepted shared assault rewards.

The original83 row+0x220 is confirmed as the weekly clan badge place by the
unchanged native reader and UI renderer. Permanent player medal fields remain
unconfirmed; this module provides a portal view and private native chat adapter.
It never closes a week, creates tables, pays prizes or changes saves. HTTP
callers must resolve account from their authenticated owned character slot.
"""
from contextlib import closing
from datetime import datetime, timezone
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
import time

from tio import clan_benefits as benefits
from tio.achievement_benefits import influence_multiplier as achievement_factor
from tio.premium import state as premium_state
from tio.protocol.chat import decode_send, encode_system_message

MEDALS_PER_PAGE = 20
MAX_MEDAL_PAGE = 10000


class AssaultViewRejected(ValueError):
    pass


def _json(raw, expected):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise AssaultViewRejected('Сохранённый результат штурма повреждён') from error
    if not isinstance(value, expected):
        raise AssaultViewRejected('Сохранённый результат штурма повреждён')
    return value


def _uint(value, maximum=(1 << 53)):
    if type(value) is not int or not 0 <= value <= maximum:
        raise AssaultViewRejected('Некорректное число в результате штурма')
    return value


def _name(value):
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise AssaultViewRejected('Повреждено публичное имя')
    # Original names are ANSI. Control characters cannot enter chat/HTML data.
    return ''.join(c if ord(c) >= 32 else ' ' for c in bytes(value).decode('cp1251', errors='replace'))


def _clan(db, identity):
    if not benefits.exists(db, 'clans'):
        return None
    row = db.execute('SELECT name FROM clans WHERE id=?', (identity,)).fetchone()
    return dict(id=identity, name=_name(row[0]), crest_id=benefits.crest_id(db, identity)) if row else None


def _accepted_event(db, event_id):
    required = ('warfare_events', 'warfare_event_receipts', 'clan_benefit_receipts', 'warfare_scores')
    if not all(benefits.exists(db, table) for table in required):
        return None
    row = db.execute('''SELECT e.ends,e.town,r.receipt,b.request,b.receipt
        FROM warfare_events e JOIN warfare_event_receipts r ON r.event_id=e.id
        JOIN clan_benefit_receipts b ON b.operation='assault' AND b.identity=e.id AND b.account=''
        WHERE e.id=? AND e.finalized=1''', (event_id,)).fetchone()
    if row is None:
        return None
    ends, town, final_raw, request_raw, reward_raw = row
    final, reward = _json(final_raw, dict), _json(reward_raw, dict)
    if type(final.get('benefits_version')) is not int or final['benefits_version'] != 1:
        return None
    if (final.get('event_id') != event_id or reward.get('event_id') != event_id
            or _json(request_raw, dict) != {'event_id': event_id}):
        raise AssaultViewRejected('Подтверждение штурма не соответствует событию')
    if (not isinstance(final.get('scores'), dict)
            or any(not isinstance(clan, str) or not clan.isascii() or not clan.isdecimal()
                   or type(units) is not int for clan, units in final['scores'].items())
            or not isinstance(reward.get('players'), dict) or not isinstance(reward.get('medals'), dict)):
        raise AssaultViewRejected('Повреждён принятый результат штурма')
    totals, contested = {}, {}
    for clan, units, allowed in db.execute('SELECT clan_id,ov_units,contested FROM warfare_scores WHERE event_id=?', (event_id,)):
        if type(clan) is not int or clan <= 0 or type(units) is not int or allowed not in (0, 1):
            raise AssaultViewRejected('Повреждены очки штурма')
        totals[str(clan)] = totals.get(str(clan), 0) + units
        if allowed:
            contested[clan] = contested.get(clan, 0) + units
    if final.get('scores') != totals:
        raise AssaultViewRejected('Очки штурма отличаются от подтверждённого результата')
    return dict(ends=_uint(ends), town=_uint(town, 0xffffffff), reward=reward,
                totals={clan: max(0, units) for clan, units in contested.items()})


def _scores(db, start, cache):
    if not benefits.exists(db, 'clan_assault_totals'):
        return {}
    scores = {}
    for event_id, clan, units in db.execute('SELECT event_id,clan_id,units FROM clan_assault_totals WHERE week_start=?', (start,)):
        event = cache.setdefault(event_id, _accepted_event(db, event_id)) if event_id not in cache else cache[event_id]
        # Orphan/legacy rows never become a new public award or rating.
        if event is None:
            continue
        if benefits.week_start(event['ends'] - 1) != start or event['totals'].get(clan) != units:
            raise AssaultViewRejected('Недельные очки не соответствуют подтверждённому штурму')
        scores[clan] = scores.get(clan, 0) + _uint(units)
    return scores


def _week(db, start, current, cache):
    closed = db.execute('SELECT receipt FROM clan_weeks WHERE week_start=?', (start,)).fetchone() if benefits.exists(db, 'clan_weeks') else None
    if closed and start >= current:
        raise AssaultViewRejected('Текущая неделя не может быть закрыта')
    scores = _scores(db, start, cache)
    if closed:
        source = _json(closed[0], list)
        if len(source) > 20:
            raise AssaultViewRejected('Недельный рейтинг превышает 20 кланов')
    else:
        ranked = sorted(((clan, units) for clan, units in scores.items() if units > 0 and _clan(db, clan)), key=lambda item: (-item[1], item[0]))[:20]
        source = [dict(clan_id=clan, place=place, score=units, rank_per_kill=0) for place, (clan, units) in enumerate(ranked, 1)]
    rows, seen = [], set()
    for index, row in enumerate(source, 1):
        if not isinstance(row, dict) or type(row.get('place')) is not int or row['place'] != index or type(row.get('clan_id')) is not int or row['clan_id'] <= 0 or row['clan_id'] in seen:
            raise AssaultViewRejected('Повреждены места недельного рейтинга')
        clan_id = row['clan_id']; seen.add(clan_id)
        units = _uint(row.get('score'))
        if units <= 0 or scores.get(clan_id) != units:
            raise AssaultViewRejected('Недельный рейтинг не подтверждён результатами штурмов')
        bonus = next(value for limit, value in benefits.policy()['weekly']['rank_per_kill'] if index <= limit) if closed else 0
        if row.get('rank_per_kill') != bonus:
            raise AssaultViewRejected('Награда не соответствует месту недельного рейтинга')
        if closed:
            badge = db.execute('SELECT place,rank_per_kill,starts,expires FROM clan_weekly_badges WHERE week_start=? AND clan_id=?', (start, clan_id)).fetchone() if benefits.exists(db, 'clan_weekly_badges') else None
            if badge != (index, bonus, start + benefits.WEEK, start + 2 * benefits.WEEK):
                raise AssaultViewRejected('Недельный значок не соответствует принятому расчёту')
        clan = _clan(db, clan_id)
        if clan:
            rows.append(dict(clan=clan, place=index, score_units=units,
                             score=str(Fraction(units, 2)), rank_per_kill=bonus))
    return dict(start=start, end=start + benefits.WEEK,
                status='closed' if closed else ('current' if start == current else 'pending'), rows=rows)


def _medals(db, account, page, cache):
    result = []
    if benefits.exists(db, 'clan_assault_medals'):
        for event_id, side, place, factor_raw in db.execute('SELECT event_id,side,place,multiplier FROM clan_assault_medals WHERE account=?', (account,)):
            event = cache.setdefault(event_id, _accepted_event(db, event_id)) if event_id not in cache else cache[event_id]
            if event is None:
                raise AssaultViewRejected('Медаль не подтверждена принятым результатом штурма')
            reward = event['reward']
            if side not in ('attack', 'defense') or type(place) is not int or not 1 <= place <= 3:
                raise AssaultViewRejected('Повреждена награда за штурм')
            try:
                factor = Fraction(factor_raw)
            except (ValueError, TypeError, ZeroDivisionError) as error:
                raise AssaultViewRejected('Повреждён коэффициент медали') from error
            if (factor <= 1 or reward.get('players', {}).get(account) != dict(side=side, place=place)
                    or reward.get('medals', {}).get(account) != factor_raw):
                raise AssaultViewRejected('Медаль отличается от принятой награды')
            result.append(dict(event_id=event_id, town=event['town'], earned_at=event['ends'],
                               side=side, place=place, tier=('gold', 'silver', 'bronze')[place-1],
                               influence_factor=str(factor), permanent=True))
    result.sort(key=lambda row: (-row['earned_at'], row['event_id']))
    factor = max((Fraction(row['influence_factor']) for row in result), default=Fraction(1))
    offset = (page-1) * MEDALS_PER_PAGE
    return dict(page=page, page_size=MEDALS_PER_PAGE, total=len(result),
                has_next=offset + MEDALS_PER_PAGE < len(result), entries=result[offset:offset+MEDALS_PER_PAGE]), factor


def active_badge_places(db, *, now=None):
    """Original 83 row+0x220 accepts the active weekly place, not its bonus.

    The unchanged original clan UI's6e7a48 renderer groups1/2..5/6..10/11..20
    into its four existing badge sprites. Proven by verify_assault_badge_native.
    No unknown field, weekly closure or membership is changed by this reader.
    """
    if not db.in_transaction:
        raise RuntimeError('Assault badge view requires one read transaction')
    stamp = _uint(int(time.time()) if now is None else now)
    current = benefits.week_start(stamp)
    week = _week(db, current-benefits.WEEK, current, {})
    return {row['clan']['id']: row['place'] for row in week['rows']} if week['status'] == 'closed' else {}


def snapshot(db, account, *, now=None, medal_page=1):
    """JSON-safe owned-player view; caller's transaction keeps one SQL snapshot."""
    if not db.in_transaction:
        raise RuntimeError('Assault public view requires one read transaction')
    if not isinstance(account, str) or not account:
        raise AssaultViewRejected('Требуется аккаунт игрока')
    stamp = _uint(int(time.time()) if now is None else now)
    if type(medal_page) is not int or not 1 <= medal_page <= MAX_MEDAL_PAGE:
        raise AssaultViewRejected('Страница медалей: 1–10000')
    character = db.execute('SELECT name FROM characters WHERE account=? ORDER BY slot LIMIT 1', (account,)).fetchone() if benefits.exists(db, 'characters') else None
    if character is None:
        raise AssaultViewRejected('Собственный персонаж не найден')
    member = db.execute('SELECT clan_id FROM clan_members WHERE account=?', (account,)).fetchone() if benefits.exists(db, 'clan_members') else None
    clan = _clan(db, member[0]) if member else None
    current = benefits.week_start(stamp); cache = {}
    previous_week = _week(db, current-benefits.WEEK, current, cache)
    current_week = _week(db, current, current, cache)
    badge = None
    if clan and previous_week['status'] == 'closed':
        winner = next((row for row in previous_week['rows'] if row['clan']['id'] == clan['id']), None)
        if winner:
            badge = dict(week_start=previous_week['start'], place=winner['place'],
                         rank_per_kill=winner['rank_per_kill'], starts=current,
                         expires=current+benefits.WEEK, clan=clan)
    medals, medal = _medals(db, account, medal_page, cache)
    achievement = achievement_factor(db, account)
    kind, _ = premium_state(db, account, stamp)
    premium = Fraction(benefits.policy()['influence']['premium_multiplier']) if kind == benefits.policy()['influence']['premium_kind'] else Fraction(1)
    total = premium*achievement*medal
    if total != benefits.influence_multiplier(db, account, now=stamp):
        raise AssaultViewRejected('Действующий коэффициент не подтверждён наградами')
    return dict(version=1, generated_at=stamp, character_name=_name(character[0]),
                previous_week=previous_week, current_week=current_week,
                player=dict(clan=clan, badge=badge, medals=medals,
                            bonuses=dict(weekly_rank_per_kill=badge['rank_per_kill'] if badge else 0,
                                         medal_influence_factor=str(medal), achievement_influence_factor=str(achievement),
                                         premium_influence_factor=str(premium), influence_factor=str(total),
                                         influence_applies=clan is not None)),
                policy=dict(weekly_boundary='Monday 00:00 UTC', score_unit='half_assault_point',
                            medal_coefficients='emulator_policy', influence_stacking='highest_medal_and_achievement_times_premium',
                            standings='accepted_finalized_contested_assaults_only'))


class AssaultPublicStore:
    def __init__(self, path):
        self.path = Path(path).resolve()

    def snapshot(self, account, *, now=None, medal_page=1):
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            return snapshot(db, account, now=now, medal_page=medal_page)


def private_command(packet):
    if packet[:1] != b'\x21':
        return False
    try:
        _, text, _ = decode_send(packet)
    except ValueError:
        return False
    return text.split(maxsplit=1)[0].casefold() == '!assault'


def _date(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def command(db, account, text, *, now=None):
    """Replies use original 22/channel4, returned only to the requesting socket."""
    tokens = text.casefold().split()
    if not tokens or tokens[0] != '!assault':
        return None
    if tokens[1:] in ([], ['help']):
        lines = ['!assault top — итоги прошлой недели; current — текущая неделя;',
                 '!assault me — значок и бонусы; medals [страница] — ваши медали.',
                 'Рейтинг учитывает принятые результаты завершённых штурмов. Время UTC.']
    else:
        mode = tokens[1]
        if mode not in ('top', 'current', 'me', 'medals') or (mode != 'medals' and len(tokens) != 2) or len(tokens) > 3:
            raise AssaultViewRejected('Неверная команда: !assault help')
        page = 1
        if len(tokens) == 3:
            if not tokens[2].isascii() or not tokens[2].isdecimal():
                raise AssaultViewRejected('Страница медалей: 1–10000')
            page = int(tokens[2])
        value = snapshot(db, account, now=now, medal_page=page)
        if mode in ('top', 'current'):
            week = value['previous_week' if mode == 'top' else 'current_week']
            status = {'closed':'итоги приняты', 'pending':'расчёт ожидается', 'current':'предварительный рейтинг'}[week['status']]
            lines = [f"Штурмовой топ-20: {_date(week['start'])} — {_date(week['end'])}; {status}."]
            lines += [f"{row['place']}. {row['clan']['name'][:64]}: {row['score']} очков; +{row['rank_per_kill']} звания за убийство." for row in week['rows']]
            if not week['rows']:
                lines.append('Подтверждённых результатов нет.')
        elif mode == 'me':
            player = value['player']; badge = player['badge']; bonus = player['bonuses']
            lines = [f"Клан: {player['clan']['name'][:64] if player['clan'] else 'нет'}. Недельный бонус: +{bonus['weekly_rank_per_kill']} звания за убийство."]
            if badge:
                lines.append(f"Штурмовой значок за {badge['place']} место действует до {_date(badge['expires'])}.")
            lines += [f"Влияние: медали ×{bonus['medal_influence_factor']}; достижение ×{bonus['achievement_influence_factor']}; премиум ×{bonus['premium_influence_factor']}.",
                      f"Итого ×{bonus['influence_factor']} до коэффициента города; {'начисляется вашему клану' if bonus['influence_applies'] else 'для начисления нужен клан'}. Медалей: {player['medals']['total']}."]
        else:
            medals = value['player']['medals']
            lines = [f"Ваши медали: {medals['total']}; страница {page}."]
            lines += [f"{'За штурм' if row['side']=='attack' else 'За оборону'}: {row['place']} место, ×{row['influence_factor']}, база {row['town']}, {_date(row['earned_at'])}." for row in medals['entries']]
            if not medals['entries']:
                lines.append('Медалей на этой странице нет.')
            if medals['has_next']:
                lines.append(f'Следующая страница: !assault medals {page+1}')
    return tuple(encode_system_message(4, b'Assault', line[:200]) for line in lines)
