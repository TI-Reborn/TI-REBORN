"""Join server-owned gameplay writes to one SQLite transaction per action.

Outside a gameplay unit connect is the standard SQLite API. A leased connection
cannot commit or close the enclosing unit; nested store scopes use savepoints.
No global monkeypatch, and no connection is shared between threads.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import itertools
import sqlite3
import time
from .performance import observe

_current=ContextVar('tio_gameplay_transaction',default=None)
_numbers=itertools.count()


def key(path):
    return str(Path(path).resolve()).casefold() if __import__('os').name=='nt' else str(Path(path).resolve())


class Lease:
    def __init__(self,db):self.db=db;self.scopes=[]
    def __getattr__(self,name):return getattr(self.db,name)
    def execute(self,sql,*args,**kwargs):
        if sql.strip().upper() in ('BEGIN','BEGIN IMMEDIATE','BEGIN EXCLUSIVE','BEGIN TRANSACTION'):
            return self.db.execute('SELECT 1')
        return self.db.execute(sql,*args,**kwargs)
    def __enter__(self):
        name='tio_store_'+str(next(_numbers));self.db.execute('SAVEPOINT '+name)
        self.scopes.append(name);return self
    def __exit__(self,kind,error,trace):
        name=self.scopes.pop()
        if kind is not None:self.db.execute('ROLLBACK TO '+name)
        self.db.execute('RELEASE '+name)
        return False
    def close(self):pass
    def commit(self):raise RuntimeError('Store cannot commit a gameplay unit')
    def rollback(self):raise RuntimeError('Store cannot roll back a gameplay unit')
    def executescript(self,*args,**kwargs):raise RuntimeError('Implicit script commits are forbidden in gameplay units')


def connect(path,*args,**kwargs):
    active=_current.get()
    if active is not None and key(path)==active[0]:
        if args or kwargs:raise ValueError('Custom connection options inside gameplay unit')
        return Lease(active[1])
    return sqlite3.connect(path,*args,**kwargs)


@contextmanager
def transaction(path):
    active=_current.get();identity=key(path)
    if active is not None:
        if active[0]!=identity:raise ValueError('Gameplay unit cannot span databases')
        yield active[1];return
    db=sqlite3.connect(path)
    token=None
    started=time.perf_counter()
    try:
        db.execute('PRAGMA synchronous=FULL')
        waiting=time.perf_counter()
        db.execute('BEGIN IMMEDIATE')
        observe('sql.begin_wait',time.perf_counter()-waiting)
        token=_current.set((identity,db))
        yield db
        db.commit()
    except BaseException:
        db.rollback();raise
    finally:
        if token is not None:_current.reset(token)
        db.close()
        observe('sql.transaction',time.perf_counter()-started)


def current():
    active=_current.get()
    return None if active is None else active[1]
