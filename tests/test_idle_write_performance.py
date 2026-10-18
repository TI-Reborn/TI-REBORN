"""Negative read hints never authorize mutations or change economic results."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing,contextmanager
import sqlite3
import unittest
from unittest.mock import patch

import test_pve_contracts as contracts_fixture
import test_travel_party as party_fixture
import test_sc_auction as auction_fixture
from tio import pve_contracts,travel_party,sc_auction
from tio.db_transaction import transaction


@contextmanager
def change_before_writer(module,change):
    original=module.transaction;changed=False
    @contextmanager
    def interleaved(path):
        nonlocal changed
        if not changed:
            changed=True
            with original(path) as db:change(db)
        with original(path) as db:yield db
    with patch.object(module,'transaction',interleaved):yield


class ContractIdleTests(unittest.TestCase):
    setUp=contracts_fixture.ContractTests.setUp
    accept=contracts_fixture.ContractTests.accept
    start=contracts_fixture.ContractTests.start

    def test_empty_and_unexpired_reads_do_not_request_writer(self):
        record=self.accept()
        with patch.object(pve_contracts,'transaction',side_effect=AssertionError('No change')):
            self.assertEqual(self.store.get(record['id']),record)
            self.assertEqual(self.store.active('party-one'),record)
            self.assertEqual(self.store.target_for('alice'),record['target'])
            self.assertIsNone(self.store.target_for('missing'))
            self.assertIsNone(self.store.get('missing'))
            self.assertEqual(self.store.expire(),[])

    def test_exact_deadline_expires_once_and_unlocks_members(self):
        record=self.accept();self.now[0]=record['expires_at']
        self.assertIsNone(self.store.target_for('alice'))
        self.assertEqual(self.store.get(record['id'])['state'],'expired')
        with patch.object(pve_contracts,'transaction',side_effect=AssertionError('Already expired')):
            self.assertEqual(self.store.expire(),[])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pve_contract_locks').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM pve_contract_events WHERE state='expired'").fetchone()[0],1)

    def test_extended_deadline_before_writer_is_revalidated(self):
        record=self.accept();self.now[0]=record['expires_at']
        with change_before_writer(pve_contracts,lambda db:db.execute('UPDATE pve_contract_instances SET expires_at=expires_at+100 WHERE id=?',(record['id'],))):
            self.assertIsNotNone(self.store.target_for('alice'))
        self.assertEqual(self.store.get(record['id'])['state'],'accepted')

    def test_active_battle_never_expires_and_outer_transaction_is_preserved(self):
        record=self.accept()
        with self.assertRaisesRegex(RuntimeError,'outer rollback'):
            with transaction(self.path) as db:
                db.execute("UPDATE pve_contract_instances SET state='active' WHERE id=?",(record['id'],))
                self.now[0]=record['expires_at']+1
                self.assertEqual(self.store.get(record['id'])['state'],'active')
                raise RuntimeError('outer rollback')
        self.now[0]=1000
        self.assertEqual(self.store.get(record['id'])['state'],'accepted')

    def test_expiry_failure_rolls_back_state_locks_and_events(self):
        record=self.accept()
        with closing(sqlite3.connect(self.path)) as db,db:
            before=db.execute('SELECT * FROM pve_contract_locks').fetchall()
            db.execute("CREATE TRIGGER reject_expiry BEFORE INSERT ON pve_contract_events WHEN NEW.state='expired' BEGIN SELECT RAISE(ABORT,'injected'); END")
        self.now[0]=record['expires_at']
        with self.assertRaises(sqlite3.IntegrityError):self.store.target_for('alice')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT state FROM pve_contract_instances').fetchone()[0],'accepted')
            self.assertEqual(db.execute('SELECT * FROM pve_contract_locks').fetchall(),before)

    def test_concurrent_expirers_create_one_event(self):
        record=self.accept();self.now[0]=record['expires_at']
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.store.expire(),range(2)))
        self.assertEqual(sum(map(len,results)),1)


class PartyIdleTests(unittest.TestCase):
    setUp=party_fixture.TravelPartyTests.setUp
    seed_pets=party_fixture.TravelPartyTests.seed_pets
    join=party_fixture.TravelPartyTests.join

    def group(self):
        room=self.party.create('alice');self.join('bravo');return room['id']

    def test_unchanged_online_offline_and_leader_need_no_writer(self):
        identity=self.group()
        with patch.object(travel_party,'transaction',side_effect=AssertionError('Unchanged')):
            self.party.set_online('alice',True);self.party.recover_leader(identity)
        self.party.set_online('bravo',False)
        with patch.object(travel_party,'transaction',side_effect=AssertionError('Already offline')):
            self.party.set_online('bravo',False)

    def test_disconnect_bookkeeping_repaired_even_when_status_matches(self):
        self.group()
        with transaction(self.path) as db:db.execute('INSERT INTO travel_party_disconnects VALUES (?,?)',('alice',1))
        self.party.set_online('alice',True)
        with closing(sqlite3.connect(self.path)) as db:self.assertIsNone(db.execute('SELECT 1 FROM travel_party_disconnects WHERE owner=?',('alice',)).fetchone())
        self.party.set_online('bravo',False)
        with transaction(self.path) as db:db.execute('DELETE FROM travel_party_disconnects WHERE owner=?',('bravo',))
        self.party.set_online('bravo',False)
        with closing(sqlite3.connect(self.path)) as db:self.assertIsNotNone(db.execute('SELECT 1 FROM travel_party_disconnects WHERE owner=?',('bravo',)).fetchone())

    def test_grace_boundary_and_reconnecting_leader(self):
        identity=self.group();self.party.set_online('alice',False);self.now+=59
        with patch.object(travel_party,'transaction',side_effect=AssertionError('Grace not over')):self.assertEqual(self.party.recover_leader(identity)['leader'],'alice')
        self.now+=1
        def reconnect(db):
            db.execute("UPDATE travel_party_members SET online=1 WHERE owner='alice'")
            db.execute("DELETE FROM travel_party_disconnects WHERE owner='alice'")
        with change_before_writer(travel_party,reconnect):self.assertEqual(self.party.recover_leader(identity)['leader'],'alice')
        self.party.set_online('alice',False);self.now+=60
        self.assertEqual(self.party.recover_leader(identity)['leader'],'bravo')

    def test_member_removed_before_writer_is_not_resurrected(self):
        identity=self.group()
        with change_before_writer(travel_party,lambda db:travel_party.PartyStore._delete_room(db,identity)):
            self.assertIsNone(self.party.set_online('alice',False))
        self.assertIsNone(self.party.info('bravo'))


class AuctionIdleTests(unittest.TestCase):
    setUp=auction_fixture.SCEligibleBoundaryTests.setUp
    tearDown=auction_fixture.SCEligibleBoundaryTests.tearDown
    store=auction_fixture.SCEligibleBoundaryTests.store
    credits=auction_fixture.SCEligibleBoundaryTests.credits

    def test_idle_tick_without_or_with_replenishment_needs_no_writer(self):
        store=self.store()
        with patch.object(sc_auction,'transaction',side_effect=AssertionError('No due lot')):
            self.assertEqual(store.tick(now=101),0)
            self.assertEqual(store.tick(now=108,replenish=False),0)

    def test_bot_fires_on_last_second_then_lot_closes_on_new_deadline(self):
        store=self.store();store.set_bot('alice-login',1,0,0,2,request='idle-last-second-bot',now=101)
        with patch.object(sc_auction,'transaction',side_effect=AssertionError('Too early')):self.assertEqual(store.tick(now=108,replenish=False),0)
        self.assertEqual(store.tick(now=109,replenish=False),1)
        self.assertEqual(store.get(1)['bids'],1)
        store.tick(now=113,replenish=False)
        self.assertEqual(store.get(1)['state'],'won')

    def test_won_expiry_and_missing_offer_are_not_skipped(self):
        store=self.store(automatic=False);store.bid('alice-login',1,request='idle-expiry-bid-001',now=101)
        store.tick(now=114,replenish=False);lot=store.get(1)
        self.assertEqual(lot['state'],'won')
        with patch.object(sc_auction,'transaction',side_effect=AssertionError('Not expired')):self.assertEqual(store.tick(now=lot['expires_at']-1,replenish=False),0)
        self.assertEqual(store.tick(now=lot['expires_at'],replenish=False),1)
        self.assertEqual(store.get(1)['state'],'expired')
        self.assertEqual(store.tick(now=lot['expires_at']+1),1)

    def test_replenishment_respects_full_cap_including_unclaimed_wins(self):
        store=self.store();store.rules['maximum_live_lots']=1
        with transaction(self.path) as db:db.execute("UPDATE sc_auction_lots SET state='won',expires_at=1000 WHERE id=1")
        with patch.object(sc_auction,'transaction',side_effect=AssertionError('Cap full')):self.assertEqual(store.tick(now=101),0)

    def test_extended_lot_before_writer_cannot_close_early(self):
        store=self.store(automatic=False)
        with change_before_writer(sc_auction,lambda db:db.execute('UPDATE sc_auction_lots SET ends=200 WHERE id=1')):
            self.assertEqual(store.tick(now=110,replenish=False),0)
        self.assertEqual(store.get(1)['state'],'active')

    def test_close_failure_rolls_back_and_retry_closes_once(self):
        store=self.store(automatic=False)
        with transaction(self.path) as db:db.execute("CREATE TRIGGER reject_close BEFORE INSERT ON sc_auction_history WHEN NEW.action='closed' BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):store.tick(now=110,replenish=False)
        self.assertEqual(store.get(1)['state'],'active')
        with transaction(self.path) as db:db.execute('DROP TRIGGER reject_close')
        self.assertEqual(store.tick(now=110,replenish=False),1)
        self.assertEqual(store.tick(now=110,replenish=False),0)
