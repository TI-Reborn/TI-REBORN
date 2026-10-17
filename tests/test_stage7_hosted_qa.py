from contextlib import closing,redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import verify_hosted_stage7 as qa


class HostedStage7ToolTests(unittest.TestCase):
    def test_remote_proofs_are_readonly_and_provision_is_empty_normal_two_accounts(self):
        for source in (qa.PROVISION,qa.SNAPSHOT,qa.PRESERVATION):compile(source,'remote proof','exec')
        self.assertIn("assert len(names)==2",qa.PROVISION)
        self.assertIn('create(name,password)',qa.PROVISION)
        self.assertNotIn('create(name,password,character=',qa.PROVISION)
        self.assertLess(qa.PROVISION.index('battle_settlement_jobs'),qa.PROVISION.index('folder=pathlib.Path(tempfile.mkdtemp'))
        for source in (qa.SNAPSHOT,qa.PRESERVATION):
            for operation in ('INSERT ','UPDATE ','DELETE ','CREATE '):self.assertNotIn(operation,source)
        for port in (28512,28513,29512,29513):self.assertIn(str(port),qa.PROVISION)
        self.assertIn('alias(n,2)',qa.PRESERVATION)

    def test_prepare_is_local_currentuser_private_never_overwrites_or_prints_password(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(qa,'PRIVATE',Path(temp)/'private'),patch.object(qa.Stage7Fixture,'private_directory'),patch.object(qa.FreshSurroundingsQA,'remote',side_effect=AssertionError('Unexpected SSH')):
            qa.PRIVATE.mkdir();(qa.PRIVATE/'.gitignore').write_text('*\n')
            fixture=qa.Stage7Fixture.prepare('127.0.0.1','local-key');loaded=qa.Stage7Fixture.load(fixture.credential_path)
            self.assertEqual(loaded.passwords,fixture.passwords)
            self.assertTrue(all(len(value)==16 for value in fixture.passwords))
            self.assertEqual(fixture.names,[fixture.prefix+'a',fixture.prefix+'b'])
            with self.assertRaises(AssertionError):fixture.save(pending=True)

    def test_dynamic_deployment_source_keys_hashes_and_paths_are_exact(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(qa,'ROOT',Path(temp)):
            root=Path(temp);(root/'reports/stage7').mkdir(parents=True);(root/'tio').mkdir()
            (root/'tio/a.py').write_text('example=1\n');digest=hashlib.sha256((root/'tio/a.py').read_bytes()).hexdigest()
            (root/'reports/stage7/runtime-files.json').write_text(json.dumps(['tio/a.py']))
            proof=root/'deployment.json';proof.write_text(json.dumps(dict(source_parity=True,source_sha256={'tio/a.py':digest})))
            self.assertEqual(qa.deployment_hashes(proof),{'tio/a.py':digest})
            (root/'tio/a.py').write_text('example=2\n')
            with self.assertRaises(AssertionError):qa.deployment_hashes(proof)

    def test_real_local_strict_tls_fresh_two_slots_offline_mail_repeat_relogin_and_standings(self):
        # Only the remote path/ownership/ss observations are adapted. Native
        # packet framing, TLS, handlers, four character saves and mail are real.
        from test_multi_account import MultiAccountTests
        from test_game_tls import free_ports,FIXTURES
        from server.config import TLSConfig
        case=MultiAccountTests();case.setUp();self.addCleanup(case.doCleanups)
        ports=free_ports(2);case.config=replace(case.config,tls=TLSConfig(True,*ports,FIXTURES/'valid-chain.pem',FIXTURES/'valid-key.pem'))
        backup=case.config.data_directory/'before-stage7-local';backup.mkdir()
        with closing(sqlite3.connect(case.config.database)) as src,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:src.backup(dst)
        names=['qs71234567a','qs71234567b'];passwords=['LocalPassword123','OtherPassword123']
        for name,password in zip(names,passwords):case.accounts.create(name,password)
        fixture=qa.Stage7Fixture('127.0.0.1','qs71234567',names,passwords,str(backup),'local-key')
        def remote(code,payload):
            self.assertTrue(code.startswith(qa.OWNERSHIP));source=code[len(qa.OWNERSHIP):]
            for operation in ('INSERT ','UPDATE ','DELETE ','CREATE '):self.assertNotIn(operation,source)
            source=source.replace('/var/lib/tio-server/reservation.sqlite3',case.config.database.as_posix())
            source='import json,pathlib,sqlite3,sys\ndata=json.load(sys.stdin);names=data["names"];folder=pathlib.Path(data["backup"])\n'+source
            out=io.StringIO()
            with patch.object(sys,'stdin',io.StringIO(json.dumps(payload))),redirect_stdout(out),patch('subprocess.check_output',side_effect=lambda *a,**k:'owned-session\n'*len(case.server.multi.active_accounts)):
                exec(compile(source,'<local readonly Stage7 proof>','exec'),{})
            return json.loads(out.getvalue())
        fixture.remote=remote
        args=SimpleNamespace(host='127.0.0.1',server_name='localhost',login_port=ports[0],session_port=ports[1],ca_file=FIXTURES/'ca.pem',loopback_session_port=31003)
        hashes={name:hashlib.sha256((qa.ROOT/name).read_bytes()).hexdigest() for name in ('tio/characters.py','tio/protocol/mail.py')}
        case.start();report=dict(passed=False);qa.run(fixture,args,report,hashes)
        self.assertTrue(report['passed']);self.assertTrue(report['finalize_replay_once']);self.assertTrue(report['claim_replay_once'])
        self.assertTrue(report['primary_slots_unchanged']);self.assertTrue(report['secondary_relogin_preserved'])
        self.assertTrue(report['global_claims_battles_ratings_unchanged']);self.assertEqual(report['mail_transfer'],10)
        self.assertTrue(all(channel['verified_chain_and_name'] for channel in report['tls_channels']))
        self.assertTrue(all(not direction['plaintext_secret_found'] for channel in report['tls_channels'] for direction in channel['wire'].values()))


if __name__=='__main__':unittest.main()
