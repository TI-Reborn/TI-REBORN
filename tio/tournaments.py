"""Eight entrants play three rounds, including all four placement matches."""
from contextlib import closing
from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import sqlite3
import time

from .db_transaction import transaction
from .mail import MailStore
from .protocol.item_list import ItemRecord

SIZE = 8
ROUNDS = 3
PAIRS = SIZE // 2
# The 2012 announcement gives the top payout and prize type. Intermediate amounts
# and item counts are emulator policy because the original prize image is unavailable.
PRIZES = ((45_000, 3), (35_000, 2), (25_000, 1), (20_000, 0),
          (15_000, 0), (10_000, 0), (7_500, 0), (5_000, 0))
VISION_INJECTION = 35
PRIZE_SUBJECT = 'Награда за турнир'


@dataclass
class Bracket:
    slots: tuple[str | None, ...]
    winners: dict[tuple[int, int], int] = field(default_factory=dict)

    @classmethod
    def create(cls, accounts: tuple[str, ...]) -> 'Bracket':
        if not 1 <= len(accounts) <= SIZE or len(set(accounts)) != len(accounts):
            raise ValueError('A bracket needs one to eight distinct accounts')
        return cls(accounts + (None,) * (SIZE - len(accounts)))

    def pairs(self, stage: int) -> tuple[tuple[int, int], ...]:
        if not 0 <= stage < ROUNDS:
            raise ValueError('Invalid tournament round')
        if stage == 0:
            return tuple((i, i + 1) for i in range(0, SIZE, 2))
        previous = self.pairs(stage - 1)
        if any((stage - 1, i) not in self.winners for i in range(PAIRS)):
            raise ValueError('Previous tournament round is still running')
        won = tuple(self.winners[stage - 1, i] for i in range(PAIRS))
        lost = tuple(b if w == a else a for (a, b), w in zip(previous, won))
        if stage == 1:
            return ((won[0], won[1]), (won[2], won[3]), (lost[0], lost[1]), (lost[2], lost[3]))
        return ((won[0], won[1]), (lost[0], lost[1]), (won[2], won[3]), (lost[2], lost[3]))

    def resolve(self, stage: int, match: int, winner: int) -> None:
        if not 0 <= match < PAIRS or winner not in self.pairs(stage)[match]:
            raise ValueError('Winner is outside this tournament pairing')
        if self.winners.setdefault((stage, match), winner) != winner:
            raise ValueError('Conflicting tournament result')

    def placements(self) -> tuple[int, ...]:
        return tuple(slot for index, (a, b) in enumerate(self.pairs(2))
                     for w in (self.winners[2, index],) for slot in (w, b if w == a else a))


@dataclass(frozen=True)
class Tournament:
    identity: int
    bracket: Bracket
    names: tuple[bytes, ...]
    stage: int
    deadline: float


def initialise(path: str | Path) -> None:
    with transaction(path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS tournament_events (
            id INTEGER PRIMARY KEY, slots TEXT NOT NULL, names TEXT NOT NULL,
            stage INTEGER NOT NULL, deadline REAL NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS tournament_results (
            event INTEGER NOT NULL, stage INTEGER NOT NULL, pairing INTEGER NOT NULL,
            winner INTEGER NOT NULL, PRIMARY KEY(event, stage, pairing))''')


def create_event(path: str | Path, slots: tuple[str | None, ...],
                 names: tuple[bytes, ...], deadline: float) -> Tournament:
    accounts = tuple(owner for owner in slots if owner is not None)
    Bracket.create(accounts)
    if len(slots) != SIZE or len(names) != SIZE:
        raise ValueError('Expected eight tournament slots')
    with transaction(path) as db:
        cursor = db.execute('INSERT INTO tournament_events(slots, names, stage, deadline) VALUES (?, ?, 0, ?)',
                            (json.dumps(slots), json.dumps([name.hex() for name in names]), deadline))
        return Tournament(cursor.lastrowid, Bracket(slots), names, 0, deadline)


def active_events(path: str | Path) -> tuple[Tournament, ...]:
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute('SELECT id, slots, names, stage, deadline FROM tournament_events '
                          'WHERE stage < 3 ORDER BY id').fetchall()
    return tuple(_event(row) for row in rows)


def _event(row: tuple) -> Tournament:
    identity, slots, names, stage, deadline = row
    return Tournament(identity, Bracket(tuple(json.loads(slots))),
                      tuple(bytes.fromhex(name) for name in json.loads(names)), stage, deadline)


def read_event(path: str | Path, identity: int) -> Tournament:
    from .db_transaction import connect
    with closing(connect(path)) as db:
        row = db.execute('SELECT id, slots, names, stage, deadline FROM tournament_events WHERE id=?',
                         (identity,)).fetchone()
    event = _event(row)
    event.bracket.winners.update(results(path, identity))
    return event


def extend_preparation(path: str | Path, event: Tournament, deadline: float) -> Tournament:
    from dataclasses import replace
    with transaction(path) as db:
        db.execute('UPDATE tournament_events SET deadline=? WHERE id=? AND stage=?',
                   (deadline, event.identity, event.stage))
    return replace(event, deadline=deadline)


def results(path: str | Path, event: int) -> dict[tuple[int, int], int]:
    from .db_transaction import connect
    with closing(connect(path)) as db:
        return {(stage, pair): winner for stage, pair, winner in db.execute(
            'SELECT stage, pairing, winner FROM tournament_results WHERE event=?', (event,))}


def record_result(path: str | Path, event: int, stage: int, pair: int, winner: int) -> None:
    with transaction(path) as db:
        db.execute('INSERT OR IGNORE INTO tournament_results VALUES (?, ?, ?, ?)', (event, stage, pair, winner))
        recorded, = db.execute('SELECT winner FROM tournament_results WHERE event=? AND stage=? AND pairing=?',
                               (event, stage, pair)).fetchone()
        if recorded != winner:
            raise ValueError('Conflicting tournament battle result')


def advance(path: str | Path, event: Tournament, deadline: float, *, now: float | None = None) -> Tournament:
    if any((event.stage, index) not in event.bracket.winners for index in range(PAIRS)):
        raise ValueError('Tournament cannot advance before all matches finish')
    with transaction(path) as db:
        next_stage = event.stage + 1
        cursor = db.execute('UPDATE tournament_events SET stage=?, deadline=? WHERE id=? AND stage=?',
                            (next_stage, deadline, event.identity, event.stage))
        if cursor.rowcount != 1:
            raise ValueError('Stale tournament round')
        if next_stage == ROUNDS:
            save_standings(path, str(event.identity), event.bracket)
            _deliver_prizes(path, event, int(time.time() if now is None else now))
        return replace(event, stage=next_stage, deadline=deadline)


def _deliver_prizes(path: str | Path, event: Tournament, now: int) -> None:
    mail = MailStore(path)
    for place, slot in enumerate(event.bracket.placements(), 1):
        recipient = event.bracket.slots[slot]
        if recipient is None:
            continue
        credits, count = PRIZES[place - 1]
        items = (ItemRecord(0, VISION_INJECTION, bytes(2), count, 0, 0, (1, 1, 1),
                            bytes(4), None, bytes(3)),) if count else ()
        mail.deliver_reward(recipient, event.names[slot], PRIZE_SUBJECT,
                            f'Турнир №{event.identity}. Ваше место: {place} из {SIZE}.',
                            credits=credits, items=items, now=now)


def save_standings(path: str | Path, event: str, bracket: Bracket) -> None:
    rows = tuple((event, owner, place) for place, slot in enumerate(bracket.placements(), 1)
                 if (owner := bracket.slots[slot]) is not None)
    with transaction(path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS tournament_placements (
            event TEXT NOT NULL, account TEXT NOT NULL, place INTEGER NOT NULL CHECK(place BETWEEN 1 AND 8),
            PRIMARY KEY(account, event), UNIQUE(event, place))''')
        prior = tuple(db.execute('SELECT event, account, place FROM tournament_placements '
                                 'WHERE event=? ORDER BY place', (event,)))
        if prior and prior != rows:
            raise ValueError('Conflicting tournament placements')
        if not prior:
            db.executemany('INSERT INTO tournament_placements VALUES (?, ?, ?)', rows)


def standings(path: str | Path, account: str) -> tuple[int, ...]:
    if not Path(path).is_file():
        return (0,) * SIZE
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return read_standings(db, account)


def read_standings(db: sqlite3.Connection, account: str) -> tuple[int, ...]:
    result = [0] * SIZE
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='tournament_placements'").fetchone():
        for place, count in db.execute('SELECT place, COUNT(*) FROM tournament_placements '
                                       'WHERE account=? GROUP BY place', (account,)):
            result[place - 1] = count
    return tuple(result)
