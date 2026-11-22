"""Persistent lesson facts for the active character's Reservation quests."""
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from sqlite3 import Connection
from typing import Literal, TypedDict

from .db_transaction import Lease, connect, transaction

TOWN = 3
ARMOR = (245, 246, 247)
WEAPON = 1 << len(ARMOR)
COMPLETE = (WEAPON << 1) - 1
Status = Literal['locked', 'available', 'active', 'ready', 'done']


class State(TypedDict):
    welcome: Status
    survival: Status
    purchases: list[int]
    weapon: bool
    outcome: int | None


def schema(db: Connection | Lease) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS reservation_quests (
        account TEXT PRIMARY KEY, stage INTEGER NOT NULL CHECK(stage BETWEEN 1 AND 4),
        purchases INTEGER NOT NULL DEFAULT 0, outcome INTEGER
    )''')


def _state(db: Connection | Lease, account: str) -> State:
    row = db.execute('SELECT stage,purchases,outcome FROM reservation_quests WHERE account=?',
                     (account,)).fetchone()
    stage, purchases, outcome = row or (0, 0, None)
    welcome: Status = 'available' if stage == 0 else 'done' if stage >= 2 else (
        'ready' if purchases == COMPLETE else 'active')
    survival: Status = 'locked' if stage < 2 else 'available' if stage == 2 else (
        'done' if stage == 4 else 'ready' if outcome == 1 else 'active')
    return dict(welcome=welcome, survival=survival, weapon=bool(purchases & WEAPON),
                purchases=[item for index, item in enumerate(ARMOR) if purchases & (1 << index)],
                outcome=outcome)


def state(path: str | Path, account: str) -> State:
    with closing(connect(path)) as db:
        return _state(db, account)


def act(path: str | Path, account: str, action: str) -> State:
    with transaction(path) as db:
        before = _state(db, account)
        if action == 'accept_welcome':
            db.execute('INSERT OR IGNORE INTO reservation_quests(account,stage) VALUES (?,1)', (account,))
        elif action == 'turn_in_welcome':
            if before['welcome'] not in ('ready', 'done'):
                raise ValueError('Сначала купите три детали Heavy Combat и оружие')
            db.execute('UPDATE reservation_quests SET stage=2 WHERE account=? AND stage=1', (account,))
        elif action == 'accept_survival':
            if before['survival'] == 'locked':
                raise ValueError('Сначала сдайте «Добро пожаловать в пустошь»')
            db.execute('UPDATE reservation_quests SET stage=3 WHERE account=? AND stage=2', (account,))
        elif action == 'turn_in_survival':
            if before['survival'] not in ('ready', 'done'):
                raise ValueError('Сначала победите в режиме «Выживание»')
            db.execute('UPDATE reservation_quests SET stage=4 WHERE account=? AND stage=3', (account,))
        else:
            raise ValueError('Неизвестное действие Рут Восс')
        return _state(db, account)


def purchase(db: Connection | Lease, account: str, template: int, *, town: int, weapon: bool) -> None:
    if town != TOWN:
        return
    bit = 1 << ARMOR.index(template) if template in ARMOR else WEAPON if weapon else 0
    if bit:
        db.execute('UPDATE reservation_quests SET purchases=purchases|? WHERE account=? AND stage=1',
                   (bit, account))


def active_survivors(path: str | Path, accounts: Iterable[str]) -> set[str]:
    with closing(connect(path)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='reservation_quests'").fetchone():
            return set()
        return {account for account in accounts if db.execute(
            'SELECT 1 FROM reservation_quests WHERE account=? AND stage=3 AND outcome IS NOT 1',
            (account,)).fetchone()}


def survival_result(db: Connection, account: str, result: int) -> None:
    db.execute('UPDATE reservation_quests SET outcome=? WHERE account=? AND stage=3 AND outcome IS NOT 1',
               (result, account))
