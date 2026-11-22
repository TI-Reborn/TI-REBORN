"""Real combat, durable settlement retries and independent shared matches."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

import test_shared_team_arena as fixtures
import test_multi_account as tcp_fixtures
from tio import battle_settlement
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.player_statistics import battle_report
from tio.ranks import battle_report as rank_report
from server.failure_policy import storage_failure


class BattleFailureTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.SharedTeamTests();self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        for session in self.case.sessions:session.stop=Mock()
        self.owners,self.battle=self.case.open_battle()
        self.field=self.battle['field'];self.hub=self.case.hub

    def kill(self):
        attacker,victim=(self.field.actor_ids(o)[0] for o in self.owners)
        self.field._actors[victim]=replace(self.field.actor(victim),x=5,y=6,health=1)
        self.field.combat.rng=SimpleNamespace(randrange=lambda n:0,randint=lambda a,b:a)
        self.case.send(0,encode_attack_request(AttackRequest(attacker,5,6)))
        self.assertIn((attacker,victim),self.field.combat.rank_kills)
        return attacker,victim

    def rows(self,query):
        with closing(sqlite3.connect(self.case.path)) as db:return db.execute(query).fetchall()

    def second_match(self):
        for index in (2,3):self.case.create(index);self.case.send(index,b'\x2e')
        owners=[self.hub.identities[s] for s in self.case.sessions[2:]]
        battle=self.hub.battles[owners[0]]
        for index in (2,3):self.case.send(index,b'\x36')
        return owners,battle

    def test_victim_reconnect_expiry_preserves_kill_and_both_accounts(self):
        _,victim=self.kill()
        self.hub.disconnect(self.case.sessions[1]);self.case.now=self.hub.offline[self.owners[1]]
        self.hub.expire_reconnects()
        self.assertNotIn(victim,self.field._actors)
        self.assertEqual(battle_report(self.field.combat,self.owners[0])[1],{1:[1,0]})
        self.hub.settle(self.battle,self.owners[0],1)
        self.assertEqual(self.rows('SELECT account,kills,deaths FROM player_battle_statistics ORDER BY account'),
                         [('alice',1,0),('bob',0,1)])
        self.assertEqual(self.rows('SELECT account,rating FROM soldier_ratings ORDER BY account'),[('alice',1),('bob',-1)])
        self.assertEqual(len(self.rows('SELECT * FROM battle_rewards')),2)

    def test_removed_killer_preserves_victim_rank_death_cause(self):
        attacker,victim=self.kill();self.hub.settle(self.battle,self.owners[0],0,escaped=True)
        self.hub.remove_from_battle(self.battle,self.owners[0])
        self.assertNotIn(attacker,self.field._actors)
        self.assertEqual(rank_report(self.field.combat,self.owners[1])[victim],(0,True))
        self.hub.settle(self.battle,self.owners[1],0)
        self.assertEqual(self.rows("SELECT penalty FROM rank_battle_audit WHERE account='bob'"),[(5,)])
        self.assertEqual(self.rows("SELECT rating FROM soldier_ratings WHERE account='bob'"),[(-1,)])

    def test_shutdown_captures_every_report_before_removing_actors(self):
        self.kill();self.hub.shutdown_battles();self.hub.shutdown_battles()
        self.assertEqual(self.rows('SELECT account,kills,deaths FROM player_battle_statistics ORDER BY account'),
                         [('alice',1,0),('bob',0,1)])
        self.assertEqual(len(self.rows('SELECT * FROM battle_rewards')),2)
        self.assertEqual(self.rows('SELECT * FROM battle_settlement_jobs'),[])

    def test_actor_ownership_is_immutable_after_departure(self):
        attacker,_=self.kill();owners=self.field.combat.actor_owners
        with self.assertRaises(TypeError):owners[attacker]=99
        self.field.remove_owner(self.owners[0])
        self.assertEqual(owners[attacker],self.owners[0])

    def test_tick_failure_only_closes_affected_match(self):
        owners,good=self.second_match();original=self.hub.tick_battle
        def tick(battle):
            if battle is self.battle:raise KeyError('Injected bad match')
            original(battle)
        with patch.object(self.hub,'tick_battle',side_effect=tick):self.hub.tick()
        self.assertTrue(self.battle['finished']);self.assertFalse(good['finished'])
        for session in self.case.sessions[:2]:session.stop.assert_called_once()
        for session in self.case.sessions[2:]:session.stop.assert_not_called()
        self.assertIs(self.hub.battles[owners[0]],good)
        self.assertEqual(self.rows('SELECT account,resolved FROM battle_failure_audit ORDER BY account'),[('alice',1),('bob',1)])
        self.assertEqual(len(self.rows('SELECT * FROM battle_rewards')),2)

    def test_action_failure_is_quarantined_without_losing_committed_kill(self):
        self.second_match();self.kill()
        with patch.object(self.hub,'perform_action',side_effect=RuntimeError('Injected projection failure')):
            self.assertTrue(self.hub.handle(self.case.sessions[0],b'\x37'))
        self.assertEqual(self.rows('SELECT account,kills,deaths FROM player_battle_statistics ORDER BY account'),
                         [('alice',1,0),('bob',0,1)])
        self.assertFalse(battle_settlement.blocked(self.case.path,'alice'))
        self.assertEqual(len(self.hub.battles),2)

    def test_failed_account_retry_preserves_other_result_and_runs_other_match(self):
        owners,good=self.second_match()
        # Finish a match with a deterministic winner, then fail only Alice's
        # reward transaction. This rolls back all of her derived statistics.
        for i,a in tuple(self.field._actors.items()):
            if self.field.side(a.owner_id)!=self.field.side(self.owners[0]):
                self.field._actors[i]=replace(a,health=0)
        battle_settlement.initialise(self.case.path)
        # Create the reward table without settling any real participant.
        with closing(sqlite3.connect(self.case.path)) as db,db:
            db.execute('CREATE TABLE battle_rewards(match_id TEXT,account TEXT,result INTEGER,credits INTEGER,PRIMARY KEY(match_id,account))')
            db.execute("CREATE TRIGGER reject_alice BEFORE INSERT ON battle_rewards WHEN new.account='alice' BEGIN SELECT RAISE(ABORT,'Injected individual write failure'); END")
        self.hub.tick()
        self.assertTrue(self.battle['faulted']);self.assertFalse(self.battle['finished'])
        self.assertEqual(self.rows('SELECT account,result FROM battle_rewards'),[('bob',0)])
        self.assertEqual(self.rows('SELECT account FROM battle_settlement_jobs'),[('alice',)])
        self.assertTrue(battle_settlement.blocked(self.case.path,'alice'))
        self.assertFalse(battle_settlement.blocked(self.case.path,'bob'))
        self.assertIs(self.hub.battles[owners[0]],good)
        self.assertTrue(self.hub.handle(self.case.sessions[0],b'\x37'))
        with closing(sqlite3.connect(self.case.path)) as db,db:db.execute('DROP TRIGGER reject_alice')
        self.case.now=5;self.hub.tick()
        self.assertTrue(self.battle['finished'])
        self.assertEqual(self.rows('SELECT account,result FROM battle_rewards ORDER BY account'),[('alice',1),('bob',0)])
        self.assertEqual(self.rows('SELECT * FROM battle_settlement_jobs'),[])
        self.assertFalse(battle_settlement.blocked(self.case.path,'alice'))
        self.assertEqual(len(self.rows('SELECT * FROM player_battle_statistics')),2)

    def test_capture_failure_blocks_only_affected_accounts_until_retry(self):
        owners,good=self.second_match()
        with patch.object(self.hub,'settlement_inputs',side_effect=KeyError('Injected report failure')):
            self.hub.quarantine(self.battle,RuntimeError('Injected match failure'))
        self.assertTrue(battle_settlement.blocked(self.case.path,'alice'))
        self.assertTrue(battle_settlement.blocked(self.case.path,'bob'))
        self.assertFalse(battle_settlement.blocked(self.case.path,'carol'))
        self.assertEqual(self.rows('SELECT * FROM battle_settlement_jobs'),[])
        self.assertIs(self.hub.battles[owners[0]],good)
        self.case.now=5;self.hub.tick()
        self.assertFalse(battle_settlement.blocked(self.case.path,'alice'))
        self.assertTrue(self.battle['finished'])

    def test_restart_recovers_captured_reports_once_after_reward_commit(self):
        from tio.battle_rewards import settle
        self.kill();match=self.battle['match_id']
        self.hub.prepare_settlements(self.battle,((self.owners[0],1,False),(self.owners[1],0,False)))
        # Simulate a process dying after reward commit, before deleting its job.
        payload=self.rows("SELECT payload FROM battle_settlement_jobs WHERE account='alice'")[0][0]
        result,kwargs=battle_settlement.unpack(payload)
        settle(self.case.path,'alice',match,result,**kwargs)
        before=self.rows("SELECT credits,gold FROM wallets WHERE account='alice'")
        self.assertEqual(set(battle_settlement.retry(self.case.path,force=True)),{(match,'alice'),(match,'bob')})
        self.assertEqual(self.rows("SELECT credits,gold FROM wallets WHERE account='alice'"),before)
        self.assertEqual(len(self.rows('SELECT * FROM player_battle_statistics')),2)
        self.assertEqual(self.rows('SELECT account,rating FROM soldier_ratings ORDER BY account'),[('alice',1),('bob',-1)])
        self.assertEqual(battle_settlement.retry(self.case.path,force=True),[])
        # A concurrent in-memory finisher can observe an already-recovered job.
        self.hub.settle(self.battle,self.owners[0],1)
        self.assertEqual(self.rows("SELECT credits,gold FROM wallets WHERE account='alice'"),before)

    def test_pending_payload_cannot_be_replaced_and_enqueue_is_atomic(self):
        match=self.battle['match_id'];report=self.hub.settlement_inputs(self.battle,self.owners[0])
        battle_settlement.enqueue(self.case.path,match,(('alice',1,report),))
        with self.assertRaises(ValueError):
            battle_settlement.enqueue(self.case.path,match,(('bob',0,{}),('alice',0,report)))
        self.assertEqual(self.rows('SELECT account FROM battle_settlement_jobs'),[('alice',)])

    def test_failed_job_does_not_starve_independent_job(self):
        battle_settlement.enqueue(self.case.path,'bad',(('unknown-account',0,{}),))
        battle_settlement.enqueue(self.case.path,'good',(('alice',0,{}),))
        self.assertEqual(battle_settlement.retry(self.case.path),[('good','alice')])
        self.assertEqual(self.rows('SELECT match_id,attempts,error_type FROM battle_settlement_jobs'),[('bad',1,'ValueError')])
        self.assertFalse(battle_settlement.blocked(self.case.path,'alice'))

    def test_shared_storage_failure_remains_fatal(self):
        error=sqlite3.DatabaseError('database disk image is malformed')
        with patch.object(self.hub,'tick_battle',side_effect=error):
            with self.assertRaises(sqlite3.DatabaseError):self.hub.tick()
        self.assertNotIn('faulted',self.battle)
        self.assertFalse(storage_failure(sqlite3.IntegrityError('individual constraint')))
        self.assertFalse(storage_failure(sqlite3.OperationalError('database is locked')))
        self.assertTrue(storage_failure(sqlite3.OperationalError('database or disk is full')))

    def test_busy_audit_write_defers_only_faulty_match_and_then_recovers(self):
        owners,good=self.second_match()
        with patch.object(battle_settlement,'record_failure',side_effect=sqlite3.OperationalError('database is locked')):
            self.hub.quarantine(self.battle,RuntimeError('Injected match failure'))
        self.assertTrue(self.battle['faulted']);self.assertFalse(self.battle['finished'])
        self.assertIs(self.hub.battles[owners[0]],good)
        self.case.now=5;self.hub.tick()
        self.assertTrue(self.battle['finished'])
        self.assertEqual(self.rows('SELECT account,resolved FROM battle_failure_audit ORDER BY account'),[('alice',1),('bob',1)])

    def test_private_final_report_remains_frozen_during_retry(self):
        from tio.protocol.pet_info import decode_pet_info
        arena=self.case.sessions[0].arena
        with patch('tio.battle_rewards.settle',side_effect=ValueError('Injected private settlement failure')):
            with self.assertRaises(ValueError):arena.settle_final(self.case.path,'alice','private-frozen',1,health={1:1})
        arena.settle_final(self.case.path,'alice','private-frozen',1,health={1:999})
        packet=self.rows("SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=1")[0][0]
        self.assertEqual(decode_pet_info(packet,human_equipment=True).fields['0x8c4ab1'],1)
        self.assertEqual(self.rows("SELECT result FROM battle_rewards WHERE match_id='private-frozen'"),[(1,)])
        self.assertEqual(self.rows('SELECT * FROM battle_settlement_jobs'),[])


class SessionFailureTests(unittest.TestCase):
    def tcp_case(self):
        case=tcp_fixtures.MultiAccountTests();case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_busy_recovery_does_not_stop_healthy_tcp_sessions(self):
        case=self.tcp_case()
        with patch.object(battle_settlement,'retry',side_effect=sqlite3.OperationalError('database is locked')):
            case.start();alice=case.handoff(case.begin('alice'));case.enter(alice,'Alice');case.ping(alice)
            bob=case.handoff(case.begin('bob'));case.enter(bob,'Bob');case.ping(bob)
            self.assertTrue(case.thread.is_alive());self.assertFalse(case.errors)

    def test_territory_sync_retries_after_external_writer_without_dropping_two_accounts(self):
        import threading
        from tio import territories

        case = self.tcp_case()
        case.start()
        alice = case.handoff(case.begin('alice'))
        case.enter(alice, 'Alice')
        bob = case.handoff(case.begin('bob'))
        case.enter(bob, 'Bob')

        store = case.server.multi.team_arena.assault_store
        sync = store.sync
        blocked = threading.Event()
        resumed = threading.Event()

        def observe_sync(*args, **kwargs):
            try:
                result = sync(*args, **kwargs)
            except sqlite3.OperationalError:
                blocked.set()
                raise
            if blocked.is_set():
                resumed.set()
            return result

        def short_connection(path, **kwargs):
            return sqlite3.connect(path, timeout=kwargs.get('timeout', .02))

        with patch.object(store, 'sync', side_effect=observe_sync), \
                patch.object(territories, 'connect', side_effect=short_connection):
            with closing(sqlite3.connect(case.config.database)) as writer:
                writer.execute('BEGIN IMMEDIATE')
                self.assertTrue(blocked.wait(4), 'The territory tick never encountered the writer')
                case.ping(alice)
                case.ping(bob)
                self.assertEqual(case.errors, [])
            self.assertTrue(resumed.wait(4), 'The territory tick did not retry')
            case.ping(alice)
            case.ping(bob)

    def test_startup_replays_pending_report_before_login(self):
        from tio.wallets import WalletStore
        case=self.tcp_case();WalletStore(case.config.database).ensure('alice')
        battle_settlement.enqueue(case.config.database,'pending-startup',(('alice',0,{}),))
        case.start();alice=case.handoff(case.begin('alice'));case.enter(alice,'Alice')
        case.ping(alice)
        with closing(sqlite3.connect(case.config.database)) as db:
            self.assertEqual(db.execute('SELECT account,result FROM battle_rewards').fetchall(),[('alice',0)])
            self.assertEqual(db.execute('SELECT * FROM battle_settlement_jobs').fetchall(),[])

    def test_unrecoverable_account_report_does_not_block_other_tcp_login(self):
        from tio.wallets import WalletStore
        case=self.tcp_case();WalletStore(case.config.database).ensure('alice')
        battle_settlement.enqueue(case.config.database,'bad-pending',(('alice',0,dict(rank_report={999:(0,False)})),))
        case.start();case.begin('alice',denied=True)
        bob=case.handoff(case.begin('bob'));case.enter(bob,'Bob');case.ping(bob)
        self.assertTrue(battle_settlement.blocked(case.config.database,'alice'))
        self.assertFalse(battle_settlement.blocked(case.config.database,'bob'))
        self.assertTrue(case.thread.is_alive());self.assertFalse(case.errors)

    def test_unexpected_worker_failure_does_not_disconnect_other_tcp_account(self):
        case=self.tcp_case();case.start()
        alice=case.handoff(case.begin('alice'));case.enter(alice,'Alice')
        bob=case.handoff(case.begin('bob'));case.enter(bob,'Bob')
        presence=case.server.multi.presence;original=presence.handle
        def handle(exchange,packet):
            if exchange.account=='alice' and packet==b'\x70':raise RuntimeError('Injected single session failure')
            return original(exchange,packet)
        with patch.object(presence,'handle',side_effect=handle):
            alice.send(b'\x70')
            with self.assertRaises((EOFError,ConnectionResetError)):alice.receive()
        case.ping(bob)
        self.assertTrue(case.thread.is_alive());self.assertFalse(case.errors)
        replacement=case.handoff(case.begin('alice'));case.enter(replacement,'Alice')
        case.ping(replacement);case.ping(bob)


if __name__=='__main__':unittest.main()
