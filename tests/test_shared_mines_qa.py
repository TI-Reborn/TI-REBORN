"""Independent, local-only safeguards for shared-mines acceptance tooling."""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from contextlib import redirect_stdout
import io,json,sys,time,pathlib
from unittest.mock import patch

from tools.inspect_shared_mines import REMOTE
from tools.deploy_shared_mines import remote_program, candidate_entries, ALLOWED
from tools.verify_hosted_shared_mines import (MINE_SNAPSHOT,validate_shared_snapshot,
    validate_reconnect,validate_lift_lock,validate_receipt,MinesFixture,MinesNetwork,
    PROVISION_MINES,LEVEL4_FIXTURE,OWNED_STATUS,CLAIM_OPERATION,GATE_CHECK,SOURCES)
from tools.verify_game_tls_hosted import tls_context
from tools.verify_hosted_arena_surroundings import OWNERSHIP
from tools.verify_hosted_economy_tls import ECONOMY_SNAPSHOT


def mine_fixture():
    names=['qs12345678'+c for c in 'abc']
    actors=[dict(id=100+i,owner=10+i,account=n,storage_id=1,team=(1 if i==1 else 0),
                 x=i,y=0,hp=115,max_hp=115,ap=15,inventory=[]) for i,n in enumerate(names)]
    actors.extend(dict(id=1000+i,owner=20,account=None,storage_id=None,team=2,
                       x=i,y=20,hp=150,max_hp=150,ap=20,inventory=[]) for i in range(10))
    return names,dict(match='owned-match',kind='mine',mode=7,town=13,width=60,height=60,bots=1,
        ground_sha256='original-ground',participants={10:names[0],11:names[1],12:names[2]},
        foreign_checkpoint_rows=0,actors=actors,claim={'location':13,'owner_clan':1,'tax_percent':10,'revision':1},
        mining=dict(shared=True,roles={10:1,11:2,12:3},round=2,last_tick=2,lift_blocked_until=7,
                    owner_deadlines={10:7,11:0,12:7},raider_entries=[11],exited=[],total=1000,
                    deposits=[dict(id=1,initial=500),dict(id=2,initial=500)]))


class SharedMinesBaselineTests(unittest.TestCase):
    def test_counts_without_private_row_values_and_no_database_write(self):
        namespace = {'__name__':'local_fixture'}
        exec(REMOTE, namespace)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'fixture.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE accounts(username TEXT,password TEXT)')
                db.execute("INSERT INTO accounts VALUES ('private-name','private-secret')")
                db.execute('CREATE TABLE battle_checkpoints(id TEXT)')
                db.execute('CREATE TABLE battle_settlement_jobs(id TEXT)')
            before = path.read_bytes()
            result = namespace['database_counts'](path)
            self.assertEqual(result['tables']['accounts'], {'rows':1})
            self.assertEqual(result['unfinished_battle_rows'], {'battle_checkpoints':0,'battle_settlement_jobs':0})
            self.assertNotIn('private-', repr(result))
            self.assertEqual(path.read_bytes(), before)

    def test_missing_database_is_not_created(self):
        namespace = {'__name__':'local_fixture'}
        exec(REMOTE, namespace)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'absent.sqlite3'
            with self.assertRaises(sqlite3.OperationalError):
                namespace['database_counts'](path)
            self.assertFalse(path.exists())

    def test_deployment_adaptor_keeps_idle_backups_and_no_database_restore(self):
        code=remote_program()
        self.assertIn("sport = :29512 or sport = :29513",code)
        self.assertIn("source.backup(destination)",code)
        self.assertIn("idle_rows()",code)
        self.assertIn("fingerprint(backup/'reservation.sqlite3')!=before",code)
        self.assertIn("database_restored=False",code)
        self.assertIn("rollback_deferred=True",code)
        self.assertIn("'tio/mine_claims.py'",code)
        self.assertNotIn("'tio/wallets.py'",repr(ALLOWED))

    def test_unexpected_deployment_path_refused_before_read(self):
        for names in (['config/server.toml'],['../reservation.sqlite3'],['tio/wallets.py'],[]):
            with self.assertRaises(ValueError):candidate_entries(names,{})


class SharedMinesEvidenceTests(unittest.TestCase):
    def test_poll_batch_guard_once_and_only_read_poll_packets(self):
        from tools.verify_hosted_shared_mines import MinesNetwork
        from tools.verify_game_tls_hosted import TlsNetworkQA
        from types import SimpleNamespace
        seen=[]
        fixture=SimpleNamespace(guard_gate=lambda:seen.append('gate'),
                                guard_connections=lambda n:seen.append(('connections',n)))
        network=object.__new__(MinesNetwork);network.fixture=fixture;network.peers={0:None,1:None,2:None}
        with patch.object(TlsNetworkQA,'command',side_effect=lambda i,p:seen.append((i,p))):
            network.poll_batch()
        self.assertEqual(seen,['gate',('connections',3),(0,b'\x70'),(1,b'\x70'),(2,b'\x70')])

    def test_public_diagnosis_refuses_remote_and_private_exception_text(self):
        from tools.verify_hosted_shared_mines import safe_assertion_diagnostic
        self.assertEqual(safe_assertion_diagnostic(RuntimeError('No legal AP movement prefix')), {})
        self.assertEqual(safe_assertion_diagnostic(AssertionError('secret or remote input')), {})
        self.assertEqual(safe_assertion_diagnostic(AssertionError('Bounded route exceeded'))['assertion'],
                         'Bounded route exceeded')

    def test_at_goal_does_not_wait_for_turn_or_advance_lift_round(self):
        from tools.verify_hosted_shared_mines import MineDriver
        from types import SimpleNamespace
        names,state=mine_fixture()
        driver=MineDriver(SimpleNamespace(),SimpleNamespace(names=names))
        driver.state=lambda:state
        driver.owner_turn=lambda *a,**k:self.fail('Already-at-goal route must not wait for AP/turn')
        plan=SimpleNamespace(path=())
        with patch('tools.shared_mines_route.plan_route',return_value=plan):
            self.assertIs(driver.to(0,[(0,0)]),state)
        self.assertEqual(state['mining']['round'],2)

    def test_resume_bounds_include_previous_completed_zero_mission(self):
        from tools.verify_hosted_shared_mines import battle_owned
        from types import SimpleNamespace
        fixture=SimpleNamespace(status=lambda:{'receipts':[dict(match_id='old',gross=0)]})
        ordinals=[]
        def refusal(fixture,args,attempt):
            ordinals.append(attempt['ordinal']);attempt.update(retry_safe=True,cleanup={'all_owned_sockets_closed':True})
        with patch('tools.verify_hosted_shared_mines.battle_attempt',side_effect=refusal):
            with self.assertRaisesRegex(AssertionError,'Three ordinary missions'):
                battle_owned(fixture,SimpleNamespace(),{})
        self.assertEqual(ordinals,[2,3])

    def test_prior_zero_or_other_extractor_receipt_cannot_complete_new_lift_run(self):
        from tools.verify_hosted_shared_mines import current_extraction_receipts
        status={'receipts':[dict(match_id='prior',extractor='miner',gross=0),
                            dict(match_id='current',extractor='defender',gross=0)]}
        self.assertEqual(current_extraction_receipts(status,'current','miner'),[])
        actual=dict(match_id='current',extractor='miner',gross=101)
        status['receipts'].append(actual)
        self.assertEqual(current_extraction_receipts(status,'current','miner'),[actual])

    def test_remote_audit_compiles_and_uses_readonly_database(self):
        compile(MINE_SNAPSHOT,'owned_snapshot','exec')
        self.assertIn('?mode=ro',MINE_SNAPSHOT)
        self.assertNotIn('UPDATE ',MINE_SNAPSHOT)
        self.assertNotIn('INSERT ',MINE_SNAPSHOT)
        self.assertNotIn('DELETE ',MINE_SNAPSHOT)

    def test_real_three_roles_and_starter_storage_ids(self):
        names,state=mine_fixture()
        result=validate_shared_snapshot(state,names)
        self.assertEqual((result['humans'],result['mutants']),(3,10))
        self.assertEqual(result['actor_ids'],[100,101,102])

    def test_private_demonstration_or_missing_role_cannot_pass(self):
        names,state=mine_fixture()
        state['mining']['shared']=False
        with self.assertRaises(AssertionError):validate_shared_snapshot(state,names)
        names,state=mine_fixture();state['mining']['roles'][12]=1
        with self.assertRaises(AssertionError):validate_shared_snapshot(state,names)

    def test_foreign_player_or_actor_collision_refused(self):
        names,state=mine_fixture();state['participants'][12]='ordinary-player'
        with self.assertRaises(AssertionError):validate_shared_snapshot(state,names)
        names,state=mine_fixture();state['actors'][1]['id']=100
        with self.assertRaises(AssertionError):validate_shared_snapshot(state,names)

    def test_reconnect_allows_clock_ap_but_preserves_owner_hp_inventory(self):
        names,before=mine_fixture();after=deepcopy(before)
        after['mining']['round']+=1;after['actors'][0]['ap']=14
        self.assertTrue(validate_reconnect(before,after,names)['same_actor_ids'])
        after['actors'][0]['hp']=116
        with self.assertRaises(AssertionError):validate_reconnect(before,after,names)

    def test_reconnect_cannot_refresh_lift_or_replace_map(self):
        names,before=mine_fixture();after=deepcopy(before)
        after['mining']['lift_blocked_until']+=5
        with self.assertRaises(AssertionError):validate_reconnect(before,after,names)
        after=deepcopy(before);after['ground_sha256']='replacement'
        with self.assertRaises(AssertionError):validate_reconnect(before,after,names)

    def test_five_full_rounds_not_five_actor_actions(self):
        _,entry=mine_fixture();locked=deepcopy(entry);unlocked=deepcopy(entry)
        locked['mining']['round']=6;unlocked['mining']['round']=7
        self.assertEqual(validate_lift_lock(entry,locked,unlocked)['full_rounds'],5)
        unlocked['mining']['round']=6
        with self.assertRaises(AssertionError):validate_lift_lock(entry,locked,unlocked)

    def test_early_extraction_or_refresh_cannot_pass(self):
        _,entry=mine_fixture();locked=deepcopy(entry);unlocked=deepcopy(entry)
        unlocked['mining']['round']=7;locked['mining']['exited']=[10]
        with self.assertRaises(AssertionError):validate_lift_lock(entry,locked,unlocked)
        locked=deepcopy(entry);unlocked['mining']['lift_blocked_until']=12
        with self.assertRaises(AssertionError):validate_lift_lock(entry,locked,unlocked)

    def test_odd_crystal_amount_conserved_in_persisted_balances(self):
        receipt=dict(extractor='m',gross=101,tax=10,payouts={'m':50,'d':41})
        before={'m':0,'d':0,'r':0,'clan':0};after={'m':50,'d':41,'r':0,'clan':10}
        self.assertTrue(validate_receipt(receipt,before,after,miner='m',defender='d',raider='r')['conserved'])
        after['d']=40
        with self.assertRaises(AssertionError):validate_receipt(receipt,before,after,miner='m',defender='d',raider='r')


class SharedMinesProvisionGuards(unittest.TestCase):
    def test_exact_three_refused_before_files_or_remote_mutations(self):
        with patch.object(MinesFixture,'prepare_private_directory') as private:
            for count in (0,1,2,4,8):
                with self.assertRaises(AssertionError):MinesFixture.prepare_owned('invalid',count)
            private.assert_not_called()

    def test_gate_account_mismatch_refused_before_remote_provisioning(self):
        fixture=MinesFixture('invalid','qs12345678',['qs12345678'+c for c in 'abc'],['abcdefABCDEF1234']*3,'',
                             credential_path='qs12345678.pending.json')
        with patch.object(fixture,'remote') as remote:
            with self.assertRaises(AssertionError):fixture.provision(dict(accounts=['foreign']))
            remote.assert_not_called()

    def test_private_pending_written_before_remote_creation(self):
        import tools.verify_hosted_shared_mines as module
        events=[]
        with tempfile.TemporaryDirectory() as folder,patch.object(module,'PRIVATE',Path(folder)):
            with patch.object(MinesFixture,'prepare_private_directory',side_effect=lambda:events.append('acl')):
                fixture=MinesFixture.prepare_owned('invalid')
            self.assertTrue(all(12<=len(p)<=16 and p.isalnum() and p.isascii() for p in fixture.passwords))
            self.assertEqual(fixture.names,[fixture.prefix+c for c in 'abc'])
            self.assertTrue(Path(fixture.credential_path).exists())
            self.assertGreaterEqual(len(events),1)

    def test_remote_mutation_snippets_compile_and_pin_operator_proof(self):
        for code in (PROVISION_MINES,LEVEL4_FIXTURE,OWNED_STATUS,CLAIM_OPERATION):compile(code,'local-review','exec')
        self.assertIn("helper['helper_sha256']",GATE_CHECK.replace("gate['helper_sha256']","helper['helper_sha256']"))
        self.assertIn('verify_gate',PROVISION_MINES)
        self.assertIn('claim_for_qa',CLAIM_OPERATION)
        self.assertIn("len(pairs)==3",PROVISION_MINES)
        self.assertIn('source_hashes',PROVISION_MINES)
        self.assertIn('create(name,password)',PROVISION_MINES)
        self.assertNotIn('character=name',PROVISION_MINES)
        self.assertIn("'0x8c4a07':115",LEVEL4_FIXTURE)
        self.assertNotIn('UPDATE wallets',LEVEL4_FIXTURE)
        self.assertNotIn('UPDATE character_locations',LEVEL4_FIXTURE)
        for name in ('server/battle_events.py','tio/arena_service.py','tio/battle_rewards.py'):
            self.assertIn(name,SOURCES)


class SharedMinesThreeTlsClients(unittest.TestCase):
    def test_three_normal_accounts_tls_onboarding_and_only_own_level4_fixture(self):
        # Real local TLS backend. Only the SSH path/ownership/gate adapters are
        # replaced; all three protocols/certificates/onboarding are genuine.
        from test_multi_account import MultiAccountTests
        from test_game_tls import free_ports,FIXTURES
        from server.config import TLSConfig
        case=MultiAccountTests();case.setUp();self.addCleanup(case.doCleanups)
        login,game=free_ports(2)
        case.config=replace(case.config,tls=TLSConfig(True,login,game,FIXTURES/'valid-chain.pem',FIXTURES/'valid-key.pem'))
        names=['qs12345678'+c for c in 'abc'];password='LocalFixture1234'
        for n in names:case.accounts.create(n,password)
        folder=Path(case.temp.name)/'owned-audit';folder.mkdir()
        class Local(MinesFixture):
            def guard_gate(self):return dict(local_only=True)
            def guard_connections(self,expected):
                # Existing production ss guard is tested separately; real
                # local active_accounts may release asynchronously on close.
                deadline=time.monotonic()+3
                while len(case.server.multi.active_accounts)!=expected:
                    if time.monotonic()>deadline:raise AssertionError('Local owned TLS session count differs')
                    time.sleep(.02)
                return dict(owned_sessions=expected)
            def remote(self,code,payload):
                self_outer.assertIn(code,(ECONOMY_SNAPSHOT,LEVEL4_FIXTURE,OWNED_STATUS,MINE_SNAPSHOT))
                source=code.removeprefix(OWNERSHIP).replace(GATE_CHECK,'')
                source=source.replace('/var/lib/tio-server/reservation.sqlite3',case.config.database.as_posix())
                if code==LEVEL4_FIXTURE:
                    source=source.replace("assert not subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).strip()",'assert not case.server.multi.active_accounts')
                out=io.StringIO()
                namespace=dict(names=names,data=payload,folder=folder,sqlite3=sqlite3,json=json,pathlib=pathlib,case=case)
                try:
                    with redirect_stdout(out):exec(compile(source,'local-owned-qa','exec'),namespace)
                finally:
                    for value in namespace.values():
                        if isinstance(value,sqlite3.Connection):value.close()
                return json.loads(out.getvalue())
        self_outer=self
        fixture=Local('127.0.0.1','qs12345678',names,[password]*3,'local-only')
        case.start()
        from tools.verify_hosted_shared_mines import preflight_forwards
        forwarding=dict(host='127.0.0.1',login_port=login,session_port=game,remote_login_port=29512,remote_session_port=29513)
        preflight=preflight_forwards(dict(forwarding=forwarding),hostname='localhost',ca_file=FIXTURES/'ca.pem')
        self.assertEqual(len(preflight),2)
        self.assertTrue(all(p['certificate_and_bootstrap_verified'] for p in preflight))
        net=MinesNetwork(fixture,'127.0.0.1','localhost',login,game,tls_context(cafile=FIXTURES/'ca.pem'),local_session_port=game)
        try:
            for i in range(3):net.attach(i,fresh=True)
            before=fixture.snapshot_economy()['states']
            self.assertEqual([s['wallet'] for s in before],[[3000,0]]*3)
            self.assertEqual([s['pets'][0]['level'] for s in before],[1]*3)
            self.assertEqual(len(net.audit()),6)
            self.assertTrue(all(c['tls_version'] in ('TLSv1.2','TLSv1.3') for c in net.audit()))
        finally:net.close();net.peers.clear()
        fixture.guard_connections(0)
        self.assertEqual(fixture.apply_level4()['xp'],7355)
        after=fixture.snapshot_economy()['states']
        for old,new in zip(before,after):
            self.assertEqual(new['wallet'],old['wallet'])
            self.assertEqual(new['pets'][0]['items'],old['pets'][0]['items'])
            self.assertEqual((new['pets'][0]['level'],new['pets'][0]['xp'],new['pets'][0]['hp']), (4,7355,115))
        with sqlite3.connect(case.config.database) as db:
            self.assertEqual(db.execute("SELECT credits,gold FROM wallets WHERE account='alice'").fetchone(),(10000,10000))
        with self.assertRaises(AssertionError):fixture.apply_level4()
        # Supplies, clan, actual timed map travel and shared mine admission are
        # ordinary C2S actions. Only local claim setup bypasses operator ingress.
        from tools.verify_hosted_shared_mines import encode_shop_purchase,ShopPurchase,encode_item_action,ItemAction
        from tio.mine_claims import MineClaimsStore
        import struct
        net=MinesNetwork(fixture,'127.0.0.1','localhost',login,game,tls_context(cafile=FIXTURES/'ca.pem'),local_session_port=game)
        try:
            for i in range(3):net.attach(i)
            state=fixture.snapshot_economy()['states']
            for i in range(3):
                net.command(i,encode_shop_purchase(ShopPurchase(1,0,3,1)))
                net.command(i,encode_item_action(ItemAction(1,state[i]['pets'][0]['items'][0]['id'],4)))
                net.command(i,b'\x50\3')
            net.command(0,b'\x52'+fixture.prefix.encode()+b'\0')
            net.command(0,b'\x5b'+names[2].encode()+b'\0');net.command(2,b'\x5d\1')
            for i in range(3):net.command(i,b'\x1b'+struct.pack('<ii',-170,-274))
            end=time.monotonic()+20
            while time.monotonic()<end:
                for i in range(3):net.command(i,b'\x70')
                status=fixture.status()
                if all(r['town']==13 for r in status['locations']):break
                time.sleep(.1)
            self.assertTrue(all(r['town']==13 for r in status['locations']))
            self.assertEqual({m['account'] for m in status['members']},{names[0],names[2]})
        finally:net.close();net.peers.clear()
        fixture.guard_connections(0)
        claim=MineClaimsStore(case.config.database).admin_set_claim(13,status['clan'],tax_percent=10,
            expected_revision=0,actor='local-only',reason='real3TLS fixture')
        net=MinesNetwork(fixture,'127.0.0.1','localhost',login,game,tls_context(cafile=FIXTURES/'ca.pem'),local_session_port=game)
        try:
            for i in range(3):net.attach(i)
            for i,role in ((0,1),(2,3),(1,2)):net.command(i,bytes((0xb0,0x14,role)))
            shared=fixture.snapshot_mine()
            self.assertEqual(validate_shared_snapshot(shared,names)['humans'],3)
            self.assertEqual(shared['claim'],claim)
            self.assertEqual(shared['mining']['lift_blocked_until'],5)
            grounds=[next(p for p in net.received[i] if p[0]==0x35) for i in range(3)]
            self.assertEqual(grounds,[grounds[0]]*3)
            self.assertTrue(all(b'\xb2\x0a\1' in net.received[i] for i in range(3)))
            self.assertGreaterEqual(len(shared['crates']),1)
            for i in range(3):net.command(i,b'\x36')
            before=fixture.snapshot_mine()
            net.drop(2);fixture.guard_connections(2);net.attach(2);net.command(2,b'\x36')
            after=fixture.snapshot_mine()
            self.assertTrue(validate_reconnect(before,after,names)['same_actor_ids'])
        finally:net.close();net.peers.clear()

    def test_raider_untaxed_and_foreign_receiver_rejected(self):
        receipt=dict(extractor='r',gross=101,tax=0,payouts={'r':101})
        before={'m':0,'d':0,'r':0,'clan':0};after={'m':0,'d':0,'r':101,'clan':0}
        self.assertTrue(validate_receipt(receipt,before,after,miner='m',defender='d',raider='r')['conserved'])
        receipt['payouts']['ordinary-player']=1
        with self.assertRaises(AssertionError):validate_receipt(receipt,before,after,miner='m',defender='d',raider='r')


if __name__=='__main__':unittest.main()
