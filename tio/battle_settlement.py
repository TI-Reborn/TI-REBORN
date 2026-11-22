"""Durable final reports, replayed through the idempotent reward transaction.

This is a settlement outbox, not a snapshot of an unfinished battle. Reports
are private server inputs; neither the client nor a retry may replace them.
"""

from .db_transaction import connect
from contextlib import closing
from dataclasses import asdict
import json
import sqlite3
import time


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS battle_settlement_jobs (
        match_id TEXT NOT NULL,account TEXT NOT NULL,payload TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,
        error_type TEXT,PRIMARY KEY(match_id,account))''')
    db.execute('''CREATE TABLE IF NOT EXISTS battle_failure_audit (
        match_id TEXT NOT NULL,account TEXT NOT NULL,error_type TEXT NOT NULL,
        created_at REAL NOT NULL,resolved INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(match_id,account))''')


def initialise(path):
    with closing(connect(path)) as db,db:schema(db)


def pack(result,kwargs):
    data=dict(kwargs)
    if data.get('reward_context') is not None:data['reward_context']=asdict(data['reward_context'])
    return json.dumps(dict(version=1,result=result,kwargs=data),sort_keys=True,allow_nan=False)


def unpack(payload):
    data=json.loads(payload)
    if data['version']!=1:raise ValueError('Unknown settlement report version')
    kwargs=data['kwargs']
    for key in ('health','rank_report','experience_report','tournament_proficiency'):
        if kwargs.get(key) is not None:kwargs[key]={int(i):v for i,v in kwargs[key].items()}
    if kwargs.get('statistics_report') is not None:
        totals,soldiers=kwargs['statistics_report']
        kwargs['statistics_report']=(totals,{int(i):v for i,v in soldiers.items()})
    if kwargs.get('reward_context') is not None:
        from .reward_policy import RewardContext
        c=kwargs['reward_context']
        kwargs['reward_context']=RewardContext(tuple(c['levels']),tuple((n,tuple(ls)) for n,ls in c['opponents']),c['active'],c.get('town_id'))
    return data['result'],kwargs


def enqueue(path,match_id,reports,*,error=None):
    """Capture all supplied accounts in one transaction before any settlement."""
    packed=[(account,pack(result,kwargs)) for account,result,kwargs in reports]
    with closing(connect(path)) as db,db:
        db.execute('BEGIN IMMEDIATE');schema(db)
        for account,payload in packed:
            prior=db.execute('SELECT payload FROM battle_settlement_jobs WHERE match_id=? AND account=?',(match_id,account)).fetchone()
            if prior is not None and prior[0]!=payload:raise ValueError('Conflicting pending settlement report')
            db.execute('INSERT OR IGNORE INTO battle_settlement_jobs(match_id,account,payload) VALUES (?,?,?)',
                       (match_id,account,payload))
        if error is not None:
            for account,_ in packed:
                db.execute('INSERT OR IGNORE INTO battle_failure_audit VALUES (?,?,?,?,0)',
                           (match_id,account,type(error).__name__,time.time()))


def record_failure(path,match_id,accounts,error):
    # If report generation itself fails, retain a visible unresolved record and
    # block those accounts from editing the roster needed for later settlement.
    with closing(connect(path)) as db,db:
        db.execute('BEGIN IMMEDIATE');schema(db)
        for account in accounts:
            db.execute('INSERT OR IGNORE INTO battle_failure_audit VALUES (?,?,?,?,0)',
                           (match_id,account,error if isinstance(error,str) else type(error).__name__,time.time()))


def complete_failure(path,match_id):
    with closing(connect(path)) as db,db:
        db.execute('UPDATE battle_failure_audit SET resolved=1 WHERE match_id=?',(match_id,))


def blocked(path,account):
    with closing(connect(path)) as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'battle_settlement_jobs' in tables and db.execute('SELECT 1 FROM battle_settlement_jobs WHERE account=? LIMIT 1',(account,)).fetchone():return True
        return bool('battle_failure_audit' in tables and db.execute(
            'SELECT 1 FROM battle_failure_audit WHERE account=? AND resolved=0 LIMIT 1',(account,)).fetchone())


def apply(path,match_id,account):
    with closing(connect(path)) as db:
        row=db.execute('SELECT payload FROM battle_settlement_jobs WHERE match_id=? AND account=?',(match_id,account)).fetchone()
        if row is None and db.execute("SELECT 1 FROM sqlite_master WHERE name='battle_rewards'").fetchone():
            if db.execute('SELECT 1 FROM battle_rewards WHERE match_id=? AND account=?',(match_id,account)).fetchone():
                from .protocol.asset_count import AssetCount
                return AssetCount(*db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone())
    if row is None:raise ValueError('Pending settlement report missing')
    result,kwargs=unpack(row[0])
    from .battle_rewards import settle
    # Inside a gameplay transaction this scope rolls back a failed report even
    # when the caller catches the error and continues the outer transaction.
    with closing(connect(path)) as db,db:
        assets=settle(path,account,match_id,result,**kwargs)
        db.execute('DELETE FROM battle_settlement_jobs WHERE match_id=? AND account=?',(match_id,account))
        db.execute('UPDATE battle_failure_audit SET resolved=1 WHERE match_id=? AND account=?',(match_id,account))
    return assets


def retry(path,*,force=False,limit=32):
    from server.failure_policy import storage_failure
    import logging
    log=logging.getLogger('tio.server')
    now=time.time()
    with closing(connect(path)) as db:
        rows=db.execute('SELECT match_id,account,attempts FROM battle_settlement_jobs WHERE next_attempt<=? ORDER BY next_attempt,match_id,account LIMIT ?',
                        (float('inf') if force else now,limit)).fetchall()
    completed=[]
    for match,account,attempts in rows:
        try:apply(path,match,account)
        except Exception as error:
            if storage_failure(error):raise
            with closing(connect(path)) as db,db:
                db.execute('UPDATE battle_settlement_jobs SET attempts=attempts+1,next_attempt=?,error_type=? WHERE match_id=? AND account=?',
                           (now+min(300,5*2**min(attempts,6)),type(error).__name__,match,account))
            log.error('settlement_retry_failed match=%s account=%s error_type=%s',match,account,type(error).__name__)
        else:completed.append((match,account))
    return completed
