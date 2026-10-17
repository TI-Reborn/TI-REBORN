"""Shared mining round scores, idempotent mission wins and next-round tax."""
from contextlib import closing
import json
import math
from pathlib import Path
import time

from .db_transaction import connect

POLICY=json.loads((Path(__file__).resolve().parents[1]/'config/mine_rounds.json').read_text(encoding='utf-8'))


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS mine_round_state (
        id INTEGER PRIMARY KEY CHECK(id=1),started INTEGER NOT NULL,
        defense_points INTEGER NOT NULL CHECK(defense_points BETWEEN 0 AND 10),
        defense_wins INTEGER NOT NULL CHECK(defense_wins BETWEEN 0 AND 4294967295),
        raider_wins INTEGER NOT NULL CHECK(raider_wins BETWEEN 0 AND 4294967295))''')
    db.execute('''CREATE TABLE IF NOT EXISTS mine_round_history (
        started INTEGER PRIMARY KEY,defense_wins INTEGER NOT NULL,raider_wins INTEGER NOT NULL,
        previous_points INTEGER NOT NULL,next_points INTEGER NOT NULL,closed INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS mine_round_missions (
        match_id TEXT PRIMARY KEY,started INTEGER NOT NULL,side INTEGER NOT NULL CHECK(side IN (0,1)),
        gross INTEGER NOT NULL CHECK(gross BETWEEN 1 AND 4294967295),observed INTEGER NOT NULL)''')


def clock_value(now):
    if isinstance(now,bool) or not isinstance(now,(int,float)) or not math.isfinite(now) or now<0:
        raise ValueError('Invalid mining round clock')
    return int(now)


def advance(db,now):
    """Run inside the caller's transaction; never rewrite a frozen mine claim."""
    if not db.in_transaction:raise ValueError('Mining round transaction required')
    now=clock_value(now);schema(db)
    duration=POLICY['duration_seconds'];current=now//duration*duration
    db.execute('INSERT OR IGNORE INTO mine_round_state VALUES (1,?,?,0,0)',
               (current,POLICY['initial_defense_points']))
    started,points,defense,raiders=db.execute('SELECT started,defense_points,defense_wins,raider_wins FROM mine_round_state WHERE id=1').fetchone()
    if now>=started+duration:
        next_points=max(0,min(POLICY['total_points'],points+(defense>raiders)-(raiders>defense)))
        db.execute('INSERT INTO mine_round_history VALUES (?,?,?,?,?,?)',
                   (started,defense,raiders,points,next_points,started+duration))
        # Empty hours while offline never repeat the previous hour's result.
        db.execute('UPDATE mine_round_state SET started=?,defense_points=?,defense_wins=0,raider_wins=0 WHERE id=1',
                   (current,next_points))
        from .mine_claims import schema as claim_schema
        claim_schema(db)
        for location,owner,tax,revision in db.execute('SELECT location,owner_clan,tax_percent,revision FROM mine_claims WHERE owner_clan IS NOT NULL').fetchall():
            if tax==next_points:continue
            if revision>=0xffffffff:raise ValueError('Checkpoint claim revision exhausted')
            revision+=1
            db.execute('INSERT INTO mine_claim_history VALUES (?,?,?,?,?,?,?)',
                       (location,revision,owner,next_points,'server:mine-round',f'round {started}: {defense}/{raiders}',now))
            db.execute('UPDATE mine_claims SET tax_percent=?,revision=? WHERE location=?',
                       (next_points,revision,location))
        started,points,defense,raiders=current,next_points,0,0
    return dict(started=started,ends=started+duration,defense_points=points,
                raider_points=POLICY['total_points']-points,defense_wins=defense,
                raider_wins=raiders,remaining=max(0,min(duration,started+duration-now)))


def record_mission(db,match_id,side,gross,*,now):
    if not isinstance(match_id,str) or not match_id or len(match_id)>128:raise ValueError('Invalid mining match')
    if type(side) is not int or side not in (0,1):raise ValueError('Invalid mining side')
    if type(gross) is not int or not 0<gross<=0xffffffff:raise ValueError('Successful extraction required')
    state=advance(db,now)
    previous=db.execute('SELECT side,gross FROM mine_round_missions WHERE match_id=?',(match_id,)).fetchone()
    if previous:
        if previous!=(side,gross):raise ValueError('Conflicting mining round outcome')
        return state
    field='defense_wins' if side==0 else 'raider_wins'
    if state[field]>=0xffffffff:raise ValueError('Mining round score exhausted')
    db.execute('INSERT INTO mine_round_missions VALUES (?,?,?,?,?)',
               (match_id,state['started'],side,gross,clock_value(now)))
    db.execute(f'UPDATE mine_round_state SET {field}={field}+? WHERE id=1',
               (POLICY['score_per_successful_mission'],))
    state[field]+=POLICY['score_per_successful_mission']
    return state


class MineRounds:
    def __init__(self,path,*,clock=time.time):self.path,self.clock=path,clock

    def state(self):
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');return advance(db,self.clock())

    def packets(self):
        import struct
        state=self.state()
        return (b'\xb0\x26'+struct.pack('<II',state['defense_points'],state['raider_points']),
                b'\xb0\x27'+struct.pack('<II',state['defense_wins'],state['raider_wins']),
                b'\xb0\x2b'+struct.pack('<I',state['remaining']))
