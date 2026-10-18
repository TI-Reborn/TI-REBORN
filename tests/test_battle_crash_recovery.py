"""Real gameplay transactions and process exits at the commit boundaries."""
from contextlib import closing
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_shared_team_arena as shared_fixture
import test_shooting_range as range_fixture
import test_mining as mine_fixture
from server.team_arena import TeamArena
from server.battle_journal import BattleJournal,PrivateJournal
from tio import battle_checkpoints as checkpoints
from tio import battle_snapshot
from tio.db_transaction import transaction,connect
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.item_action import ItemAction,encode_item_action
from test_combat import item

ROOT=Path(__file__).resolve().parents[1]


def initialise_shared(case,path=None):
    if path is not None:
        with closing(sqlite3.connect(case.path)) as src,closing(sqlite3.connect(path)) as dst:src.backup(dst)
        case.path=Path(path)
        for session in case.sessions:session.database=case.path
    with closing(sqlite3.connect(case.path)) as db,db:
        db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',(encode_item_list(1,(item(200,10,3),)),'alice'))
    case.wall=1000.;case.hub.journal=BattleJournal(case.hub,case.path,wall=lambda:case.wall)
    for index in (0,1):case.send(index,b'\xba\3\1\1');case.send(index,b'\x2e')
    for index in (0,1):case.send(index,b'\x36')
    case.hub.tick()
    owners=tuple(case.hub.identities[s] for s in case.sessions[:2]);b=case.hub.battles[owners[0]]
    actor=b['field'].actor_ids(owners[0])[0]
    with case.hub.journal.unit(b):b['field']._actors[actor]=replace(b['field'].actor(actor),health=20)
    return owners,b,actor


class CrashRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.case=shared_fixture.SharedTeamTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.owners,self.battle,self.actor=initialise_shared(self.case)

    def restore(self,*,mono=None,wall=None):
        mono=self.case.now if mono is None else mono;wall=self.case.wall if wall is None else wall
        hub=TeamArena(clock=lambda:mono);hub.journal=BattleJournal(hub,self.case.path,wall=lambda:wall)
        hub.journal.recover();return hub

    def medical(self):
        self.case.hub.battle_action(self.owners[0],encode_item_action(ItemAction(self.actor,200,255)))

    def rows(self):
        with closing(sqlite3.connect(self.case.path)) as db:
            tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {t:tuple(db.execute('SELECT * FROM "'+t+'"').fetchall()) for t in tables}

    def test_medical_health_ap_and_inventory_restore_together(self):
        self.medical();hub=self.restore();b=hub.battles[self.owners[0]];a=b['field'].actor(self.actor)
        self.assertEqual((a.health,a.action_points),(50,12))
        self.assertEqual(decode_item_list(b['field'].combat.inventories[self.actor])[1][0].count,2)
        self.assertEqual(decode_item_list(OwnedPetStore(self.case.path).inventory('alice',1))[1][0].count,2)
        self.assertEqual(b['match_id'],self.battle['match_id']);self.assertEqual(b['ground'],self.battle['ground'])
        self.assertEqual(set(hub.account_owners),{'alice','bob'})

    def test_checkpoint_failure_rolls_back_gameplay_writes_memory_and_notifications(self):
        before=self.rows();queues={o:tuple(q) for o,q in self.case.hub.queues.items()}
        real=checkpoints.save
        def fail(*args,**kwargs):real(*args,**kwargs);raise RuntimeError('Injected after snapshot write')
        with patch('server.battle_journal.store.save',side_effect=fail),self.assertRaises(RuntimeError):self.medical()
        self.assertEqual(self.rows(),before)
        b=self.case.hub.battles[self.owners[0]]
        self.assertEqual(b['field'].actor(self.actor).health,20)
        self.assertEqual(decode_item_list(b['field'].combat.inventories[self.actor])[1][0].count,3)
        self.assertEqual({o:tuple(q) for o,q in self.case.hub.queues.items()},queues)

    def test_deadlines_do_not_restart_when_monotonic_clock_resets(self):
        original=self.battle['arena']._turns[self.battle['room'].room_id]
        hub=self.restore(mono=50,wall=1007)
        turn=hub.battles[self.owners[0]]['arena']._turns[self.battle['room'].room_id]
        self.assertEqual(turn[:2],original[:2]);self.assertEqual(turn[2]-50,original[2]-7)
        self.assertEqual(hub.offline[self.owners[0]]-50,173)

    def test_both_accounts_reload_same_shared_battle_without_resetting_ap(self):
        self.medical();hub=self.restore(mono=5,wall=1003)
        for s in self.case.sessions[:2]:self.assertTrue(hub.resume(s))
        self.assertIs(hub.battles[self.owners[0]],hub.battles[self.owners[1]])
        self.assertEqual(hub.battles[self.owners[0]]['field'].actor(self.actor).action_points,12)
        for s in self.case.sessions[:2]:hub.handle(s,b'\x36')
        self.assertFalse(hub.returning)

    def test_random_state_is_preserved_without_replaying_actions(self):
        with self.case.hub.journal.unit(self.battle):
            self.battle['field'].combat.rng=random.Random(1234)
            self.battle['field'].loot.rng=random.Random(4321)
            self.battle['field'].combat.rng.random()
        clone=self.restore().battles[self.owners[0]]
        self.assertEqual(clone['field'].combat.rng.getstate(),self.battle['field'].combat.rng.getstate())
        self.assertEqual(clone['field'].loot.rng.getstate(),self.battle['field'].loot.rng.getstate())

    def test_overdue_offline_accounts_settle_once_and_release_checkpoints(self):
        hub=self.restore(mono=0,wall=1181);hub.expire_reconnects()
        self.assertFalse(hub.battles);self.assertFalse(checkpoints.read(self.case.path))
        with closing(sqlite3.connect(self.case.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM battle_rewards').fetchone()[0],2)
        again=self.restore(mono=0,wall=1182);again.expire_reconnects()
        with closing(sqlite3.connect(self.case.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM battle_rewards').fetchone()[0],2)

    def test_corrupt_snapshot_blocks_only_its_accounts(self):
        for index in (2,3):self.case.send(index,b'\xba\3\1\1');self.case.send(index,b'\x2e')
        with closing(sqlite3.connect(self.case.path)) as db,db:
            db.execute('UPDATE battle_checkpoints SET payload=? WHERE match_id=?',('{"broken":true}',self.battle['match_id']))
        hub=self.restore()
        self.assertEqual(set(hub.account_owners),{'carol','dave'})
        self.assertTrue(checkpoints.blocked(self.case.path,'alice'));self.assertFalse(checkpoints.blocked(self.case.path,'carol'))

    def test_final_results_and_rewards_survive_restart_without_duplicate_payment(self):
        with self.case.hub.journal.unit(self.battle):
            field=self.battle['field'];side=field.side(self.owners[1])
            for victim in tuple(field._actors):
                if field.side(field.actor(victim).owner_id)==side:field._actors[victim]=replace(field.actor(victim),health=0)
        self.case.hub.tick();before=self.rows()
        hub=self.restore();self.assertEqual(set(hub.completed),set(self.owners))
        for s in self.case.sessions[:2]:hub.resume(s);hub.handle(s,b'\x36')
        with closing(sqlite3.connect(self.case.path)) as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM battle_rewards').fetchall()),before['battle_rewards'])
        for s in self.case.sessions[:2]:hub.handle(s,b'\x2a\1')
        self.assertFalse(checkpoints.read(self.case.path))

    def test_unknown_class_and_rules_version_are_quarantined(self):
        for change in ('class','version'):
            with self.subTest(change=change),closing(sqlite3.connect(self.case.path)) as db,db:
                data=json.loads(battle_snapshot.dumps(self.case.hub.journal.data(self.battle),clock=self.case.hub.clock,wall=lambda:1000))
                if change=='class':data['nodes'][0]['class']='os.system'
                else:data['version']=999
                payload=json.dumps(data);db.execute('UPDATE battle_checkpoints SET payload=?,checksum=?,status=? WHERE match_id=?',
                    (payload,hashlib.sha256(payload.encode()).hexdigest(),'active',self.battle['match_id']))
            hub=self.restore();self.assertFalse(hub.battles);self.assertTrue(checkpoints.blocked(self.case.path,'alice'))

    def test_account_cannot_bind_to_two_checkpoints(self):
        with transaction(self.case.path) as db,self.assertRaisesRegex(ValueError,'another durable'):
            checkpoints.save(db,'different',checkpoints.read(self.case.path)[0][1],{'alice':55})

    def test_pending_terminal_reports_take_precedence_over_active_checkpoint(self):
        from tio import battle_settlement
        self.case.hub.prepare_settlements(self.battle,tuple((o,0,True) for o in self.owners))
        battle_settlement.apply(self.case.path,self.battle['match_id'],'alice')
        hub=self.restore();battle=hub.battles[self.owners[0]]
        self.assertEqual(battle['faulted'],'RecoveredSettlement')
        self.assertIn(self.owners[0],battle['settled'])
        hub.tick();self.assertFalse(hub.battles);self.assertFalse(checkpoints.read(self.case.path))
        with closing(sqlite3.connect(self.case.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM battle_rewards').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT count(*) FROM battle_settlement_jobs').fetchone()[0],0)


class PrivateCrashRecoveryTests(unittest.TestCase):
    def test_range_admission_snapshot_failure_refunds_and_does_not_create_scene(self):
        c=range_fixture.RangeTests();c.setUp();self.addCleanup(c.doCleanups)
        s=SimpleNamespace(probe_character_id=42,probe_character_name=b'Alice')
        checkpoints.initialise(c.path)
        PrivateJournal(c.arena,c.path,'alice',session=s,wall=lambda:c.now[0])
        c.service.handle('alice',42,b'Alice',range_fixture.CREATE_REQUEST)
        before=c.service.admission.assets('alice')
        with patch('server.battle_journal.store.save',side_effect=RuntimeError('Injected')),self.assertRaises(RuntimeError):
            c.service.handle('alice',42,b'Alice',b'\x2e\1')
        self.assertEqual(c.service.admission.assets('alice'),before)
        with closing(sqlite3.connect(c.path)) as db:self.assertEqual(db.execute('SELECT count(*) FROM range_visits').fetchone()[0],0)
        self.assertFalse(c.arena._fields);self.assertFalse(checkpoints.read(c.path))

    def test_range_restarts_with_paid_visit_and_live_targets(self):
        c=range_fixture.RangeTests();c.setUp();self.addCleanup(c.doCleanups)
        s=SimpleNamespace(probe_character_id=42,probe_character_name=b'Alice')
        PrivateJournal(c.arena,c.path,'alice',session=s,wall=lambda:c.now[0]);c.start(payment=1)
        balance=c.service.admission.assets('alice').credits
        c.now[0]+=5;hub=TeamArena(clock=lambda:c.now[0]);hub.journal=BattleJournal(hub,c.path,wall=lambda:c.now[0]);hub.journal.recover()
        restored=hub.private['alice'][0].arena._fields[c.room.room_id]
        self.assertEqual(c.service.admission.assets('alice').credits,balance)
        self.assertEqual(restored.practice.targets,c.field.practice.targets)
        self.assertIs(restored.practice.field,restored);self.assertFalse(restored.practice.complete())

    def test_mining_layout_deposits_temporary_items_and_monsters_restore(self):
        c=mine_fixture.MiningTests();c.setUp();self.addCleanup(c.doCleanups)
        from tio.arena_service import ArenaService
        arena=ArenaService(clock=lambda:0);s=SimpleNamespace(probe_character_id=42,probe_character_name=b'Alice')
        PrivateJournal(arena,c.path,'probe_user',session=s,wall=lambda:1000)
        room,_=arena.start_survival(42,b'Alice',c.scene)
        hub=TeamArena(clock=lambda:0);hub.journal=BattleJournal(hub,c.path,wall=lambda:1000);hub.journal.recover()
        f=hub.private['probe_user'][0].arena._fields[room.room_id]
        self.assertEqual(f.mining.layout,c.field.mining.layout);self.assertEqual(f.mining.deposits,c.field.mining.deposits)
        self.assertEqual(f.combat.temporary_items,c.field.combat.temporary_items)
        self.assertEqual(f.combat.catalog.weapons[353],c.field.combat.catalog.weapons[353])
        self.assertEqual(f.combat.npc_defense,c.field.combat.npc_defense)


class ProcessExitTests(unittest.TestCase):
    def test_two_tcp_accounts_resume_after_forced_server_process_exit(self):
        import socket,time
        import test_multi_account as tcp_fixture
        from tio.protocol.arena import ArenaCreateRequest,encode_create_request
        from tio.protocol.battle_turn import encode_end_turn
        c=tcp_fixture.MultiAccountTests();c.setUp();self.addCleanup(c.doCleanups)
        processes=[]
        def stop_processes():
            for p in processes:
                if p.poll() is None:p.kill()
                p.wait(timeout=10)
            for connection in c.clients:connection.close()
        self.addCleanup(stop_processes)
        code="""import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from server.config import ServerConfig
from server.runtime import Server
Server(ServerConfig('127.0.0.1','127.0.0.1',int(sys.argv[3]),Path(sys.argv[2]),'ERROR',True,int(sys.argv[4]))).serve()
"""
        def start():
            p=subprocess.Popen([sys.executable,'-c',code,str(ROOT),str(c.config.data_directory),str(c.config.game_port),str(c.config.session_port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            processes.append(p);deadline=time.monotonic()+10
            while True:
                self.assertIsNone(p.poll(),'Isolated server exited')
                try:
                    with socket.create_connection(('127.0.0.1',c.config.game_port),timeout=.1):break
                except OSError:
                    if time.monotonic()>deadline:self.fail('Server startup timeout')
                    time.sleep(.02)
            return p
        p=start();peers=[]
        for account,name in (('alice','Alice'),('bob','Bob')):
            peer=c.handoff(c.begin(account));c.enter(peer,name);peers.append(peer)
        request=encode_create_request(ArenaCreateRequest(1,0,4,2,40,1,1,0,0))
        for peer in peers:peer.send(request);peer.until(b'\x25');peer.send(b'\x2e')
        for peer in peers:peer.until(b'\x41');peer.send(b'\x36')
        peers[0].until(b'\x38')
        row=checkpoints.read(c.config.database)[0]
        state,_=battle_snapshot.loads(row[1],clock=time.monotonic,wall=time.time)
        owner=row[4]['alice'];field=state['battle']['field'];actor=field.actor_ids(owner)[0]
        peers[0].send(encode_end_turn(actor));peers[1].until(b'\x38')
        committed=checkpoints.read(c.config.database)[0]
        saved,_=battle_snapshot.loads(committed[1],clock=time.monotonic,wall=time.time)
        p.kill();p.wait(timeout=10)
        for peer in peers:peer.sock.close()
        self.assertEqual(checkpoints.read(c.config.database)[0][1],committed[1])
        start()
        for account,name in (('alice','Alice'),('bob','Bob')):
            peer=c.handoff(c.begin(account));c.character_screen(peer)
            peer.send(bytes.fromhex('1701000000'));self.assertTrue(peer.receive().startswith(b'\x18'))
            peer.send(b'\x19');peer.until(b'\x41');peer.send(b'\x36');c.ping(peer)
        restored=checkpoints.read(c.config.database)[0]
        state,_=battle_snapshot.loads(restored[1],clock=time.monotonic,wall=time.time)
        self.assertEqual(restored[0],committed[0]);self.assertEqual(restored[4],committed[4])
        self.assertEqual(state['battle']['field']._actors,saved['battle']['field']._actors)
        self.assertEqual(state['battle']['ground'],saved['battle']['ground'])
        with closing(sqlite3.connect(c.config.database)) as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='battle_rewards'").fetchone()
            self.assertEqual(db.execute('SELECT count(*) FROM battle_rewards').fetchone()[0] if exists else 0,0)

    def test_real_process_exit_before_and_after_commit(self):
        code='''import os,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[4]]
from test_battle_crash_recovery import *
shared_fixture.ROOT=Path(sys.argv[1])
case=shared_fixture.SharedTeamTests();case.setUp()
owners,b,actor=initialise_shared(case,sys.argv[2])
phase=sys.argv[3]
if phase=='before':
 real=checkpoints.save
 def crash(*a,**k):real(*a,**k);os._exit(71)
 checkpoints.save=crash
else:
 from contextlib import contextmanager
 from tio.db_transaction import current
 real=case.hub.journal.unit
 @contextmanager
 def crash(battle):
  with real(battle):yield
  if current() is None:os._exit(72)
 case.hub.journal.unit=crash
case.hub.battle_action(owners[0],encode_item_action(ItemAction(actor,200,255)))
raise AssertionError('Crash was not reached')'''
        for phase,hp,count in (('before',20,3),('after',50,2)):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'battle.db'
                p=subprocess.run([sys.executable,'-c',code,str(ROOT),str(path),phase,str(Path(__file__).parent)],capture_output=True,text=True,timeout=30)
                self.assertEqual(p.returncode,71 if phase=='before' else 72,p.stderr)
                hub=TeamArena(clock=lambda:0);hub.journal=BattleJournal(hub,path,wall=lambda:1000)
                self.assertEqual(len(hub.journal.recover()),1)
                owner=hub.account_owners['alice'];field=hub.battles[owner]['field'];actor=field.actor_ids(owner)[0]
                self.assertEqual(field.actor(actor).health,hp)
                self.assertEqual(decode_item_list(field.combat.inventories[actor])[1][0].count,count)
                self.assertEqual(decode_item_list(OwnedPetStore(path).inventory('alice',1))[1][0].count,count)
                self.assertEqual(set(hub.account_owners),{'alice','bob'})


if __name__=='__main__':unittest.main()
