"""Saved map positions after the road layout moved every location (2026-10-29).

In-town characters stand at their town's parking point. Journeys started
before the move point at old coordinates; a once-only migration completes them
at the relocated destination. Journey table schemas stay compatible.
"""
import json
from pathlib import Path
from collections.abc import Mapping
import sqlite3


_PARKING = json.loads((Path(__file__).resolve().parents[1] /
    "config/world_roads.json").read_text(encoding="utf-8"))["nodes"]


def parking_point(town: int) -> tuple[int, int] | None:
    point = _PARKING.get(f"L{town}")
    return tuple(point) if point is not None else None

# Rectangles before the move; used only to recognise old journey targets.
LEGACY_BOUNDS = {
    2: (-390, -447, -345, -402), 3: (-171, -335, -136, -300), 4: (225, -437, 305, -357),
    5: (140, -70, 240, 30), 6: (-434, -370, -414, -350), 7: (315, -410, 335, -390),
    8: (286, -265, 366, -185), 9: (-90, -460, -64, -434), 10: (-330, 59, -304, 85),
    11: (63, -3, 83, 18), 12: (241, -175, 261, -155), 13: (-180, -284, -160, -264),
    14: (175, -346, 195, -326), 15: (88, -10, 108, 10), 16: (255, -170, 275, -150),
    17: (-25, -268, 1, -242), 18: (-150, 50, -90, 110), 19: (-240, -320, -220, -300),
    20: (-240, -420, -220, -400), 21: (-245, -370, -225, -350), 22: (110, -320, 130, -300),
}


def legacy_town_at(x, y):
    return next((town for town, (x1, y1, x2, y2) in LEGACY_BOUNDS.items()
                 if x1 <= x <= x2 and y1 <= y <= y2), None)


def _claim(db: sqlite3.Connection, name: str) -> bool:
    db.execute('CREATE TABLE IF NOT EXISTS world_layout_migrations(name TEXT PRIMARY KEY)')
    return db.execute('INSERT OR IGNORE INTO world_layout_migrations VALUES (?)', (name,)).rowcount == 1


def normalize_characters(db: sqlite3.Connection, centers: Mapping[int, tuple[int, int]]) -> None:
    """Move old coordinates once, without changing the legacy journey schema."""
    if not _claim(db, 'v3-characters'):
        return
    for town, (x, y) in centers.items():
        db.execute('UPDATE character_locations SET x=?,y=? WHERE town_id=?', (x, y, town))
    for account, tx, ty, started in db.execute(
            'SELECT account,tx,ty,started FROM map_journeys').fetchall():
        town = legacy_town_at(tx, ty)
        if town in centers:
            tx, ty = centers[town]
        db.execute('UPDATE map_journeys SET tx=?,ty=?,arrives=? WHERE account=?',
                   (tx, ty, started + 0.000001, account))


def normalize_parties(db: sqlite3.Connection, centers: Mapping[int, tuple[int, int]]) -> None:
    """Complete old group routes once; current routes survive reconnects."""
    if not _claim(db, 'v3-parties'):
        return
    for party, tx, ty, started, town in db.execute(
            'SELECT party_id,tx,ty,started,town_id FROM travel_party_journeys').fetchall():
        if town in centers:
            tx, ty = centers[town]
        db.execute('UPDATE travel_party_journeys SET tx=?,ty=?,arrives=? WHERE party_id=?',
                   (tx, ty, started + 0.000001, party))


def restore_legacy_layout(db: sqlite3.Connection) -> None:
    """Offline rollback of map coordinates only; never restore player snapshots."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='world_layout_migrations'").fetchone():
        return
    if not db.execute("SELECT 1 FROM world_layout_migrations WHERE name='v3-characters'").fetchone():
        return
    from .locations import town_at
    centers = {town: ((a+c)//2, (b+d)//2) for town, (a,b,c,d) in LEGACY_BOUNDS.items()}
    for town, (x,y) in centers.items():
        db.execute('UPDATE character_locations SET x=?,y=? WHERE town_id=?', (x,y,town))
    for account, tx, ty, started in db.execute(
            'SELECT account,tx,ty,started FROM map_journeys').fetchall():
        town = town_at(tx,ty)
        if town in centers:
            tx,ty = centers[town]
        db.execute('UPDATE map_journeys SET tx=?,ty=?,arrives=? WHERE account=?',
                   (tx,ty,started+0.000001,account))
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='travel_party_journeys'").fetchone():
        normalize = db.execute('SELECT party_id,town_id,started FROM travel_party_journeys').fetchall()
        for party, town, started in normalize:
            if town in centers:
                db.execute('UPDATE travel_party_journeys SET tx=?,ty=?,arrives=? WHERE party_id=?',
                           (*centers[town],started+0.000001,party))
    db.execute('DELETE FROM world_layout_migrations')
