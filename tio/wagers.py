"""Credit-only wager lobbies and durable, transaction-bound escrow.

Manual pp16-17: stakes form the complete prize; no skill/XP/influence/rank
progression, and Start has a cancellable five-second countdown. Equal shares
among eligible winning teammates (remainder in account order) are server policy;
the original manual does not specify its division or a draw prize.
"""
from dataclasses import dataclass, field
import json
import time

from .db_transaction import transaction
from . import market_inventory
from .protocol.arena import encode_create_request

MAX_CREDITS = 0xffffffff
COUNTDOWN_SECONDS = 5


def validate_request(request):
    encode_create_request(request)
    if request.mode not in (0, 1, 4):
        raise ValueError('Ставки доступны в Выживании, Командном бою и Стенке')
    if not 1 <= request.map_size <= 4:
        raise ValueError('Недопустимый размер карты')
    n, soldiers = request.players_count, request.soldiers_count_01
    if (request.mode == 0 and n not in (2, 3, 4)
            or request.mode == 1 and n not in (2, 4, 6, 8)
            or request.mode == 4 and n != 8):
        raise ValueError('Недопустимое число игроков')
    maximum = 1 if request.mode == 4 or n == 8 else 2 if n >= 6 else 3
    if not 1 <= soldiers <= maximum or request.soldiers_count_02 != soldiers:
        raise ValueError('Недопустимое число бойцов')
    if request.unknown_u8_01 != 2 or request.unknown_u32_01 != 20*soldiers+20:
        raise ValueError('Недопустимое время хода или параметры заявки')
    if request.level_range_index not in (0, 1, 2):
        raise ValueError('Разница уровней должна быть ±0, ±1 или ±2')
    if not 1 <= request.stake <= MAX_CREDITS // n:
        raise ValueError('Ставка должна быть положительной и помещаться в призовой фонд')
    return request


def request_data(request):
    return dict(mode=request.mode, map_size=request.map_size,
                players=request.players_count, soldiers=request.soldiers_count_01,
                level_delta=request.level_range_index, stake=request.stake)


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS wager_matches (
        match_id TEXT PRIMARY KEY NOT NULL, settings TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('held','loading','active','settled','refunded')),
        stake INTEGER NOT NULL, pot INTEGER NOT NULL, created_at REAL NOT NULL,
        outcome TEXT, completed_at REAL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS wager_members (
        match_id TEXT NOT NULL, account TEXT NOT NULL, side INTEGER NOT NULL,
        roster TEXT NOT NULL, forfeited INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(match_id,account))''')
    db.execute('''CREATE TABLE IF NOT EXISTS wager_leases (
        account TEXT PRIMARY KEY NOT NULL, match_id TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS wager_receipts (
        match_id TEXT NOT NULL, account TEXT NOT NULL, kind TEXT NOT NULL,
        amount INTEGER NOT NULL, PRIMARY KEY(match_id,account))''')


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def reserve(db, match_id, request, members, *, creator_level, pool, now=None):
    """Hold every real account atomically. Caller owns the transaction.

    members: tuples (account, side, actor_ids, levels), already authenticated and
    revalidated against persistent owned squads by the gameplay service.
    Repeating precisely the same frozen admission is idempotent.
    """
    validate_request(request)
    schema(db)
    members = tuple((a, s, tuple(ids), tuple(levels)) for a, s, ids, levels in members)
    accounts = [m[0] for m in members]
    if (not isinstance(match_id, str) or not match_id or len(match_id) > 128
            or len(members) != request.players_count or len(set(accounts)) != len(accounts)
            or any(not isinstance(a, str) or not a for a in accounts)
            or type(creator_level) is not int or not 1 <= creator_level <= 20):
        raise ValueError('Для ставки нужны разные реальные аккаунты и полный состав')
    low, high = max(1, creator_level-request.level_range_index), min(20, creator_level+request.level_range_index)
    for account, side, ids, levels in members:
        if (type(side) is not int or side < 0 or not 1 <= len(ids) <= request.soldiers_count_01
                or len(set(ids)) != len(ids) or len(ids) != len(levels)
                or any(type(i) is not int or i <= 0 for i in ids)
                or any(type(l) is not int or not low <= l <= high for l in levels)):
            raise ValueError('Состав или уровни бойцов не соответствуют заявке')
    sides = [m[1] for m in members]
    if request.mode == 0:
        if sorted(sides) != list(range(len(members))):
            raise ValueError('В Выживании каждый игрок представляет свою сторону')
    elif set(sides) != {0, 1} or sides.count(0) != sides.count(1):
        raise ValueError('Для командной ставки нужны две равные команды')
    settings = _json(dict(**request_data(request), creator_level=creator_level, pool=pool,
                          members=sorted(members)))
    prior = db.execute('SELECT settings,status FROM wager_matches WHERE match_id=?', (match_id,)).fetchone()
    if prior:
        if prior[0] != settings:
            raise ValueError('Повторная ставка имеет другой состав или параметры')
        if prior[1] not in ('held', 'loading', 'active'):
            raise ValueError('Расчёт этой ставки уже завершён')
        return request.stake * len(members)
    for account in accounts:
        if db.execute('SELECT 1 FROM wager_leases WHERE account=?', (account,)).fetchone():
            raise ValueError('Средства аккаунта уже зарезервированы в другом бою')
        wallet = db.execute('SELECT credits FROM wallets WHERE account=?', (account,)).fetchone()
        if wallet is None or wallet[0] < request.stake:
            raise ValueError('У участника недостаточно кредитов для ставки')
    db.execute('INSERT INTO wager_matches VALUES (?,?,?,?,?,?,NULL,NULL)',
               (match_id, settings, 'held', request.stake, request.stake*len(members), time.time() if now is None else now))
    for account, side, ids, levels in members:
        db.execute('UPDATE wallets SET credits=credits-? WHERE account=?', (request.stake, account))
        db.execute('INSERT INTO wager_members VALUES (?,?,?,?,0)', (match_id, account, side, _json(dict(ids=ids, levels=levels))))
        db.execute('INSERT INTO wager_leases VALUES (?,?)', (account, match_id))
    return request.stake*len(members)


def transition(db, match_id, phase):
    if phase not in ('loading', 'active'):
        raise ValueError('Недопустимое состояние ставки')
    row = db.execute('SELECT status FROM wager_matches WHERE match_id=?', (match_id,)).fetchone()
    if row is None or row[0] not in (('held', 'loading') if phase == 'loading' else ('loading', 'active')):
        raise ValueError('Ставка не готова к запуску')
    db.execute('UPDATE wager_matches SET status=? WHERE match_id=?', (phase, match_id))


def forfeit(db, match_id, account):
    row = db.execute('SELECT status FROM wager_matches WHERE match_id=?', (match_id,)).fetchone()
    if row is None or row[0] not in ('loading', 'active'):
        raise ValueError('Нет активной ставки')
    if db.execute('UPDATE wager_members SET forfeited=1 WHERE match_id=? AND account=?', (match_id, account)).rowcount != 1:
        raise ValueError('Аккаунт не участвовал в ставке')


def settle(db, match_id, report, *, now=None):
    """Distribute the complete pot once inside the battle reward transaction.

    report = {version:1, winner_side:int|None, refund_reason:str|None}.
    Draw/administrative cancellation refunds all stakes. Departed players marked
    by forfeit receive no winning share; dead teammates who stayed still do.
    Returns each account's receipt; repeating another outcome is rejected.
    """
    schema(db)
    if (not isinstance(report, dict) or set(report) != {'version', 'winner_side', 'refund_reason'}
            or report['version'] != 1 or type(report['version']) is not int
            or report['winner_side'] is not None and type(report['winner_side']) is not int
            or report['refund_reason'] is not None and (not isinstance(report['refund_reason'], str) or not report['refund_reason'])
            or report['winner_side'] is not None and report['refund_reason'] is not None):
        raise ValueError('Некорректный расчёт ставки')
    row = db.execute('SELECT status,stake,pot,outcome FROM wager_matches WHERE match_id=?', (match_id,)).fetchone()
    if row is None:
        raise ValueError('Зарезервированная ставка не найдена')
    status, stake, pot, prior = row
    encoded = _json(report)
    if status in ('settled', 'refunded'):
        if prior != encoded:
            raise ValueError('Результат ставки уже зафиксирован иначе')
        return dict((a, (kind, amount)) for a, kind, amount in db.execute(
            'SELECT account,kind,amount FROM wager_receipts WHERE match_id=?', (match_id,)))
    members = db.execute('SELECT account,side,forfeited FROM wager_members WHERE match_id=? ORDER BY account', (match_id,)).fetchall()
    winner = report['winner_side']
    if winner is not None and status != 'active':
        raise ValueError('Не загруженный бой не может иметь победителя')
    if winner is not None and winner not in {side for _, side, _ in members}:
        raise ValueError('Победившая сторона не участвовала в ставке')
    winners = [a for a, side, left in members if side == winner and not left] if winner is not None else []
    if winner is not None and not winners:
        raise ValueError('В победившей команде нет участников, сохранивших ставку')
    amounts = dict.fromkeys((a for a, _, _ in members), 0)
    if winner is None:
        amounts = {a: stake for a, _, _ in members}
    else:
        share, extra = divmod(pot, len(winners))
        amounts.update({a: share+int(i < extra) for i, a in enumerate(winners)})
    if sum(amounts.values()) != pot:
        raise ValueError('Призовой фонд не совпадает с выплатами')
    market_inventory.initialise(db)
    receipts = {}
    for account, amount in amounts.items():
        kind = 'refund' if winner is None else 'win' if account in winners else 'lose'
        market_inventory.credit(db, account, amount)
        db.execute('INSERT INTO wager_receipts VALUES (?,?,?,?)', (match_id, account, kind, amount))
        receipts[account] = (kind, amount)
    db.execute('UPDATE wager_matches SET status=?,outcome=?,completed_at=? WHERE match_id=?',
               ('refunded' if winner is None else 'settled', encoded, time.time() if now is None else now, match_id))
    db.execute('DELETE FROM wager_leases WHERE match_id=?', (match_id,))
    return receipts


def refund(db, match_id, reason):
    return settle(db, match_id, dict(version=1, winner_side=None, refund_reason=reason))


class WagerStore:
    def __init__(self, path):
        self.path = path
        with transaction(path) as db:
            schema(db)

    def recover(self, retained_matches):
        """Refund startup/countdown/load orphans; retain journaled real battles.

        Call only after the battle journal has recovered/quarantined checkpoints.
        Pass quarantined IDs too: repair must retain their pot until its outcome
        is known. A graceful stop refunds unstarted wagers separately.
        """
        retained_matches = set(retained_matches)
        recovered = []
        with transaction(self.path) as db:
            pending = db.execute("SELECT match_id,status FROM wager_matches WHERE status IN ('held','loading','active')").fetchall()
            for match, phase in pending:
                if phase == 'held' or match not in retained_matches:
                    refund(db, match, 'restart_without_battle'); recovered.append(match)
        return tuple(recovered)

    def stop_unstarted(self):
        with transaction(self.path) as db:
            pending = [r[0] for r in db.execute("SELECT match_id FROM wager_matches WHERE status='held'")]
            for match in pending:
                refund(db, match, 'server_stop_before_start')
        return tuple(pending)


@dataclass
class WagerLobby:
    identity: int
    captain: int
    request: object
    creator_level: int
    pool: str
    members: list
    sides: dict
    ready: set = field(default_factory=set)
    match_id: str | None = None
    starts_at: float | None = None
    accounts: dict = field(default_factory=dict)

    @property
    def mode(self): return self.request.mode
    @property
    def soldiers(self): return self.request.soldiers_count_01
    @property
    def band(self): return self.request.level_range_index
    @property
    def capacity(self): return self.request.players_count
    @property
    def wager(self): return True


class WagerLobbies:
    """Lifecycle under the containing TeamArena lock; no synthetic players."""
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock; self.rooms = {}; self.membership = {}; self.next_id = 0x20000000

    def room(self, owner):
        return self.rooms.get(self.membership.get(owner))

    def create(self, owner, account, request, creator_level, pool):
        validate_request(request)
        existing = self.room(owner)
        if existing:
            if existing.captain == owner and existing.request == request:
                return existing
            raise ValueError('Сначала покиньте текущую заявку')
        if any(account in r.accounts.values() for r in self.rooms.values()):
            raise ValueError('Аккаунт уже участвует в заявке со ставкой')
        self.next_id += 1
        room = WagerLobby(self.next_id, owner, request, creator_level, pool, [owner], {owner: 0}, accounts={owner: account})
        self.rooms[room.identity] = room; self.membership[owner] = room.identity
        return room

    def join(self, room_id, owner, account, levels, soldiers, pool):
        room = self.rooms.get(room_id)
        if room is None or room.starts_at is not None:
            raise ValueError('Заявка закрыта или запускается')
        if self.room(owner) is room:
            return room
        if self.room(owner) or any(account in r.accounts.values() for r in self.rooms.values()):
            raise ValueError('Аккаунт уже участвует в заявке')
        if len(room.members) >= room.capacity:
            raise ValueError('Заявка заполнена')
        delta = room.request.level_range_index
        if (pool != room.pool or not 1 <= soldiers <= room.soldiers or not levels
                or any(not max(1, room.creator_level-delta) <= level <= min(20, room.creator_level+delta) for level in levels)):
            raise ValueError('Город, уровень или состав не соответствуют заявке')
        side = len(room.members) if room.mode == 0 else min((0, 1), key=lambda s: (sum(v == s for v in room.sides.values()), s))
        room.members.append(owner); room.accounts[owner] = account; room.sides[owner] = side
        room.ready.clear(); self.membership[owner] = room.identity
        return room

    def transfer(self, captain, target, side):
        room = self.room(captain)
        if room is None or room.captain != captain or room.mode == 0 or side not in (0, 1) or target not in room.members:
            raise ValueError('Изменять команды может только создатель командной заявки')
        if room.starts_at is not None:
            raise ValueError('Сначала отмените запуск битвы')
        room.sides[target] = side; room.ready.clear()
        return room

    def ready(self, owner, ready):
        room = self.room(owner)
        if room is None or type(ready) is not bool:
            raise ValueError('Некорректная готовность')
        if ready: room.ready.add(owner)
        else: room.ready.discard(owner)
        return room

    def validate_start(self, owner):
        room = self.room(owner)
        if room is None or room.captain != owner:
            raise ValueError('Запустить бой может только создатель')
        if len(room.members) != room.capacity or room.ready | {owner} != set(room.members):
            raise ValueError('Все места должны быть заняты готовыми игроками')
        if room.mode != 0 and sum(v == 0 for v in room.sides.values()) != room.capacity//2:
            raise ValueError('Для ставки нужны равные команды')
        return room

    def consume(self, room):
        if self.rooms.get(room.identity) is not room:
            raise ValueError('Заявка изменилась при запуске')
        del self.rooms[room.identity]
        for owner in room.members: self.membership.pop(owner, None)

    def leave(self, owner, target=None):
        room = self.room(owner)
        if room is None: return ()
        target = owner if target is None else target
        if target not in room.members or target != owner and room.captain != owner:
            raise ValueError('Исключать участников может только создатель')
        affected = tuple(room.members)
        if target == room.captain: self.consume(room)
        else:
            room.members.remove(target); room.accounts.pop(target); room.sides.pop(target); room.ready.clear()
            self.membership.pop(target, None)
            if room.mode == 0:
                room.sides = {o: i for i, o in enumerate(room.members)}
        return affected
