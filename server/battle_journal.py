"""Checkpoint accepted gameplay with its economic writes before exposing replies."""
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
import logging
import sqlite3
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING

from tio import battle_checkpoints as store
from tio import battle_snapshot as codec
from tio.db_transaction import transaction
from .failure_policy import storage_failure

LOG=logging.getLogger('tio.server')
_units=ContextVar('tio_battle_units',default=())

if TYPE_CHECKING:
    from tio.arena_service import ArenaService


def play_private_turn(arena: 'ArenaService', room_id: int,
                      owner: int) -> tuple[bytes, ...]:
    """Commit an NPC turn together; retry only rolled-back SQLite contention."""
    from tio.training_bot import play_turn
    manager = getattr(arena, '_durable', None)
    if manager is None:
        return play_turn(arena, room_id, owner,
                         view=getattr(arena._fields[room_id], 'result_view', None))
    for attempt in range(3):
        try:
            with manager.unit():
                return play_turn(arena, room_id, owner, view=getattr(
                    arena._fields[room_id], 'result_view', None))
        except sqlite3.OperationalError as error:
            if storage_failure(error) or attempt == 2:
                raise
    raise AssertionError('NPC turn retry limit did not terminate')


class OfflineSession(SimpleNamespace):
    def stop(self):pass


def rebind(arena,path):
    for field in arena._fields.values():
        for identity,(_,account) in field.combat.persistence.items():
            field.combat.persistence[identity]=(path,account)


def arena_copy(target,restored,manager):
    target.__dict__.clear();target.__dict__.update(restored.__dict__)
    target._durable=manager
    manager.attach()


class PrivateJournal:
    def __init__(self,arena,path,account,*,session=None,wall=time.time):
        self.arena,self.path,self.account,self.session,self.wall=arena,path,account,session,wall
        self.known=set();self.attach()
        self.offline_until=None

    def attach(self):
        self.arena._durable=self
        for field in self.arena._fields.values():field._durable_arena=self.arena
        if self.session is not None:
            self.session.visibility_views={r:f.result_view for r,f in self.arena._fields.items() if hasattr(f,'result_view')}

    def data(self):
        return dict(kind='private',account=self.account,arena=self.arena,
            name=getattr(self.session,'probe_character_name',b''),
            offline_until=self.offline_until,
            character=getattr(self.session,'probe_character_id',None))

    @contextmanager
    def unit(self):
        identity=id(self.arena)
        if identity in _units.get():yield;return
        before=codec.dumps(self.data(),clock=self.arena._clock,wall=self.wall)
        known=set(self.known);token=_units.set((*_units.get(),identity))
        try:
            with transaction(self.path) as db:
                yield
                self.attach()
                live={r:self.arena._match_ids[r] for r in self.arena._fields if r in self.arena._match_ids}
                matches=set(live.values())
                for match in known-matches:store.delete(db,match)
                if matches:
                    # An account-local arena can have only one durable active scene.
                    if len(matches)!=1:raise ValueError('Multiple private durable scenes')
                    room=next(r for r in self.arena.rooms.snapshot() if r.room_id in live)
                    payload=codec.dumps(self.data(),clock=self.arena._clock,wall=self.wall)
                    store.save(db,next(iter(matches)),payload,{self.account:room.owner_id},now=self.wall())
                self.known=matches
        except BaseException:
            restored,_=codec.loads(before,clock=self.arena._clock,wall=self.wall,rebase=False)
            arena_copy(self.arena,restored['arena'],self);self.known=known
            raise
        finally:_units.reset(token)


def private_method(method):
    @wraps(method)
    def wrapped(arena,*args,**kwargs):
        manager=getattr(arena,'_durable',None)
        if manager is None:return method(arena,*args,**kwargs)
        if method.__name__=='expire_turns' and all(arena._clock()<t[2] for t in arena._turns.values()):
            return method(arena,*args,**kwargs)
        if method.__name__=='finish_training' and args:
            room=next((r for r in arena.rooms.snapshot() if args[0] in r.members),None)
            field=None if room is None else arena._fields.get(room.room_id)
            if field is not None and not hasattr(field,'practice') and len(field.living_sides())>1:
                mine=getattr(field,'mining',None)
                if mine is None or mine.extracted_amount is None and field.living_actor_ids(args[0]):
                    return ()
        with manager.unit():return method(arena,*args,**kwargs)
    return wrapped


def private_service(method):
    @wraps(method)
    def wrapped(service,*args,**kwargs):
        manager=getattr(service.arena,'_durable',None)
        if manager is None:return method(service,*args,**kwargs)
        with manager.unit():return method(service,*args,**kwargs)
    return wrapped


def private_field(method):
    @wraps(method)
    def wrapped(component,*args,**kwargs):
        arena=getattr(component.field,'_durable_arena',None)
        manager=None if arena is None else getattr(arena,'_durable',None)
        if manager is None:return method(component,*args,**kwargs)
        with manager.unit():return method(component,*args,**kwargs)
    return wrapped


class BattleJournal:
    def __init__(self,hub,path,*,wall=time.time):
        self.hub,self.path,self.wall=hub,path,wall
        store.initialise(path)
        from tio.battle_settlement import initialise
        initialise(path)

    def data(self,battle):
        hub=self.hub
        retained={o:'active' if hub.battles.get(o) is battle else 'completed'
            for o in battle['humans'] if hub.battles.get(o) is battle or hub.completed.get(o) is battle}
        sessions={}
        for o in battle['reward_roster']:
            s=hub.players.get(o)
            if s is not None:sessions[o]=dict(account=s.account,name=s.probe_character_name,character=s.probe_character_id)
            else:sessions[o]=battle.get('durable_sessions',{})[o]
        return dict(kind='shared',battle=battle,retained=retained,sessions=sessions,
            offline={o:t for o,t in hub.offline.items() if o in retained},
            returning={o:t for o,t in hub.returning.items() if o in retained},next_id=hub.next_id)

    def birth(self,method,*args):
        """Atomically publish a new shared mine and its authoritative ownership."""
        hub=self.hub
        maps={name:dict(getattr(hub,name)) for name in ('battles','completed','players','identities','account_owners','offline','returning','tickets')}
        queues={o:deque(q) for o,q in hub.queues.items()};results=set(hub.results)
        try:
            with transaction(self.path) as db:
                battle=method(*args)
                from .world_runtime import admit
                admit(db,battle,now=self.wall())
                data=self.data(battle);battle['durable_sessions']=data['sessions']
                claim=battle.get('mine_claim')
                if claim and claim['owner_clan'] is not None:
                    db.execute('INSERT INTO mine_claim_leases VALUES (?,?,?,?)',
                        (battle['match_id'],claim['owner_clan'],claim['location'],claim['revision']))
                store.save(db,battle['match_id'],codec.dumps(data,clock=hub.clock,wall=self.wall),
                    {data['sessions'][o]['account']:o for o in data['retained']},now=self.wall())
            return battle
        except BaseException:
            for name,value in maps.items():setattr(hub,name,value)
            hub.queues=queues;hub.results=results
            raise

    @contextmanager
    def unit(self,battle):
        identity=id(battle);hub=self.hub
        if identity in _units.get():yield;return
        before=codec.capture_rollback(self.data(battle),clock=hub.clock,wall=self.wall)
        maps={name:dict(getattr(hub,name)) for name in ('battles','completed','players','identities','account_owners','offline','returning','tickets')}
        queues={o:deque(q) for o,q in hub.queues.items()};results=set(hub.results)
        token=_units.set((*_units.get(),identity))
        try:
            with transaction(self.path) as db:
                yield
                state=self.data(battle)
                # Live mine admissions extend the frozen reward roster. Keep
                # their metadata after hub.forget removes an expired session;
                # the snapshot's sessions alone cannot serve in-memory reads.
                # This assignment rolls back with the enclosing gameplay unit.
                battle['durable_sessions']=state['sessions']
                if not state['retained']:
                    store.delete(db,battle['match_id'])
                    if battle.get('kind')=='mine':
                        db.execute('DELETE FROM mine_claim_leases WHERE match_id=?',(battle['match_id'],))
                else:
                    payload=codec.dumps(state,clock=hub.clock,wall=self.wall)
                    store.save(db,battle['match_id'],payload,
                        {state['sessions'][o]['account']:o for o in state['retained']},
                        status='finished' if battle['finished'] else 'active',now=self.wall())
        except BaseException:
            restored=codec.restore_rollback(before,clock=hub.clock,wall=self.wall)
            battle.clear();battle.update(restored['battle'])
            for name,value in maps.items():setattr(hub,name,value)
            hub.queues=queues;hub.results=results
            raise
        finally:_units.reset(token)

    def quarantine_unjournalable(self,battle,error):
        """Preserve the last committed snapshot if quarantine cannot snapshot.

        A malformed in-memory match must not take the service's failure path
        down with it. Keep checkpoint bindings and outbox reports for repair;
        no replacement snapshot or invented terminal reward is committed.
        """
        if storage_failure(error):raise error
        hub=self.hub;match=battle['match_id']
        from tio import battle_settlement
        with transaction(self.path) as db:
            members=dict(db.execute('SELECT account,owner_id FROM battle_checkpoint_members WHERE match_id=?',(match,)))
            if db.execute('SELECT 1 FROM battle_checkpoints WHERE match_id=?',(match,)).fetchone():
                store.quarantine(self.path,match,error)
            else:
                members={data[0]:owner for owner,data in battle['reward_roster'].items()}
            battle_settlement.record_failure(self.path,match,members,error)
        battle['faulted']=type(error).__name__
        # A retired owner may have another scene already. Only detach exact
        # mappings to this failed match; durable bindings stay in SQLite.
        affected={owner for owner,value in (*hub.battles.items(),*hub.completed.items()) if value is battle}
        for owner in affected:
            session=hub.players.get(owner)
            hub.battles.pop(owner,None);hub.completed.pop(owner,None)
            hub.forget(owner)
            if session is not None:
                try:session.stop()
                except Exception as stop_error:
                    if storage_failure(stop_error):raise
                    LOG.error('quarantine_session_close_failed match=%s error_type=%s',match,type(stop_error).__name__)
        LOG.error('match_journal_quarantined match=%s error_type=%s accounts=%d',match,type(error).__name__,len(members))

    def start(self,method,first,seats,teams,bots,consume):
        hub=self.hub;prior=set(hub.battles);queues={o:deque(q) for o,q in hub.queues.items()}
        try:
            with transaction(self.path) as db:
                result=method(hub,first,seats,teams,bots,lambda:None)
                new={id(b):b for o,b in hub.battles.items() if o not in prior}
                if len(new)!=1:raise ValueError('New authoritative battle missing')
                battle=next(iter(new.values()))
                from .world_runtime import admit
                admit(db,battle,now=self.wall())
                data=self.data(battle)
                battle['durable_sessions']=data['sessions']
                store.save(db,battle['match_id'],codec.dumps(data,clock=hub.clock,wall=self.wall),
                    {data['sessions'][o]['account']:o for o in data['retained']},now=self.wall())
            consume();return result
        except BaseException:
            for o in set(hub.battles)-prior:
                hub.battles.pop(o,None)
                hub.account_owners.pop(hub.players[o].account,None)
            hub.queues=queues
            raise

    def recover(self):
        hub=self.hub;restored=[]
        for match,payload,checksum,status,members in store.read(self.path):
            if status=='quarantined':continue
            before={name:dict(getattr(hub,name)) for name in
                ('battles','completed','players','queues','account_owners','offline','returning','private')}
            results=set(hub.results);next_id=hub.next_id
            try:
                if hashlib.sha256(payload.encode()).hexdigest()!=checksum:raise ValueError('Checkpoint checksum mismatch')
                state,timing=codec.loads(payload,clock=hub.clock,wall=self.wall)
                if state['kind']=='shared':self.restore_shared(match,state,timing,members)
                elif state['kind']=='private':self.restore_private(match,state,timing,members)
                else:raise ValueError('Unknown checkpoint kind')
            except Exception as error:
                for name,value in before.items():setattr(hub,name,value)
                hub.results=results;hub.next_id=next_id
                if storage_failure(error):raise
                store.quarantine(self.path,match,error)
                from tio import battle_settlement
                battle_settlement.record_failure(self.path,match,members,error)
                LOG.error('battle_checkpoint_quarantined match=%s error_type=%s',match,type(error).__name__)
            else:
                restored.append(match)
                LOG.info('battle_checkpoint_restored match=%s kind=%s accounts=%d',match,state['kind'],len(members))
        return restored

    def restore_shared(self,match,state,timing,members):
        hub=self.hub;b=state['battle'];retained=state['retained'];metadata=state['sessions']
        expected={metadata[o]['account']:o for o in retained}
        if b['match_id']!=match or expected!=members or not retained:raise ValueError('Checkpoint ownership mismatch')
        if any(account in hub.account_owners or account in hub.private for account in members):raise ValueError('Duplicate recovered account')
        b['durable_sessions']=metadata
        rebind(b['arena'],self.path)
        for name in ('deadline','fault_retry'):
            if name in b:b[name]+=timing['shift']
        if 'created_at' in b:b['created_at']+=timing['shift']
        if b.get('full_turn'):b['full_turn']=(b['full_turn'][0],b['full_turn'][1]+timing['shift'])
        # Overlay previously frozen outbox reports before any new settlement.
        from contextlib import closing
        from tio.db_transaction import connect
        from tio.battle_settlement import unpack
        with closing(connect(self.path)) as db:
            pending=False
            for account,payload in db.execute('SELECT account,payload FROM battle_settlement_jobs WHERE match_id=?',(match,)):
                owner=next(o for o,data in metadata.items() if data['account']==account)
                b.setdefault('settlement_inputs',{})[owner]=unpack(payload)
                pending=True
            paid=set()
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='battle_rewards'").fetchone():
                paid={o for o,m in metadata.items() if db.execute(
                    'SELECT 1 FROM battle_rewards WHERE match_id=? AND account=?',(match,m['account'])).fetchone()}
            b['settled'].update(paid)
            # A departed team member can have an early defeat receipt while
            # the remaining players continue. Only retained active owners
            # make an old active checkpoint terminal during recovery.
            active={o for o,phase in retained.items() if phase=='active'}
            terminal=bool(active & (set(b.get('settlement_inputs',{}))-b['settled'] | paid))
            if b.get('kind')=='mine':
                # Independently retired miners can already have receipts while
                # their escorts/raiders continue in the same authoritative mine.
                active=b['mine_active']
                pending_owners=set(b.get('settlement_inputs',{}))-b['settled']
                terminal=bool(active & (pending_owners | paid))
            if b.get('kind')=='assault':
                active={o for o,phase in retained.items() if phase=='active'}
                terminal=bool(active & (set(b.get('settlement_inputs',{}))-b['settled'] | paid))
            if not b['finished'] and terminal:
                # A durable terminal report takes precedence over an older
                # active snapshot, including a planned stop interrupted midway.
                b['faulted']='RecoveredSettlement';b['fault_retry']=0
        from tio.arena_service import ArenaService
        sessions={o:OfflineSession(account=m['account'],database=self.path,probe_character_id=m['character'],
            probe_character_name=m['name'],arena=ArenaService(clock=hub.clock)) for o,m in metadata.items()}
        b['humans']=set(retained)
        # All recovered clients are offline; they must reload the exact scene.
        from .battle_reconnect import RECONNECT_SECONDS
        for o in retained:
            hub.players[o]=sessions[o];hub.queues[o]=deque();hub.account_owners[metadata[o]['account']]=o
            hub.offline[o]=(state['offline'][o]+timing['shift'] if o in state['offline'] else
                hub.clock()+max(0,RECONNECT_SECONDS-timing['elapsed']))
            if retained[o]=='active':hub.battles[o]=b
            elif retained[o]=='completed':hub.completed[o]=b;hub.results.add(o)
            else:raise ValueError('Unknown recovered membership phase')
        b['arena']._loading[b['room'].room_id].update(retained)
        hub.next_id=max(hub.next_id,state['next_id'],*retained)

    def restore_private(self,match,state,timing,members):
        hub=self.hub;arena=state['arena'];account=state['account']
        rooms=[r for r in arena.rooms.snapshot() if arena._match_ids.get(r.room_id)==match]
        if len(rooms)!=1 or members!={account:rooms[0].owner_id}:raise ValueError('Private checkpoint ownership mismatch')
        if account in hub.private or account in hub.account_owners:raise ValueError('Duplicate recovered account')
        rebind(arena,self.path);room=rooms[0]
        session=OfflineSession(account=account,database=self.path,probe_character_id=room.owner_id,
            probe_character_name=state['name'],arena=arena,
            training_matches={r.room_id:tuple(m for m in r.members if m!=r.owner_id) for r in rooms},
            visibility_views={r:f.result_view for r,f in arena._fields.items() if hasattr(f,'result_view')})
        manager=PrivateJournal(arena,self.path,account,session=session,wall=self.wall);manager.known={match}
        manager.offline_until=state.get('offline_until')
        from .battle_reconnect import RECONNECT_SECONDS
        remaining=(manager.offline_until-self.wall() if manager.offline_until is not None else
                   RECONNECT_SECONDS-timing['elapsed'])
        hub.private[account]=(session,hub.clock()+max(0,remaining))


def shared_method(method):
    @wraps(method)
    def wrapped(hub,*args,**kwargs):
        manager=getattr(hub,'journal',None)
        if manager is None:return method(hub,*args,**kwargs)
        with hub.lock:
            if method.__name__=='start_match':return manager.start(method,*args,**kwargs)
            first=args[0] if args else None
            battle=first if isinstance(first,dict) and 'match_id' in first else hub.battles.get(first) or hub.completed.get(first)
            if battle is None:return method(hub,*args,**kwargs)
            # Skill-list replies only read the battle; retain the hub lock.
            if method.__name__=='battle_action' and len(args)>1 and args[1][:2]==b'\xc8\x12':
                return method(hub,*args,**kwargs)
            if method.__name__=='tick_battle':
                arena=battle['arena'];room=battle['room'];field=battle['field']
                turn=arena._turns.get(room.room_id)
                idle=(arena._loading[room.room_id]!=set(room.members) and hub.clock()<=battle['deadline']
                      or turn is not None and hub.clock()<turn[2] and len(field.living_sides())>1
                      and (any(field.actor(i).action_points>0 for i in field.living_actor_ids(turn[0]))
                           or hub.turn_has_open_loot(battle,turn)))
                if battle.get('kind')=='mine' and any(not field.living_actor_ids(o) for o in battle['mine_active']):idle=False
                if battle.get('kind') == 'contract':
                    metadata = field.contract_metadata
                    boss = metadata.get('boss')
                    if boss is not None and not field.actor(boss).health and 'boss_item' not in metadata:
                        idle = False
                if battle.get('kind')=='assault' and hub.assault_wall()>=battle['assault_ends']:idle=False
                if battle['finished'] or idle:return method(hub,*args,**kwargs)
            try:
                with manager.unit(battle):return method(hub,*args,**kwargs)
            except Exception as error:
                if method.__name__!='retry_quarantined' or storage_failure(error):raise
                manager.quarantine_unjournalable(battle,error)
    return wrapped
