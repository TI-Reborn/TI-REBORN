"""Soldier ranks: manual pp.52–54, original PetInfo66 rank fields.

The wire rank is ONE based; militaryRank is signed POINTS, not the rank ID.
All database helpers use their caller's transaction (including battle rewards).
See RANKS.md for explicit choices where the original server is unavailable.
"""

from .db_transaction import connect
from .mobs import MOB_RESOURCES
from bisect import bisect_right
from collections.abc import Collection
from contextlib import closing
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
import time
from .protocol.pet_info import decode_pet_info, encode_pet_info

RULES = json.loads((Path(__file__).resolve().parents[1]/'config/ranks.json').read_text(encoding='utf-8'))
THRESHOLDS = tuple(r['points'] for r in RULES['ranks'])
DAY = 86400


def signed(value):
    return value if value < 0x80000000 else value-0x100000000


def rank_id(points):
    return max(1, bisect_right(THRESHOLDS, points))


def level_cap(level):
    if not 1 <= level <= 20: raise ValueError('Unsupported soldier level')
    return next(cap for maximum, cap in RULES['level_caps'] if level <= maximum)


def kill_points(killer_level, killer_points, victim_level, victim_points):
    level_cap(killer_level)
    level_cap(victim_level)
    if victim_level < RULES['minimum_victim_level'][killer_level-1]: return 0
    difference = victim_points-killer_points
    adjustment = abs(difference)//500 * (1 if difference >= 0 else -1)
    return min(20, max(1, 10+adjustment))


def project(packet, human, points, *, commander_rank=29, debt=0):
    pet = decode_pet_info(packet, human_equipment=human)
    rank = min(rank_id(points), commander_rank)
    remaining = max(0, THRESHOLDS[rank]-points) if rank < 29 else 0
    return encode_pet_info(replace(pet, fields={**pet.fields,
        '0x8c4bbc':rank, '0x8c4bd0':points & 0xffffffff,
        '0x8c4be3':min(0x7fffffff, debt), '0x8c4bf6':remaining}))


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS soldier_ranks (
        account TEXT NOT NULL, pet_id INTEGER NOT NULL, points INTEGER NOT NULL,
        debt INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(account,pet_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS rank_clock (
        account TEXT PRIMARY KEY, next_decay INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS rank_battle_audit (
        account TEXT NOT NULL, match_id TEXT NOT NULL, pet_id INTEGER NOT NULL,
        before_points INTEGER NOT NULL, earned INTEGER NOT NULL, restored INTEGER NOT NULL,
        penalty INTEGER NOT NULL, after_points INTEGER NOT NULL,
        PRIMARY KEY(account,match_id,pet_id))''')


def roster(db, account):
    return db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=? ORDER BY pet_id', (account,)).fetchall()


def sync(db, account, *, now=None, active=False):
    """Import old saves without resetting points; catch up offline decay once."""
    now = int(time.time() if now is None else now)
    schema(db)
    rows = roster(db, account)
    for owner, human, packet in rows:
        fields = decode_pet_info(packet, human_equipment=bool(human)).fields
        # Old fixtures used rank=0 and undefined rank fields. They are recruits.
        points = signed(fields['0x8c4bd0']) if 1 <= fields['0x8c4bbc'] <= 29 else 0
        db.execute('INSERT OR IGNORE INTO soldier_ranks(account,pet_id,points) VALUES (?,?,?)', (account,owner,points))
    db.execute('INSERT OR IGNORE INTO rank_clock VALUES (?,?)', (account,now+DAY))
    due = db.execute('SELECT next_decay FROM rank_clock WHERE account=?', (account,)).fetchone()[0]
    if not active and now >= due:
        days = (now-due)//DAY+1
        for owner, _, _ in rows:
            points, debt = db.execute('SELECT points,debt FROM soldier_ranks WHERE account=? AND pet_id=?', (account,owner)).fetchone()
            before = points
            # Daily integer rounding; stops early below 100 even after years offline.
            for _ in range(days):
                loss = min(50, max(0, points)//100)
                if not loss: break
                points -= loss
            db.execute('UPDATE soldier_ranks SET points=?,debt=? WHERE account=? AND pet_id=?', (points,debt+before-points,account,owner))
        db.execute('UPDATE rank_clock SET next_decay=? WHERE account=?', (due+days*DAY,account))
    if active:
        db.execute('UPDATE rank_clock SET next_decay=? WHERE account=?', (now+DAY,account))
    write_packets(db, account, rows)


def write_packets(db, account, rows=None):
    rows = roster(db, account) if rows is None else rows
    for owner, updated in packet_updates(db, account, rows):
        db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?', (updated,account,owner))


def needs_sync(db: sqlite3.Connection, account: str, rows: list, *, now=None) -> bool:
    """Check lazy imports, decay and packet projection without taking a writer."""
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'soldier_ranks', 'rank_clock'} <= tables:
        return True
    due = db.execute('SELECT next_decay FROM rank_clock WHERE account=?', (account,)).fetchone()
    if due is None or int(time.time() if now is None else now) >= due[0]:
        return True
    saved = {r[0] for r in db.execute('SELECT pet_id FROM soldier_ranks WHERE account=?', (account,))}
    if any(owner not in saved for owner, _, _ in rows):
        return True
    return bool(packet_updates(db, account, rows))


def packet_updates(db: sqlite3.Connection, account: str, rows: list) -> list[tuple[int, bytes]]:
    if not rows: return []
    updates = []
    states = dict((i,(p,d)) for i,p,d in db.execute('SELECT pet_id,points,debt FROM soldier_ranks WHERE account=?', (account,)))
    hired = set()
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='hired_candidates'").fetchone():
        hired = {r[0] for r in db.execute('SELECT pet_id FROM hired_candidates WHERE account=?', (account,))}
    # The original avatar is the non-hired actor. Old fixtures fall back to first ID.
    commander = next((i for i,h,p in rows if i not in hired), rows[0][0])
    commander_rank = rank_id(states[commander][0])
    for owner,human,packet in rows:
        points,debt = states[owner]
        updated = project(packet,bool(human),points,commander_rank=commander_rank,debt=debt)
        if updated != packet:
            updates.append((owner, updated))
    return updates


def settle_ranks(db, account, match_id, result, report, *, now=None, escaped=False,
                 repeat_factor=Fraction(1)):
    """report: actor -> (kill points, died[, death counts for rank])."""
    if not isinstance(repeat_factor,Fraction) or not 0<=repeat_factor<=1:
        raise ValueError('Invalid rank repeat factor')
    sync(db, account, now=now, active=True)
    rows = {i:(h,p) for i,h,p in roster(db, account)}
    if not set(report) <= rows.keys(): raise ValueError('Unowned rank participant')
    for owner,entry in report.items():
        if len(entry) not in (2,3):raise ValueError('Invalid rank report')
        earned,died=entry[:2]
        penalize_death=died if len(entry)==2 else entry[2]
        if type(earned) is not int or earned < 0 or type(died) is not bool:
            raise ValueError('Invalid rank result')
        if type(penalize_death) is not bool or penalize_death and not died:raise ValueError('Invalid rank death cause')
        before,debt = db.execute('SELECT points,debt FROM soldier_ranks WHERE account=? AND pet_id=?', (account,owner)).fetchone()
        human,packet = rows[owner]
        level = decode_pet_info(packet,human_equipment=bool(human)).fields['0x8c4aef']
        fled = escaped and not died
        gain = 0 if fled else earned*(2 if result == 1 else 1)
        from .premium import state
        factor=repeat_factor*(Fraction(3,2) if state(db,account,now)[0]==1 else 1)
        gain=gain*factor.numerator//factor.denominator
        penalty = 20 if fled else 5 if penalize_death else 0
        # Each two recoverable points cost one newly earned point; odd last point
        # costs one. Level cap applies to recovery too, and never erases old points.
        budget = max(0,level_cap(level)-before)
        gain = min(gain,budget)
        restored = min(gain,debt//2,budget-gain)
        debt -= min(debt,gain+restored)
        after = max(-0x7fffffff,before+gain+restored-penalty)
        db.execute('UPDATE soldier_ranks SET points=?,debt=? WHERE account=? AND pet_id=?', (after,debt,account,owner))
        db.execute('INSERT INTO rank_battle_audit VALUES (?,?,?,?,?,?,?,?)', (account,match_id,owner,before,gain,restored,penalty,after))
    write_packets(db, account)


def squad_points(db, account):
    rows = roster(db,account)
    values = []
    for owner,human,packet in rows:
        f = decode_pet_info(packet,human_equipment=bool(human)).fields
        values.append((owner,f['0x8c4aef'],signed(f['0x8c4bd0'])))
    top = {r[0] for r in sorted(values,key=lambda r:(-r[1],r[0]))[:3]}
    return sum((Fraction(p,3 if i in top or p<0 else 15) for i,l,p in values), Fraction(0))


def credit_percent(db, account):
    points = squad_points(db,account)
    return int(points//250) if points >= 0 else -min(90,int(-points//500))


def battle_report(combat, owner, *, weekly_rank_per_kill=0,weekly_rank_by_victim=None,
                  actor_ids: Collection[int] | None = None):
    """Optional server-frozen weekly badge bonus, before normal rank settlement.

    Capture clan_benefits.rank_per_kill at each accepted death and preserve the
    weekly_rank_by_victim map in the authoritative match journal/snapshot. Missing
    entries grant0, including after badge expiry. The constant argument supports
    older fixed-bonus callers. Existing callers keep bonus0; this helper never
    reads wall-clock state or a client-supplied badge claim.
    """
    if type(weekly_rank_per_kill) is not int or not 0<=weekly_rank_per_kill<=5:
        raise ValueError('Invalid frozen weekly rank bonus')
    if weekly_rank_by_victim is not None:
        deaths={victim for killer,victim in combat.rank_kills}
        if not isinstance(weekly_rank_by_victim,dict) or any(type(i) is not int or i<=0 or i not in deaths
                or type(n) is not int or not 0<=n<=5 for i,n in weekly_rank_by_victim.items()):
            raise ValueError('Invalid accepted-death weekly rank bonuses')
    if getattr(combat,'wager',False):weekly_rank_per_kill=0
    owners=getattr(combat,'actor_owners',None)
    if owners is None:owners={i:a.owner_id for i,a in combat.field._actors.items()}
    eligible_ids = combat.persistence if actor_ids is None else actor_ids
    result = {i:[0,a.health==0] for i,a in combat.field._actors.items()
              if a.owner_id == owner and i in eligible_ids}
    weekly_victims=set()
    for killer,victim in combat.rank_kills:
        if killer not in result: continue
        if combat.resources.get(victim) in MOB_RESOURCES:continue
        kl,kp = combat.rank_profiles[killer]
        vl,vp = combat.rank_profiles[victim]
        from .battle_item_effects import rank_bonus
        base=kill_points(kl,kp,vl,vp)
        eligible=(base>0 and victim in owners and not combat.field.allied(owners[killer],owners[victim]))
        captured=weekly_rank_by_victim.get(victim,0) if weekly_rank_by_victim is not None else weekly_rank_per_kill
        badge=captured if eligible and victim not in weekly_victims and not getattr(combat,'wager',False) else 0
        if eligible:weekly_victims.add(victim)
        result[killer][0] += base + badge + getattr(combat,'city_kill_bonus',0)+rank_bonus(combat,killer,victim)
    player_killed={victim for killer,victim in combat.rank_kills
                   if combat.resources.get(killer) in (1,2,3,4,5,6)
                   and killer in owners and victim in owners
                   and owners[killer]!=owners[victim]}
    return {i:((p,d,False) if d and i not in player_killed else (p,d)) for i,(p,d) in result.items()}


def refresh(path, account, *, now=None, active=False):
    with closing(connect(path)) as db,db:
        db.execute('BEGIN IMMEDIATE')
        before = {i:bytes(p) for i,h,p in roster(db,account)}
        sync(db,account,now=now,active=active)
        return tuple(i for i,h,p in roster(db,account) if before.get(i)!=p)
