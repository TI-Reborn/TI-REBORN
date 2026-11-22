"""Read the clan and alliance windows opened from a player's public card."""
from contextlib import closing
from pathlib import Path
import sqlite3
import unicodedata

from tio.alliances import alliance_for_clan
from tio.clan_ratings import alliances, clans
from tio.clans import available, character, level, membership
from tio.protocol.public_profile import encode_alliance_profile, encode_clan_profile

from .alliance_service import projection


def _standing(db: sqlite3.Connection, clan_id: int, *, trueskill: bool) -> dict:
    for offset in (0, 100, 200):
        page = clans(db, offset=offset, trueskill=trueskill)
        for row in page:
            if row['id'] == clan_id:
                return row
        if len(page) < 100:
            break
    return {}


def clan_card(path: str | Path, name: bytes, online: set[str], *, view_alliance: bool) -> bytes:
    key = unicodedata.normalize('NFKC', name.decode('cp1251')).casefold()
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        row = db.execute('SELECT id,leader FROM clans WHERE name_key=?', (key,)).fetchone() if available(db) else None
        if row is None:
            raise ValueError('Клан не найден')
        clan = membership(db, row[1])
        if clan is None or clan['id'] != row[0]:
            raise ValueError('Клан не найден')
        alliance = alliance_for_clan(db, clan['id'])
        if view_alliance:
            if alliance is None:
                raise ValueError('Клан не состоит в действующем альянсе')
            cohort = []
            for clan_id in alliance['clans']:
                name, leader, tier, influence = db.execute(
                    'SELECT name,leader,level,influence FROM clans WHERE id=?', (clan_id,)).fetchone()
                cohort.append(dict(id=clan_id, name=bytes(name), leader=leader, level=tier, influence=influence))
            place = next((row['place'] for row in alliances(db) if row['id'] == alliance['id']), 0)
            return encode_alliance_profile(projection(db, alliance, cohort, online), place)
        members = tuple(dict(name=character(db, owner), level=level(db, owner),
                             online=owner in online, leader=owner == clan['leader'])
                        for owner, in db.execute('SELECT account FROM clan_members WHERE clan_id=? ORDER BY id',
                                                 (clan['id'],)))
        ordinary = _standing(db, clan['id'], trueskill=False)
        ranked = _standing(db, clan['id'], trueskill=True)
        return encode_clan_profile(clan, members, alliance, ordinary.get('place', 0),
                                   ranked.get('place', 0), ranked.get('rating', 0))
