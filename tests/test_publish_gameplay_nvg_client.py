"""Execute the reviewed SSH publisher transaction only in disposable files."""
import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock

from tools import publish_gameplay_nvg_client as tool


class NVGPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=(tool.NVG/'source/silver.dll').read_bytes();cls.after=(tool.NVG/'candidate/silver.dll').read_bytes()
        cls.plan=tool.nvg_patch_plan(cls.before,cls.after)
        cls.manifest=(tool.NVG/'source/manifest.json').read_bytes()
        cls.hashes=tool.server_sources(tool.FOLDER)

    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.live=self.root/'updates';self.downloads=self.root/'downloads';self.game=self.root/'game';self.private=self.root/'private'
        for p in (self.live/'blobs',self.downloads,self.game,self.private):p.mkdir(parents=True)
        for name in ('TIO-Launcher.exe','TIO-Launcher-0.1.4.exe'):(self.downloads/name).write_bytes(b'preserved launcher')
        self.config=self.root/'server.toml';self.config.write_bytes(b'preserved configuration')
        rows=[]
        for name,raw,seed in (('silver.dll',self.before,False),('base/autoexec.cfg',b'original autoexec',True),
                             ('base/config.cfg',b'original config',True)):
            digest=tool.sha(raw);(self.live/'blobs'/digest).write_bytes(raw)
            rows.append(dict(path=name,sha256=digest,size=len(raw),seed=seed))
        raw=b'unchanged public asset';digest=tool.sha(raw);(self.live/'blobs'/digest).write_bytes(raw)
        rows += [dict(path=f'base/reviewed/{i}.dat',sha256=digest,size=len(raw))for i in range(6327)]
        self.old=(json.dumps(dict(schema=1,version=tool.PREVIOUS_VERSION,news='preserved news',files=rows))+'\n').encode()
        with patch.object(tool,'BASE_MANIFEST_SHA',tool.sha(self.old)):self.new=tool.new_manifest(self.old)
        (self.live/'manifest.json').write_bytes(self.old)
        for name in tool.SERVER_FILES:
            target=self.game/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((tool.FOLDER/'runtime'/name).read_bytes())
        self.scope={};exec(compile(tool.REMOTE,'isolated-reviewed-nvg-publisher','exec'),self.scope)
        self.scope.update(LIVE=self.live,DOWNLOADS=self.downloads,GAME=self.game,PRIVATE=self.private,CONFIGS=(self.config,),
            BASELINE_MANIFEST_SHA=tool.sha(self.old),service=lambda:dict(ActiveState='active',MainPID='123',NRestarts='0'))
        self.payload=dict(operation='a'*32,before_manifest=base64.b64encode(self.old).decode(),after_manifest=base64.b64encode(self.new).decode(),
            candidate=base64.b64encode(self.after).decode(),plan=copy.deepcopy(self.plan),server_source_sha256=dict(self.hashes),
            server_abi={n:self.hashes[n]for n in tool.SERVER_ABI})
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules,fcntl=SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *args:None)).start()

    def publish(self,payload=None):return self.scope['publish'](self.payload if payload is None else payload)

    def test_exact_official_manifest_changes_one_of_6330_records(self):
        new=tool.new_manifest(self.manifest);self.assertEqual(tool.transition(self.manifest,new),['silver.dll'])
        a,b=json.loads(self.manifest),json.loads(new)
        self.assertEqual(len(a['files']),6330);self.assertEqual(a['news'],b['news'])
        self.assertEqual([r for r in a['files']if r['path']!='silver.dll'],[r for r in b['files']if r['path']!='silver.dll'])
        self.assertTrue(any(r['size']==0 for r in a['files']))

    def test_wrong_manifest_hash_count_seeds_and_private_paths_refuse(self):
        data=json.loads(self.manifest)
        for change in ('news','count','seed','path','schema'):
            value=copy.deepcopy(data)
            if change=='news':value['news']='changed'
            elif change=='count':value['files'].pop()
            elif change=='seed':next(r for r in value['files']if r['path']=='base/config.cfg')['seed']=False
            elif change=='path':value['files'][1]['path']='base/login.ini'
            else:value['schema']=True
            with self.subTest(change=change),self.assertRaises(ValueError):tool.checked_manifest(json.dumps(value).encode(),version=tool.PREVIOUS_VERSION)
        for path in ('../evil','base\\evil','C:/evil','base/../evil','base//evil','base/evil\0'):
            value=copy.deepcopy(data);value['files'][1]['path']=path
            with self.subTest(path=path),self.assertRaises(ValueError):tool.checked_manifest(json.dumps(value).encode(),version=tool.PREVIOUS_VERSION)

    def test_remote_catalogue_requires_6330_and_original_seeds(self):
        value=json.loads(self.old);self.assertEqual(len(self.scope['catalogue'](self.old,tool.PREVIOUS_VERSION)['files']),6330)
        for change in ('count','seed','login','schema'):
            bad=copy.deepcopy(value)
            if change=='count':bad['files'].pop()
            elif change=='seed':bad['files'][1]['seed']=False
            elif change=='login':bad['files'][3]['path']='login.ini'
            else:bad['schema']=True
            raw=json.dumps(bad).encode();self.scope['BASELINE_MANIFEST_SHA']=tool.sha(raw)
            with self.subTest(change=change),self.assertRaises(ValueError):self.scope['catalogue'](raw,tool.PREVIOUS_VERSION)

    def test_trusted_exact_remote_substitutions_fail_closed(self):
        self.assertEqual(tool.sha(tool.established.REMOTE.encode()),tool.ESTABLISHED_REMOTE_SHA)
        with patch.object(tool.established,'REMOTE',tool.established.REMOTE+'\n'):
            with self.assertRaises(ValueError):tool.remote_program()
        with self.assertRaises(ValueError):tool.amend('guard twice guard','guard','new')
        for preserved in ('fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)','guards()!=state','private_json(journal,result)',
                          "(LIVE/'manifest.json').read_bytes()==new",'previous-code-config.tar.gz'):
            self.assertIn(preserved,tool.REMOTE)
        self.assertNotIn('sqlite3',tool.REMOTE);self.assertNotIn('systemctl restart',tool.REMOTE)

    def test_complete_publication_backups_journal_blobs_and_service_preserved(self):
        guards=self.scope['guards']();result=self.publish();saved=Path(result['backup'])
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.new);self.assertEqual(self.scope['guards'](),guards)
        self.assertEqual((saved/'manifest.json').read_bytes(),self.old);self.assertEqual((saved/'silver.dll').read_bytes(),self.before)
        self.assertEqual((saved/'TIO-Launcher-0.1.4.exe').read_bytes(),b'preserved launcher')
        self.assertTrue((saved/'previous-code-config.tar.gz').is_file())
        self.assertFalse(result['database_opened']);self.assertFalse(result['database_written']);self.assertFalse(result['server_restarted'])
        self.assertFalse(result['local_player_data_uploaded']);self.assertTrue(result['launchers_preserved'])
        self.assertEqual(result['blob_coverage']['verified_records'],6330)
        self.assertEqual(result['changed'],['silver.dll']);self.assertEqual(result['version'],tool.VERSION)
        self.assertTrue((self.private/('tio-nvg-client-'+'a'*32+'.json')).is_file())

    def test_completed_operation_recovers_without_second_backup(self):
        first=self.publish();second=self.publish()
        self.assertTrue(second['recovered_completed_publication']);self.assertEqual(first['backup'],second['backup'])
        self.assertEqual(len(list(self.private.glob('tio-before-nvg-client-*'))),1)

    def test_recovery_rejects_changed_deployed_runtime(self):
        self.publish();(self.game/'tio/battle_item_visuals.py').write_bytes(b'changed deployed ABI')
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.new)

    def test_corrupt_other_blob_and_immutable_candidate_refuse(self):
        row=json.loads(self.old)['files'][3];(self.live/'blobs'/row['sha256']).write_bytes(b'corrupt')
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old);self.assertEqual(list(self.private.glob('tio-before-nvg-client-*')),[])
        (self.live/'blobs'/row['sha256']).write_bytes(b'unchanged public asset')
        (self.live/'blobs'/tool.CANDIDATE_SHA).write_bytes(b'corrupt immutable candidate')
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)

    def test_unrelated_manifest_change_refuses(self):
        broken=copy.deepcopy(self.payload);value=json.loads(self.new);value['files'][3]['seed']=True
        broken['after_manifest']=base64.b64encode(json.dumps(value).encode()).decode()
        with self.assertRaises(ValueError):self.publish(broken)
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)

    def test_wrong_f9_abi_and_missing_full_release_guard_refuse(self):
        for mode in ('abi','missing','runtime'):
            broken=copy.deepcopy(self.payload)
            if mode=='abi':broken['server_abi'][tool.SERVER_ABI[0]]='0'*64
            elif mode=='missing':broken['server_source_sha256'].pop('server/private_market.py')
            else:broken['server_source_sha256']['server/assault_public.py']='0'*64
            with self.subTest(mode=mode),self.assertRaises(RuntimeError):self.publish(broken)
            self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)

    def test_candidate_and_five_hunk_free_off_guards_refuse_tampering(self):
        for mode in ('candidate','hunks','ap','activation','consume'):
            broken=copy.deepcopy(self.payload)
            if mode=='candidate':raw=bytearray(self.after);raw[-1]^=1;broken['candidate']=base64.b64encode(raw).decode()
            elif mode=='hunks':broken['plan']['changes'].pop()
            elif mode=='ap':broken['plan']['free_off_ap']=[0,1,2,3]
            elif mode=='activation':broken['plan']['activation_original_ap_gate_preserved']=False
            else:broken['plan']['shortcut_consumed_before_free_off']=False
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.publish(broken)
            self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)

    def test_competing_manifest_during_backup_is_preserved(self):
        data=json.loads(self.old);data['news']='competing release';raw=json.dumps(data).encode();original=self.scope['backup']
        def changed(*args):
            saved=original(*args);(self.live/'manifest.json').write_bytes(raw);return saved
        self.scope['backup']=changed
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),raw)

    def test_ten_file_runtime_change_during_backup_refuses(self):
        original=self.scope['backup']
        def changed(*args):
            saved=original(*args);(self.game/'server/assault_public.py').write_bytes(b'concurrent change');return saved
        self.scope['backup']=changed
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)

    def test_service_change_after_commit_rolls_back_manifest(self):
        original=self.scope['atomic']
        def changed(raw,path):
            original(raw,path)
            if path==self.live/'manifest.json'and raw==self.new:self.scope['service']=lambda:dict(ActiveState='active',MainPID='456',NRestarts='1')
        self.scope['atomic']=changed
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)
        saved=next(self.private.glob('tio-before-nvg-client-*'))
        self.assertTrue(json.loads((saved/'rollback.json').read_text())['manifest_restored'])

    def test_concurrent_manifest_after_commit_survives_rollback(self):
        value=json.loads(self.new);value['news']='newer concurrent release';other=json.dumps(value).encode();original=self.scope['atomic']
        def changed(raw,path):
            original(raw,path)
            if path==self.live/'manifest.json'and raw==self.new:path.write_bytes(other)
        self.scope['atomic']=changed
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),other)

    def test_private_audit_failure_rolls_back_without_completed_journal(self):
        original=self.scope['private_json']
        def failed(path,value):
            if path.name=='publication.json':raise OSError('isolated audit failure')
            return original(path,value)
        self.scope['private_json']=failed
        with self.assertRaises(OSError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)
        self.assertFalse((self.private/('tio-nvg-client-'+'a'*32+'.json')).exists())

    def test_native_evidence_exact_hash_sources_and_plan(self):
        proof,tests,plan=tool.native_evidence(self.before,self.after)
        self.assertEqual(tool.sha(proof),tool.NATIVE_PROOF_SHA);self.assertEqual(tool.sha(tests),tool.NATIVE_TEST_SHA)
        self.assertEqual(plan,self.plan)
        with patch.object(tool,'native_sources',return_value={}):
            with self.assertRaises(ValueError):tool.native_evidence(self.before,self.after)

    def test_only_exact_frozen_release_folder_allowed(self):
        self.assertEqual(tool.folder_checked(tool.FOLDER),tool.FOLDER)
        for folder in (tool.ROOT/'reports/contracts-local',tool.FOLDER/'child',tool.FOLDER.parent/'stage9-interfaces',self.root):
            with self.subTest(folder=str(folder)),self.assertRaises(ValueError):tool.folder_checked(folder)

    def test_exact_144_isolated_validation_rejects_skips_and_source_changes(self):
        good=dict(passed=True,source_unchanged=True,source_sha256=self.hashes,exit_code=0,output='\nRan 144 tests in 12.345s\n\nOK\n')
        tool.isolated_validation(good,self.hashes)
        for mode in ('count','skip','hash','exit','passed'):
            value=copy.deepcopy(good)
            if mode=='count':value['output']=value['output'].replace('144','121')
            elif mode=='skip':value['output']=value['output'].replace('OK','OK (skipped=1)')
            elif mode=='hash':value['source_sha256']['server/assault_public.py']='0'*64
            elif mode=='exit':value['exit_code']=1
            else:value['passed']=False
            with self.subTest(mode=mode),self.assertRaises(ValueError):tool.isolated_validation(value,self.hashes)

    def test_publish_requires_deployment_before_any_remote_write(self):
        release=dict(server_source_sha256=self.hashes)
        with patch.object(tool,'reviewed',return_value=(release,self.old,self.new,self.after)),\
             patch.object(tool,'deployment_evidence',side_effect=ValueError('deployment pending')),\
             patch.object(tool.established,'remote')as remote:
            with self.assertRaises(ValueError):tool.publish(tool.FOLDER)
            remote.assert_not_called()

    def test_all_four_server_evidence_records_required_before_publication(self):
        folder=self.root/'release';folder.mkdir()
        valid=dict(passed=True,source_unchanged=True,source_sha256=self.hashes,exit_code=0,output='\nRan 144 tests in 1.234s\n\nOK\n')
        deployment=dict(source_parity=True,source_sha256=self.hashes,service='active',backup='/root/tio-before-gameplay-completion-reviewed')
        names=('local-validation.json','hosted-isolated-validation.json','validation.json','deployment.json')
        for name in names:(folder/name).write_text(json.dumps(deployment if name=='deployment.json'else valid),encoding='utf-8')
        with patch.object(tool,'FOLDER',folder):
            result=tool.deployment_evidence(folder,self.hashes);self.assertEqual(set(result),set(names))
            for name in names:
                path=folder/name;old=path.read_bytes();bad=json.loads(old)
                bad['source_sha256']['server/private_market.py']='0'*64;path.write_text(json.dumps(bad),encoding='utf-8')
                with self.subTest(name=name),self.assertRaises(ValueError):tool.deployment_evidence(folder,self.hashes)
                path.write_bytes(old)
            path=folder/'hosted-isolated-validation.json';path.unlink()
            with self.assertRaises(FileNotFoundError):tool.deployment_evidence(folder,self.hashes)

    def test_prepare_is_read_only_remote_and_preserves_existing_native_proof(self):
        folder=self.root/'report';folder.mkdir();observed=dict(manifest=base64.b64encode(self.manifest).decode(),manifest_sha256=tool.sha(self.manifest))
        def fetch(name,maximum):return self.manifest if name=='manifest.json'else self.before
        native_before=(tool.NVG/'native-proof.json').read_bytes()
        with patch.object(tool,'FOLDER',folder),patch.object(tool,'server_sources',return_value=self.hashes),\
             patch.object(tool,'fetch',side_effect=fetch),patch.object(tool.established,'remote',return_value=observed)as remote:
            release=tool.prepare(folder)
            self.assertFalse(release['published']);self.assertFalse(release['graphical_acceptance_complete'])
            self.assertEqual(remote.call_count,2)
            for call in remote.call_args_list:self.assertEqual(call.args,(tool.READ,{}))
            self.assertEqual((folder/'client/candidate/silver.dll').read_bytes(),self.after)
            with self.assertRaises(ValueError):tool.prepare(folder)
        self.assertEqual((tool.NVG/'native-proof.json').read_bytes(),native_before)


if __name__=='__main__':unittest.main()
