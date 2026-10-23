"""Connection lifetime, fresh reads and slow-peer isolation of hub timings."""
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import patch
import sqlite3
import threading
import unittest

import test_shared_team_arena as fixture
from test_team_heartbeat import TeamHeartbeatTests
from tio.db_transaction import transaction
from tio.performance import timed_block


class ListingConnections(unittest.TestCase):
    setUp=fixture.SharedTeamTests.setUp

    def ready(self):
        self.hub.init_assault(self.path)
        for session in self.sessions:self.hub.identity(session)
        # Count only the assault membership connection, not city projection SQL.
        self.hub.city=lambda owner:SimpleNamespace(pool='starter')

    def test_one_lazy_connection_per_pass_and_closed_afterwards(self):
        self.ready()
        import tio.db_transaction as sql
        opened=[];original=sql.connect
        def connect(*a,**kw):
            db=original(*a,**kw);opened.append(db);return db
        with patch.object(sql,'connect',side_effect=connect):
            with self.hub.lock:self.hub.publish_room_lists()
        self.assertEqual(len(opened),1)
        with self.assertRaises(sqlite3.ProgrammingError):opened[0].execute('SELECT 1')
        with patch.object(sql,'connect',side_effect=connect):
            with self.hub.lock:self.hub.publish_room_lists()
        self.assertEqual(len(opened),2)

    def test_busy_memory_state_needs_no_connection(self):
        self.ready()
        self.hub.offline.update({owner:100 for owner in self.hub.players})
        with patch('tio.db_transaction.connect',side_effect=AssertionError('idle connection')):
            with self.hub.lock:self.hub.publish_room_lists()

    def test_queries_see_external_commits_within_same_pass(self):
        self.ready();seen=[];original=self.hub.assault_store._own_group
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE freshness(value INTEGER)');db.execute('INSERT INTO freshness VALUES(0)')
        def lookup(db,account,event_id=None):
            seen.append(db.execute('SELECT value FROM freshness').fetchone()[0])
            with closing(sqlite3.connect(self.path)) as writer,writer:
                writer.execute('UPDATE freshness SET value=value+1')
            return original(db,account,event_id)
        with patch.object(self.hub.assault_store,'_own_group',side_effect=lookup):
            with self.hub.lock:self.hub.publish_room_lists()
        self.assertEqual(seen,[0,1,2,3])

    def test_outer_transaction_connection_remains_open(self):
        self.ready()
        with transaction(self.path) as db:
            with self.hub.lock:self.hub.publish_room_lists()
            self.assertEqual(db.execute('SELECT 1').fetchone(),(1,))

    def test_membership_exception_closes_connection(self):
        self.ready();opened=[];original=sqlite3.connect
        def connect(*a,**kw):
            db=original(*a,**kw);opened.append(db);return db
        with patch('tio.db_transaction.connect',side_effect=connect),patch.object(self.hub.assault_store,'_own_group',side_effect=ValueError('fixture')):
            with self.assertRaises(ValueError):
                with self.hub.lock:self.hub.publish_room_lists()
        self.assertEqual(len(opened),1)
        with self.assertRaises(sqlite3.ProgrammingError):opened[0].execute('SELECT 1')


class PositiveMembership(unittest.TestCase):
    def test_full_group_and_event_filter_match_with_borrowed_connection(self):
        from test_territories import TerritoriesTests
        case=TerritoriesTests();case.setUp();self.addCleanup(case.doCleanups)
        group=case.group('a')
        with closing(sqlite3.connect(case.path)) as db:
            for owner in ('a0','a1','b0'):
                self.assertEqual(case.store.own_group(owner),case.store.own_group(owner,connection=db))
            self.assertEqual(case.store.own_group('a0',group['event_id'],connection=db)['id'],group['id'])
            self.assertIsNone(case.store.own_group('a0','missing-event',connection=db))


class PacketIsolation(TeamHeartbeatTests):
    def test_slow_send_does_not_hold_hub_lock(self):
        self.hub.put(self.owner,b'\x39');entered=threading.Event();release=threading.Event();errors=[]
        def send(frame):entered.set();release.wait(3)
        self.socket.sendall=send
        def drain():
            try:self.drain()
            except BaseException as error:errors.append(error)
        worker=threading.Thread(target=drain);worker.start()
        try:
            self.assertTrue(entered.wait(2))
            acquired=self.hub.lock.acquire(timeout=.5)
            self.assertTrue(acquired,'socket write held shared hub lock')
            if acquired:self.hub.lock.release()
        finally:release.set();worker.join(4)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[])

    def test_failed_send_does_not_prepare_later_packets(self):
        self.hub.put(self.owner,b'\x39',b'\x9e')
        self.socket.sendall=lambda frame:(_ for _ in ()).throw(ConnectionResetError())
        with patch.object(self.hub,'prepare_queued_frame',wraps=self.hub.prepare_queued_frame) as prepare:
            with self.assertRaises(ConnectionResetError):self.drain()
        self.assertEqual(prepare.call_count,1)


class TimingBoundaries(unittest.TestCase):
    def test_exception_records_elapsed(self):
        with patch('tio.performance.observe') as observe:
            with self.assertRaises(ValueError):
                with timed_block('hub.phase.battles'):raise ValueError('fixture')
        observe.assert_called_once();self.assertGreaterEqual(observe.call_args.args[1],0)

    def test_commit_and_rollback_report_without_changing_atomicity(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp,patch('tio.db_transaction.observe') as observe:
            path=Path(tmp)/'test.db'
            with transaction(path) as db:db.execute('CREATE TABLE data(value)')
            with self.assertRaises(ValueError):
                with transaction(path) as db:
                    db.execute('INSERT INTO data VALUES(1)');raise ValueError('fixture')
            with closing(sqlite3.connect(path)) as db:self.assertEqual(db.execute('SELECT * FROM data').fetchall(),[])
            names=[c.args[0] for c in observe.call_args_list]
            self.assertIn('sql.commit',names);self.assertIn('sql.rollback',names)

