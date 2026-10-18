"""Regression checks for request-scoped projections and safe idle shortcuts."""
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import patch
import sqlite3
import threading
import unittest

import test_shared_team_arena as team_fixture
import test_bank_economy as bank_fixture
from server.economy_runtime import SharedEconomy
from tio.owned_pets import OwnedPetStore
from tio.protocol.battle_members import decode_battle_members
from tio.protocol.wagers import encode_join
from tio import performance


class LobbyPerformanceTests(unittest.TestCase):
    setUp=team_fixture.SharedTeamTests.setUp
    send=team_fixture.SharedTeamTests.send
    create=team_fixture.SharedTeamTests.create

    def filled(self):
        room=self.create(0,4)
        for index in (1,2,3):self.send(index,encode_join(room.identity))
        for q in self.hub.queues.values():q.clear()
        return room

    def test_four_owners_read_once_each_and_keep_private_identity_per_viewer(self):
        room=self.filled();original=OwnedPetStore.list;reads=[]
        def load(store,account):reads.append(account);return original(store,account)
        with patch.object(OwnedPetStore,'list',load):self.hub.notify(room,entering=(room.members[-1],))
        self.assertEqual(reads,['alice','bob','carol','dave'])
        for viewer in room.members:
            packets=list(self.hub.queues[viewer]);packet=next(p for p in packets if p[:1]==b'\x25')
            mode,update,records=decode_battle_members(packet)
            self.assertEqual(mode,4);self.assertEqual(update,int(viewer!=room.members[-1]))
            self.assertEqual(tuple(r.name for r in records),(b'alice',b'bob',b'carol',b'dave'))
            self.assertEqual(tuple(r.character_id for r in records),tuple(1 if owner==viewer else owner for owner in room.members))
            self.assertTrue(all(len(r.group1)==1 for r in records))
            self.assertEqual(any(p[:1]==b'\x6c' for p in packets),viewer==room.members[-1])

    def test_next_notification_reloads_and_ready_state_is_not_cached(self):
        room=self.filled();self.hub.notify(room)
        room.ready.add(room.members[1])
        for q in self.hub.queues.values():q.clear()
        original=OwnedPetStore.list;reads=[]
        def load(store,account):reads.append(account);return original(store,account)
        with patch.object(OwnedPetStore,'list',load):self.hub.notify(room)
        self.assertEqual(len(reads),4)
        for viewer in room.members:
            records=decode_battle_members(self.hub.queues[viewer][-1])[2]
            self.assertEqual([r.ready for r in records],[0,1,0,0])

    def test_city_lookup_count_does_not_grow_with_room_count(self):
        for index in (0,1,2):self.create(index,4)
        owner=self.hub.identity(self.sessions[3]);original=self.hub.city
        with patch.object(self.hub,'city',wraps=original) as city:
            self.hub.list_packet(owner)
        self.assertEqual(city.call_count,1)


class EconomyPerformanceTests(bank_fixture.BankFixture):
    def setUp(self):
        super().setUp()
        # City services have separate router/configuration fixtures.
        self.enterContext(patch('server.services_runtime.tick'))

    def router(self):
        return SimpleNamespace(team_arena=SimpleNamespace(lock=threading.RLock()),lock=threading.Lock(),active_accounts={})

    def test_no_due_marks_skips_busy_scan_and_writer_transaction(self):
        economy=SharedEconomy(self.path,clock=lambda:1)
        with patch('server.economy_runtime.busy_accounts',side_effect=AssertionError('Unexpected busy scan')),patch('server.economy_runtime.transaction',side_effect=AssertionError('Unexpected writer')),patch.object(economy.auction,'tick') as auction:
            economy.tick(self.router())
        auction.assert_called_once()

    def test_clan_maintenance_still_runs_without_marks(self):
        economy=SharedEconomy(self.path,clock=lambda:1);economy.next_clan_tick=0
        with patch('server.clan_gameplay.maintenance') as maintenance,patch('server.economy_runtime.busy_accounts',side_effect=AssertionError('Unexpected busy scan')):
            economy.tick(self.router())
        maintenance.assert_called_once();self.assertEqual(economy.next_clan_tick,61)

    def test_newly_retained_owner_is_checked_after_due_precheck(self):
        from tio import bank_economy as bank
        mark=self.call(bank.mark_item,'alice',17,1,'1234','perf-mark',now=self.now)
        self.call(bank.lend_marked,'alice',mark['mark_id'],'bob','perf-lend',now=self.now)
        router=self.router();economy=SharedEconomy(self.path,clock=lambda:1)
        def newly_busy(hub,db):
            self.assertTrue(db.in_transaction)
            self.assertTrue(router.team_arena.lock._is_owned())
            return {'bob'}
        with patch('tio.bank_economy.time.time',return_value=self.now+86401),patch('server.economy_runtime.busy_accounts',side_effect=newly_busy):
            economy.tick(router)
        self.assertEqual(self.read('SELECT holder,state FROM bank_item_marks'),[('bob','active')])


class TimingTests(unittest.TestCase):
    def test_timing_preserves_exception_and_releases_lock(self):
        lock=threading.Lock()
        with self.assertRaisesRegex(ValueError,'original'):
            with performance.timed_lock(lock,'test.lock'):raise ValueError('original')
        self.assertTrue(lock.acquire(blocking=False));lock.release()
        @performance.timed('test.failure')
        def fail():raise ValueError('original')
        with self.assertRaisesRegex(ValueError,'original'):fail()

    def test_collector_has_bounded_storage(self):
        with performance._lock:
            saved=performance._values.copy();performance._values.clear()
        try:
            for index in range(1000):performance.observe('test.'+str(index),.001)
            self.assertEqual(len(performance._values),32)
            self.assertTrue(all(len(v[3])==len(performance.LIMITS) for v in performance._values.values()))
        finally:
            with performance._lock:performance._values.clear();performance._values.update(saved)
