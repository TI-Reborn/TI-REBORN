"""Bounded aggregate timings; never records accounts, packets or SQL text."""
from contextlib import contextmanager
from functools import wraps
import logging
import threading
import time

LOG=logging.getLogger('tio.performance')
LIMITS=(.1,.25,.5,1,2,5,10,20,50,100,250,500,1000,5000,float('inf'))
_lock=threading.Lock()
_values={}
_next_report=0


def observe(name,seconds):
    global _next_report
    ms=max(0,seconds*1000);report=None
    with _lock:
        if name not in _values:
            if len(_values)>=32:return
            _values[name]=[0,0.,0.,[0]*len(LIMITS)]
        value=_values[name];value[0]+=1;value[1]+=ms;value[2]=max(value[2],ms)
        for index,limit in enumerate(LIMITS):
            if ms<=limit:value[3][index]+=1;break
        now=time.monotonic()
        if not _next_report:_next_report=now+60
        if now>=_next_report:
            report=_values.copy();_values.clear();_next_report=now+60
    if report is not None:
        for metric,(count,total,maximum,buckets) in sorted(report.items()):
            cumulative=0
            for index,n in enumerate(buckets):
                cumulative+=n
                if cumulative>=count*.95:break
            LOG.info('performance metric=%s count=%d mean_ms=%.3f p95_upper_ms=%s max_ms=%.3f',
                     metric,count,total/count,LIMITS[index],maximum)


@contextmanager
def timed_block(name: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        observe(name, time.perf_counter() - start)


def timed(name):
    def decorate(method):
        @wraps(method)
        def wrapped(*args,**kwargs):
            start=time.perf_counter()
            try:return method(*args,**kwargs)
            finally:observe(name,time.perf_counter()-start)
        return wrapped
    return decorate


@contextmanager
def timed_lock(lock,name):
    started=time.perf_counter();lock.acquire();acquired=time.perf_counter()
    try:yield
    finally:
        held=time.perf_counter()-acquired;lock.release()
        observe(name+'.wait',acquired-started);observe(name+'.held',held)
