"""Bounded token budgets before constructors and password hashing.

Account retry budgets belong to IP/account pairs, so an unrelated address
cannot impose an account-wide lockout. Existing authenticated sessions never
consume these budgets. State contains no passwords and expires automatically.
"""
from contextlib import contextmanager
import threading
import time
from .auth_errors import LoginRejected
from tio.protocol.login import LoginFailureStatus


class LoginThrottled(LoginRejected):
    def __init__(self, reason):
        self.reason = reason
        super().__init__('throttled', LoginFailureStatus.OVERLOADED,
            'Login temporarily limited: '+reason)


class LoginGuard:
    MAX_UNAUTHENTICATED=8
    MAX_UNAUTHENTICATED_PER_IP=4
    MAX_HASHES=2
    MAX_BUCKETS=8192
    IDLE_SECONDS=300

    def __init__(self,*,clock=time.monotonic):
        self.clock=clock;self.lock=threading.Lock()
        self.buckets={};self.next_prune=0;self.hashing=set();self.counters={}

    def _reject(self,reason):
        self.counters[reason]=self.counters.get(reason,0)+1
        raise LoginThrottled(reason)

    def _take(self,specs,reason):
        now=self.clock()
        if now>=self.next_prune:
            self.buckets={key:state for key,state in self.buckets.items() if now-state[1]<self.IDLE_SECONDS}
            self.next_prune=now+30
        if len(self.buckets)+sum(key not in self.buckets for key,_,_ in specs)>self.MAX_BUCKETS:
            self._reject('budget-state-full')
        staged={}
        for key,capacity,rate in specs:
            tokens,stamp=self.buckets.get(key,(capacity,now))
            tokens=min(capacity,tokens+max(0,now-stamp)*rate)
            if tokens<1:self._reject(reason)
            staged[key]=(tokens-1,now)
        self.buckets.update(staged)

    def admit_connection(self,ip,*,unauthenticated,total,max_sessions):
        with self.lock:
            if total>=max_sessions+self.MAX_UNAUTHENTICATED:self._reject('connection-capacity')
            if len(unauthenticated)>=self.MAX_UNAUTHENTICATED:self._reject('unauthenticated-capacity')
            if sum(address==ip for address in unauthenticated)>=self.MAX_UNAUTHENTICATED_PER_IP:
                self._reject('ip-unauthenticated-capacity')
            self._take(((('connect-global',),32,4),(('connect-ip',ip),16,1)),'connection-rate')

    def admit_handoff(self,ip,*,addresses,max_handoffs):
        with self.lock:
            if len(addresses)>=max_handoffs:self._reject('handoff-capacity')
            if sum(address==ip for address in addresses)>=self.MAX_UNAUTHENTICATED_PER_IP:
                self._reject('ip-handoff-capacity')
            self._take(((('handoff-global',),32,4),(('handoff-ip',ip),16,1)),'handoff-rate')

    @contextmanager
    def hash_slot(self,ip,login):
        from .accounts import identity
        try:name=identity(login.decode('ascii'))
        except (ValueError,UnicodeError):name=''
        with self.lock:
            if len(self.hashing)>=self.MAX_HASHES or name in self.hashing:self._reject('hash-busy')
            self._take(((('auth-global',),24,4),(('auth-ip',ip),12,.5),(('auth-pair',ip,name),5,.1)),'authentication-rate')
            self.hashing.add(name)
            self.counters['hash-granted']=self.counters.get('hash-granted',0)+1
        try:yield
        finally:
            with self.lock:self.hashing.remove(name)

    def snapshot(self):
        with self.lock:return dict(counters=dict(self.counters),buckets=len(self.buckets),hashing=len(self.hashing))
