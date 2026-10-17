"""Exercise the independent checker against synthetic local hosted backups.

No SSH, HTTP request or actual hosted mutation. Account credentials and tar
members are verified with real SQLite/tarfile; POSIX ownership is simulated.
"""
import base64
import contextlib
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tarfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import publish_ui_modernization_remote as publisher
from tools import verify_ui_modernization_publication as verifier
from tools.test_publish_ui_modernization_remote import Guards


class IndependentGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Guards.setUpClass()
        cls.fixtures=Guards('test_exact_one_record_transition')

    @classmethod
    def tearDownClass(cls):
        Guards.tearDownClass()

    def fixture(self,both=True):
        ns,live,private,db,guards=self.fixtures.fixture()
        with closing(sqlite3.connect(db)) as connection, connection:
            for column in ('salt BLOB','digest BLOB','iterations INTEGER'):
                connection.execute('ALTER TABLE accounts ADD COLUMN '+column)
            connection.execute('UPDATE accounts SET salt=?,digest=?,iterations=?',(b'private-test-salt',b'private-test-digest',200000))
        source=ns['GAME']/'server/source.py'
        with tarfile.open(mode='w',fileobj=__import__('io').BytesIO()) as archive:
            metadata=archive.gettarinfo(str(source),arcname='server/source.py')
        guards['configuration']={}
        guards['game_code']={'server/source.py':dict(sha256=publisher.sha(source.read_bytes()),size=metadata.size,mode=metadata.mode&0o777,uid=metadata.uid,gid=metadata.gid)}
        receipt=ns['execute'](self.fixtures.payload(both=both,action='apply'))
        checked={'__name__':'isolated_read_only_checker'}
        exec(verifier.REMOTE.split("if __name__=='__main__':")[0],checked)
        checked.update(LIVE=live,PRIVATE=private,GAME=ns['GAME'],DB=db)
        original_state=checked['state']
        checked['state']=lambda path:dict(original_state(path),uid=0,gid=0,mode=0o644)
        checked['private_directory']=checked['directory']
        checked['guards']=lambda:copy.deepcopy(guards)
        inspected=dict(passed=True,remote_mutations=0,manifest_sha256=publisher.MANIFEST_SHA,guards=guards)
        request=verifier.make_request(self.fixtures.payload(both=both),receipt,inspected)
        return checked,request,live,Path(receipt['backup']),db,guards

    def refresh_backup_checksum(self,ns,folder,name):
        path=folder/'backup-manifest.json';receipt=json.loads(path.read_bytes())
        receipt['files'][name]=ns['state'](folder/name)
        path.write_text(json.dumps(receipt))

    def test_success_is_read_only_and_private_credentials_not_returned(self):
        ns,request,live,folder,db,guards=self.fixture()
        files={path:publisher.sha(path.read_bytes()) for path in [db,*folder.iterdir(),live/'manifest.json'] if path.is_file()}
        result=ns['verify'](request)
        self.assertTrue(result['passed']);self.assertEqual(result['remote_mutations'],0)
        self.assertEqual(result['other_client_records_preserved'],6328)
        self.assertEqual(result['backup_accounts'],202);self.assertTrue(result['account_identities_and_credentials_preserved'])
        self.assertNotIn('hosted_0',json.dumps(result));self.assertNotIn('private-test',json.dumps(result))
        self.assertEqual(files,{path:publisher.sha(path.read_bytes()) for path in files})

    def test_read_only_program_has_no_publication_or_write_functions(self):
        self.assertNotIn('def atomic(',verifier.REMOTE);self.assertNotIn('def immutable(',verifier.REMOTE)
        for text in ('.backup(','.write_bytes(','.write_text(','os.replace(','os.link(','systemctl restart'):
            self.assertNotIn(text,verifier.REMOTE)

    def test_silver_only_preserves6329_records_and_pinned_ti(self):
        ns,request,live,folder,db,guards=self.fixture(both=False)
        report=ns['verify'](request)
        self.assertEqual(report['other_client_records_preserved'],6329)
        self.assertEqual(set(report['candidates']),{'silver.dll'})
        self.assertEqual(report['unchanged_native'],{'ti.exe':dict(sha256=publisher.SOURCES['ti.exe'][0],bytes=publisher.SOURCES['ti.exe'][1])})
        self.assertEqual(report['backup_file_checksums_verified'],6)
        self.assertFalse((folder/'ti.exe').exists())

    def test_silver_only_rejects_corrupt_pinned_unchanged_ti(self):
        ns,request,live,*_=self.fixture(both=False)
        (live/'blobs'/publisher.SOURCES['ti.exe'][0]).write_bytes(b'wrong')
        with self.assertRaises(RuntimeError):ns['verify'](request)

    def test_partial_optional_ti_cli_refused_before_network(self):
        args=['--silver',str(self.fixtures.silver_path),'--silver-sha256',publisher.sha(self.fixtures.silver),'--silver-bytes',str(len(self.fixtures.silver)),
              '--ti',str(self.fixtures.ti_path),'--receipt',str(self.fixtures.folder/'unused.json'),'--report',str(self.fixtures.folder/'unused-check.json')]
        with patch.object(verifier,'verify_publication') as call,contextlib.redirect_stderr(__import__('io').StringIO()),self.assertRaises(SystemExit):verifier.main(args)
        call.assert_not_called()

    def test_wrong_scope_and_receipt_refused(self):
        ns,request,*_=self.fixture()
        request['updates'].pop('silver.dll')
        with self.assertRaises(ValueError):ns['verify'](request)
        ns,request,*_=self.fixture();request['receipt']['version']='2026.10.09.10'
        with self.assertRaises(RuntimeError):ns['verify'](request)

    def test_current_manifest_and_blob_mismatch_refused(self):
        ns,request,live,*_=self.fixture();(live/'manifest.json').write_bytes(b'wrong')
        with self.assertRaises(RuntimeError):ns['verify'](request)
        ns,request,live,*_=self.fixture();(live/'blobs'/request['updates']['ti.exe']['sha256']).write_bytes(b'wrong')
        with self.assertRaises(RuntimeError):ns['verify'](request)

    def test_live_guards_change_refused(self):
        for key in ('services','launchers','configuration','game_code'):
            ns,request,live,folder,db,guards=self.fixture()
            guards[key]['unexpected']='changed'
            with self.assertRaises(RuntimeError):ns['verify'](request)

    def test_backup_outside_private_scope_refused(self):
        ns,request,*_=self.fixture();request['receipt']['backup']=str(ROOT/'reports/other-backup')
        with self.assertRaises(ValueError):ns['verify'](request)

    def test_durable_receipt_and_journal_mismatch_refused(self):
        ns,request,live,folder,*_=self.fixture();(folder/'publication.json').write_text('{}')
        with self.assertRaises(RuntimeError):ns['verify'](request)
        ns,request,live,folder,*_=self.fixture();(folder/'publication-journal.json').write_text('{}')
        with self.assertRaises(RuntimeError):ns['verify'](request)

    def test_backup_inventory_and_checksum_mismatch_refused(self):
        ns,request,live,folder,*_=self.fixture();(folder/'ti.exe').write_bytes(b'wrong')
        with self.assertRaises(RuntimeError):ns['verify'](request)
        ns,request,live,folder,*_=self.fixture();path=folder/'backup-manifest.json';receipt=json.loads(path.read_bytes())
        receipt['files'].pop('reservation.sqlite3');path.write_text(json.dumps(receipt))
        with self.assertRaises(RuntimeError):ns['verify'](request)

    def test_prior_manifest_and_native_identity_independently_verified(self):
        for name in ('previous-manifest.json','silver.dll','ti.exe'):
            ns,request,live,folder,*_=self.fixture();(folder/name).write_bytes(b'wrong')
            self.refresh_backup_checksum(ns,folder,name)
            with self.assertRaises(RuntimeError):ns['verify'](request)

    def test_code_backup_checked_against_inspected_content(self):
        ns,request,live,folder,*_=self.fixture()
        with tarfile.open(folder/'previous-code.tar.gz','w:gz') as archive:
            import io
            item=tarfile.TarInfo('server/source.py');item.mode=0o666;item.size=5
            archive.addfile(item,io.BytesIO(b'wrong'))
        self.refresh_backup_checksum(ns,folder,'previous-code.tar.gz')
        with self.assertRaises(RuntimeError):ns['verify'](request)

    def test_missing_account_identity_or_changed_credentials_refused(self):
        for statement in ("DELETE FROM accounts WHERE login='hosted_0'","UPDATE accounts SET digest=x'0102' WHERE login='hosted_0'"):
            ns,request,live,folder,db,*_=self.fixture()
            with closing(sqlite3.connect(db)) as connection, connection:connection.execute(statement)
            after=publisher.sha(db.read_bytes())
            with self.assertRaises(RuntimeError):ns['verify'](request)
            self.assertEqual(after,publisher.sha(db.read_bytes()))

    def test_additional_real_account_permitted(self):
        ns,request,live,folder,db,*_=self.fixture()
        with closing(sqlite3.connect(db)) as connection, connection:
            connection.execute('INSERT INTO accounts VALUES(?,?,?,?)',('new_live_account',b'new',b'new',200000))
        self.assertEqual(ns['verify'](request)['accounts_after'],203)

    def test_existing_unrelated_checkpoint_permitted_and_untouched(self):
        ns,request,live,folder,db,*_=self.fixture()
        with closing(sqlite3.connect(db)) as connection, connection:connection.execute('INSERT INTO battle_checkpoints VALUES(17)')
        before=db.read_bytes();report=ns['verify'](request)
        self.assertEqual(report['health']['checkpoints'],1);self.assertEqual(db.read_bytes(),before)

    def test_state_race_in_final_guard_scan_refused(self):
        ns,request,live,folder,db,guards=self.fixture();calls=[]
        def raced():
            calls.append(1)
            if len(calls)>1:(live/'manifest.json').write_bytes(b'concurrent publication')
            return copy.deepcopy(guards)
        ns['guards']=raced
        with self.assertRaises(RuntimeError):ns['verify'](request)

    def test_untrusted_inspect_evidence_refused_before_ssh(self):
        for key,value in (('passed',False),('remote_mutations',1),('manifest_sha256','0'*64)):
            evidence=dict(passed=True,remote_mutations=0,manifest_sha256=publisher.MANIFEST_SHA,guards={});evidence[key]=value
            with self.assertRaises(ValueError):verifier.make_request(self.fixtures.payload(),{},evidence)

    def test_https_manifest_and_either_blob_mismatch_refused(self):
        payload=self.fixtures.payload()
        expected=base64.b64decode(payload['after_manifest'])
        raws={value['sha256']:base64.b64decode(value['blob']) for value in payload['updates'].values()}
        def response(path,maximum):return expected if path=='manifest.json' else raws[path.split('/')[-1]]
        with patch.object(publisher,'fetch',side_effect=response):self.assertTrue(publisher.verify_https(payload)['passed'])
        for target in ['manifest.json',*('blobs/'+value['sha256'] for value in payload['updates'].values())]:
            def wrong(path,maximum):return b'wrong' if path==target else response(path,maximum)
            with patch.object(publisher,'fetch',side_effect=wrong),self.assertRaises(ValueError):publisher.verify_https(payload)

    def test_silver_only_https_verifies_pinned_ti_with_exact_manifest(self):
        payload=self.fixtures.payload(both=False)
        expected=base64.b64decode(payload['after_manifest'])
        raws={publisher.sha(self.fixtures.silver):self.fixtures.silver,publisher.SOURCES['ti.exe'][0]:self.fixtures.sources['ti.exe']}
        def response(path,maximum):return expected if path=='manifest.json' else raws[path.split('/')[-1]]
        with patch.object(publisher,'fetch',side_effect=response):
            report=verifier.verify_https(payload)
            self.assertEqual(report['other_client_records_preserved'],6329)
            self.assertEqual(report['unchanged_native']['ti.exe']['sha256'],publisher.SOURCES['ti.exe'][0])
        def wrong(path,maximum):return b'wrong' if path=='blobs/'+publisher.SOURCES['ti.exe'][0] else response(path,maximum)
        with patch.object(publisher,'fetch',side_effect=wrong),self.assertRaises(ValueError):verifier.verify_https(payload)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(IndependentGuards))
    report=dict(passed=result.wasSuccessful(),tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),remote_mutations=0,network_calls=0,
                production_candidate_tested=False,checker_sha256=publisher.sha(Path(verifier.__file__).read_bytes()),remote_program_sha256=publisher.sha(verifier.REMOTE.encode()),
                posix_metadata_simulated=True,sqlite_and_tar_content_checks_real=True)
    (publisher.REPORT_ROOT/'postpublication-checker-guard-tests.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if not result.wasSuccessful():raise SystemExit(1)
