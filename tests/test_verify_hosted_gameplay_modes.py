"""QA tool checks and a real local four-account TLS scenario; no VPS access."""
from contextlib import closing, redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools import verify_hosted_gameplay_modes as qa
import test_multi_account as fixture
from test_game_tls import FIXTURES, free_ports
from server.config import TLSConfig
from tio.protocol.wagers import WagerRoomRecord,encode_room_list
from tio.protocol.arena import ArenaCreateRequest


class ToolChecks(unittest.TestCase):
    def test_foreign_preservation_allows_global_receipts_and_new_empty_tables(self):
        before=dict(foreign={'wallets':dict(rows=2,sha256='before')})
        after=dict(foreign={**before['foreign'],'new_account_receipts':dict(rows=0,sha256='empty')},integrity='ok',wagers=[dict(match='new')])
        self.assertEqual(qa.preserve(before,after),{'wallets':2})
        after['foreign']['wallets']=dict(rows=2,sha256='changed')
        with self.assertRaises(AssertionError):qa.preserve(before,after)

    def test_progression_covers_xp_skills_rank_and_rating(self):
        initial=dict(states=[dict(account='qa',pets=[dict(id=1,progression={'xp':0,'skill':100,'rank':1})],ranks={'ranked_players':[[25,8]]},wallet=[3000,0])])
        changed=json.loads(json.dumps(initial));changed['states'][0]['wallet'][0]=3100
        self.assertEqual(qa.progression(initial),qa.progression(changed))
        changed['states'][0]['pets'][0]['progression']['skill']=101
        self.assertNotEqual(qa.progression(initial),qa.progression(changed))

    def test_fixture_cannot_duplicate_accounts_or_cross_hosts(self):
        first=SimpleNamespace(names=['qsa','qsb'],passwords=['private1','private2'],backup='owned',host='local',key='key')
        second=SimpleNamespace(names=['qsc','qsd'],passwords=['private3','private4'],backup='owned',host='local',key='key')
        self.assertEqual(len(qa.FourFixture([first,second]).names),4)
        second.names=['qsa','qsc']
        with self.assertRaises(AssertionError):qa.FourFixture([first,second])
        second.names=['qsc','qsd'];second.host='elsewhere'
        with self.assertRaises(AssertionError):qa.FourFixture([first,second])

    def test_current_deployment_proof_and_bounded_paths(self):
        required=('tio/wagers.py','server/wager_arena.py','server/team_arena.py','tio/team_scene.py','tio/battle_rewards.py','tio/matchmaking.py')
        values={name:hashlib.sha256((qa.ROOT/name).read_bytes()).hexdigest() for name in required}
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'proof.json';path.write_text(json.dumps(dict(source_parity=True,source_sha256=values)))
            self.assertEqual(qa.deployment_hashes(path),values)
            values['tio/../server/accounts.py']='0'*64;path.write_text(json.dumps(dict(source_parity=True,source_sha256=values)))
            with self.assertRaises(AssertionError):qa.deployment_hashes(path)

    def test_failed_report_never_echoes_credentials_or_remote_error(self):
        with tempfile.TemporaryDirectory() as root:
            output=Path(root)/'report.json';printed=io.StringIO()
            with patch.object(qa,'load_fixtures',side_effect=RuntimeError('private-password-should-not-leak')),redirect_stdout(printed):
                self.assertEqual(qa.main(['--fixture','private.json','--deployment','proof.json','--output',str(output)]),1)
            combined=printed.getvalue()+output.read_text()
            self.assertNotIn('private-password-should-not-leak',combined)
            self.assertEqual(json.loads(output.read_text())['error_type'],'RuntimeError')

    def test_snapshot_is_read_only_and_compiles(self):
        compile(qa.SNAPSHOT,'owned-read-only-snapshot','exec')
        self.assertNotIn('BEGIN IMMEDIATE',qa.SNAPSHOT)
        self.assertNotIn('UPDATE ',qa.SNAPSHOT)
        self.assertNotIn('INSERT ',qa.SNAPSHOT)
        self.assertNotIn('DELETE ',qa.SNAPSHOT)
        self.assertIn('mode=ro',qa.SNAPSHOT)

    def test_native_list_wait_ignores_stale_and_unrelated_rows(self):
        old=WagerRoomRecord(10,b'qaowner',1,0,2,1,0,1,2,0,0,100)
        wanted=WagerRoomRecord(11,b'qaowner',1,1,4,1,0,1,2,0,0,100)
        other=WagerRoomRecord(12,b'another',1,1,4,1,0,1,2,0,0,100)
        pages=iter([[encode_room_list(())],[encode_room_list((old,))],[encode_room_list((old,other,wanted))]])
        net=SimpleNamespace(command=lambda index,packet:next(pages))
        with patch.object(qa.time,'sleep'):
            room,seen=qa.wait_wager_room(net,3,b'qaowner',ArenaCreateRequest(1,2,4,2,40,1,1,0,100),{10})
        self.assertEqual(room.identity,11)
        self.assertEqual(seen,[dict(rows=0,matching=0),dict(rows=1,matching=0),dict(rows=3,matching=1)])

    def test_resume_accepts_only_original_owned_starters_and_receipt_explained_money(self):
        names=['qsa','qsb','qsc','qsd']
        state=dict(states=[dict(account=n,name=n,pets=[dict(id=1,progression={'0x8c4aef':1,'0x8c4b05':0})],wallet=[3100 if i==0 else 2900 if i==1 else 3000,0]) for i,n in enumerate(names)],
            wagers=[dict(status='settled',stake=100,pot=200,members=[['qsa',0,0],['qsb',1,1]],receipts=[['qsa','win',200],['qsb','lose',0]])])
        self.assertEqual(qa.validate_resumed_state(state,names),[3100,2900,3000,3000])
        state['states'][0]['wallet'][0]+=1
        with self.assertRaises(AssertionError):qa.validate_resumed_state(state,names)
        state['states'][0]['wallet'][0]-=1;state['states'][0]['pets'][0]['progression']['0x8c4b05']=1
        with self.assertRaises(AssertionError):qa.validate_resumed_state(state,names)


class LocalGameplayToolTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.MultiAccountTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        login,game=free_ports(2)
        self.case.config=replace(self.case.config,tls=TLSConfig(True,login,game,FIXTURES/'valid-chain.pem',FIXTURES/'valid-key.pem',2,4))
        self.path=self.case.config.database;self.base=Path(self.case.temp.name)
        groups=[]
        for prefix in ('qs12345678','qs87654321'):
            names=[prefix+'a',prefix+'b'];folder=self.base/('tio-before-surroundings-qa-'+prefix);folder.mkdir()
            with closing(sqlite3.connect(self.path)) as source,closing(sqlite3.connect(folder/'reservation.sqlite3')) as target:source.backup(target)
            passwords=['ordinary-password-123']*2
            for name,password in zip(names,passwords):self.case.accounts.create(name,password)
            with closing(sqlite3.connect(self.path)) as db:
                credentials={name:list(db.execute('SELECT hex(salt),hex(digest),iterations FROM accounts WHERE login=?',(name,)).fetchone()) for name in names}
            (folder/'qa-owned.json').write_text(json.dumps(dict(names=names,credentials=credentials)))
            groups.append(SimpleNamespace(names=names,passwords=passwords,backup=str(folder),host='127.0.0.1',key='local-test',ownership_payload=lambda names=names,folder=folder:dict(names=names,backup=str(folder))))
        self.owned=qa.FourFixture(groups)
        self.case.start()
        self.script=qa.SNAPSHOT.replace('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',self.path.as_uri()+'?mode=ro').replace("pathlib.Path('/root')",'pathlib.Path('+repr(str(self.base))+')')
        # Execute the exact remote read-only snapshot against this disposable
        # local SQLite. Every economic change still comes through native TLS.
        def status(hashes):
            payload=dict(names=self.owned.names,fixtures=[f.ownership_payload() for f in groups],source_hashes=hashes)
            output=io.StringIO()
            with self.case.server.multi.team_arena.lock:
                count=len(self.case.server.multi.active_accounts)*2
                with patch('sys.stdin',io.StringIO(json.dumps(payload))),patch('subprocess.check_output',return_value='owned\n'*count),redirect_stdout(output):
                    exec(compile(self.script,'local-read-only-snapshot','exec'),{})
            return json.loads(output.getvalue())
        self.owned.status=status

    def test_entire_prepared_hosted_scenario_with_four_native_tls_accounts(self):
        args=SimpleNamespace(host='127.0.0.1',server_name='127.0.0.1',login_port=self.case.config.tls.login_port,
            session_port=self.case.config.tls.session_port,loopback_session_port=self.case.config.session_port,ca_file=FIXTURES/'ca.pem')
        report=dict(passed=False)
        qa.run(self.owned,args,report,{})
        self.assertTrue(report['passed'])
        self.assertEqual(report['survival4']['turn_circle'],4)
        self.assertTrue(report['wager2']['countdown_cancel_refund'])
        self.assertTrue(report['wager4']['forfeit_payout'])
        self.assertTrue(all(c['verified_chain_and_name'] for c in report['tls_channels']))
        self.assertFalse(any(s['plaintext_secret_found'] for c in report['tls_channels'] for s in c['wire'].values()))
        resumed=dict(passed=False);args.resume_owned=True;args.case=['wager4']
        qa.run(self.owned,args,resumed,{})
        self.assertTrue(resumed['passed'])
        self.assertTrue(resumed['resumed_owned_characters'])
        self.assertEqual(resumed['requested_cases'],['wager4'])
        self.assertTrue(resumed['wager4']['xp_skills_rank_unchanged'])
        self.assertIn('wallets',resumed['case_preservation']['wager4'])


if __name__=='__main__':unittest.main()
