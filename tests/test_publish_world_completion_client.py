import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import publish_world_completion_client as tool


class WorldPublishSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=tool.FOLDER
        cls.source=(cls.folder/'client/source/zones.xml').read_bytes()
        cls.candidate=(cls.folder/'client/candidate/zones.xml').read_bytes()
        cls.runtime=(cls.folder/'runtime/evidence/zones_diagnostic.xml').read_bytes()
        cls.policy=(tool.ROOT/'config/world_completion.json').read_bytes()
        cls.dll=(tool.ROOT/'reports/gameplay-completion/stage6-economy/client/candidate/silver.dll').read_bytes()
        cls.catalog=json.loads((cls.folder/'catalog.json').read_bytes())

    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup);self.root=Path(directory.name)
        self.live=self.root/'updates';self.downloads=self.root/'downloads';self.game=self.root/'game';self.private=self.root/'private'
        for path in (self.live/'blobs',self.downloads,self.game,self.private):path.mkdir(parents=True)
        for name in ('TIO-Launcher.exe','TIO-Launcher-0.1.4.exe'):(self.downloads/name).write_bytes(b'unchanged launcher')
        self.config=self.root/'server.toml';self.config.write_bytes(b'untouched server configuration')
        self.runtime_hashes={}
        for name,raw in (('config/world_completion.json',self.policy),('evidence/zones_diagnostic.xml',self.runtime),('tio/world_completion.py',b'reviewed world runtime')):
            path=self.game/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);self.runtime_hashes[name]=tool.sha(raw)
        rows=[]
        for name,raw,seed in (('silver.dll',self.dll,False),(tool.CLIENT_PATH,self.source,False),
                              ('base/config.cfg',b'client seed',True),('base/empty.xml',b'',False),
                              ('base/shared config/contracts.xml',b'unchanged parallel contract',False)):
            identity=tool.sha(raw);(self.live/'blobs'/identity).write_bytes(raw)
            rows.append(dict(path=name,size=len(raw),sha256=identity,seed=seed))
        self.old=(json.dumps(dict(schema=1,version=tool.PREVIOUS_VERSION,news='preserve news',metadata={'root':'unchanged'},files=rows))+'\n').encode()
        self.new=tool.new_manifest(self.old,self.candidate);(self.live/'manifest.json').write_bytes(self.old)
        self.release=dict(policy_sha256=tool.sha(self.policy),runtime_sha256=tool.sha(self.runtime),candidate_sha256=tool.sha(self.candidate),native_proof_sha256='a'*64)
        self.payload=dict(operation='1'*32,before_manifest=base64.b64encode(self.old).decode(),after_manifest=base64.b64encode(self.new).decode(),
            candidate=base64.b64encode(self.candidate).decode(),candidate_sha256=tool.sha(self.candidate),candidate_bytes=len(self.candidate),
            server_runtime=self.runtime_hashes,world_client_release=self.release)
        self.scope={};exec(compile(tool.REMOTE,'reviewed-world-remote','exec'),self.scope)
        self.scope.update(LIVE=self.live,DOWNLOADS=self.downloads,GAME=self.game,PRIVATE=self.private,CONFIGS=(self.config,),
            service=lambda:dict(ActiveState='active',MainPID='123',NRestarts='0'))
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules,fcntl=SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *args:None)).start()

    def publish(self,payload=None):return self.scope['publish'](self.payload if payload is None else payload)

    def test_manifest_changes_only_zones_and_preserves_all_metadata_seeds_empty_files(self):
        self.assertEqual(tool.transition(self.old,self.new,self.candidate),[tool.CLIENT_PATH])
        a,b=json.loads(self.old),json.loads(self.new)
        self.assertEqual(a['news'],b['news']);self.assertEqual(a['metadata'],b['metadata'])
        self.assertEqual(a['files'][0],b['files'][0]);self.assertEqual(a['files'][2:],b['files'][2:])
        self.assertEqual(self.scope['catalogue'](self.old,tool.PREVIOUS_VERSION),a)
        for path in ('../evil','base\\evil','C:/evil','base/../evil','base//evil','base/evil\0'):
            broken=copy.deepcopy(a);broken['files'][2]['path']=path;raw=json.dumps(broken).encode()
            with self.assertRaises(ValueError):tool.checked_manifest(raw,tool.PREVIOUS_VERSION)
            with self.assertRaises(ValueError):self.scope['catalogue'](raw,tool.PREVIOUS_VERSION)
        broken=copy.deepcopy(a);broken['files'].append(broken['files'][-1])
        with self.assertRaises(ValueError):tool.checked_manifest(json.dumps(broken).encode(),tool.PREVIOUS_VERSION)

    def test_publication_backups_and_service_launchers_database_preservation(self):
        guards=self.scope['guards'](self.runtime_hashes);result=self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.new)
        self.assertEqual(self.scope['guards'](self.runtime_hashes),guards)
        backup=Path(result['backup'])
        self.assertEqual((backup/'manifest.json').read_bytes(),self.old)
        self.assertEqual((backup/'zones.xml').read_bytes(),self.source)
        self.assertEqual((backup/'TIO-Launcher.exe').read_bytes(),b'unchanged launcher')
        self.assertTrue((backup/'previous-code-config.tar.gz').is_file())
        self.assertFalse(result['database_opened']);self.assertFalse(result['database_written']);self.assertFalse(result['server_restarted'])
        self.assertFalse(result['local_player_data_uploaded']);self.assertTrue(result['other_client_files_preserved'])
        self.assertEqual(result['blob_coverage']['verified_records'],5)
        self.assertNotIn('sqlite3',tool.REMOTE);self.assertNotIn('/var/lib/tio-server',tool.REMOTE)

    def test_same_operation_recovers_without_second_backup_and_requires_same_runtime(self):
        first=self.publish();second=self.publish()
        self.assertTrue(second['recovered_completed_publication']);self.assertEqual(first['backup'],second['backup'])
        self.assertEqual(len(list(self.private.glob('tio-before-world-client-*'))),1)
        (self.game/'tio/world_completion.py').write_bytes(b'changed after publication')
        with self.assertRaises(RuntimeError):self.publish()

    def test_corrupt_unrelated_blob_refuses_without_backup_or_manifest_write(self):
        row=json.loads(self.old)['files'][-1];(self.live/'blobs'/row['sha256']).write_bytes(b'corrupt')
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)
        self.assertEqual(list(self.private.glob('tio-before-world-client-*')),[])

    def test_unrelated_client_metadata_and_seed_and_dll_changes_refuse(self):
        for change in ('news','seed','dll'):
            broken=copy.deepcopy(self.payload);value=json.loads(self.new)
            if change=='news':value['metadata']['root']='changed'
            elif change=='seed':value['files'][2]['seed']=False
            else:value['files'][0]['sha256']='0'*64
            broken['after_manifest']=base64.b64encode(json.dumps(value).encode()).decode()
            with self.assertRaises(ValueError):self.publish(broken)
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)

    def test_xml_candidate_tampering_foreign_rows_or_non_contiguous_ids_refuse(self):
        for raw in (self.candidate.replace(b'name="Texas"',b'name="Changed"'),
                    self.candidate.replace(b'id="22"',b'id="23"'),self.candidate+b'<!-- unreviewed -->'):
            broken=copy.deepcopy(self.payload);broken.update(candidate=base64.b64encode(raw).decode(),candidate_sha256=tool.sha(raw),candidate_bytes=len(raw))
            broken['after_manifest']=base64.b64encode(tool.new_manifest(self.old,raw)).decode()
            broken['world_client_release']['candidate_sha256']=tool.sha(raw)
            with self.assertRaises(ValueError):self.publish(broken)
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)

    def test_runtime_policy_mismatch_and_player_data_path_refuse(self):
        broken=copy.deepcopy(self.payload);broken['server_runtime']['config/world_completion.json']='0'*64
        with self.assertRaises(RuntimeError):self.publish(broken)
        broken=copy.deepcopy(self.payload);broken['server_runtime']['../var/lib/tio-server/reservation.sqlite3']='0'*64
        with self.assertRaises(ValueError):self.publish(broken)
        broken=copy.deepcopy(self.payload);broken['world_client_release']['runtime_sha256']='0'*64
        with self.assertRaises(ValueError):self.publish(broken)

    def test_competing_manifest_during_backup_preserved(self):
        value=json.loads(self.old);value['news']='another reviewed release';competing=json.dumps(value).encode()
        original=self.scope['backup']
        def changed(*args):
            result=original(*args);(self.live/'manifest.json').write_bytes(competing);return result
        self.scope['backup']=changed
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),competing)

    def test_changed_service_after_commit_rolls_back_own_manifest(self):
        original=self.scope['atomic']
        def changed(raw,path):
            original(raw,path)
            if path==self.live/'manifest.json' and raw==self.new:self.scope['service']=lambda:dict(ActiveState='active',MainPID='456',NRestarts='1')
        self.scope['atomic']=changed
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)
        saved=next(self.private.glob('tio-before-world-client-*'))
        self.assertTrue(json.loads((saved/'rollback.json').read_text())['manifest_restored'])

    def test_competing_manifest_after_commit_not_overwritten_by_rollback(self):
        value=json.loads(self.new);value['news']='newer concurrent metadata';competing=json.dumps(value).encode()
        original=self.scope['atomic']
        def changed(raw,path):
            original(raw,path)
            if path==self.live/'manifest.json' and raw==self.new:path.write_bytes(competing)
        self.scope['atomic']=changed
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),competing)

    def test_final_audit_failure_rolls_back_and_does_not_save_completed_journal(self):
        original=self.scope['private_json']
        def failed(path,value):
            if path.name=='publication.json':raise OSError('injected audit failure')
            return original(path,value)
        self.scope['private_json']=failed
        with self.assertRaises(OSError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)
        self.assertFalse((self.private/('tio-world-client-'+'1'*32+'.json')).exists())

    def test_publication_requires_exact_validation_deployment_and_hosted_reports(self):
        folder=self.root/'review';folder.mkdir()
        release={'world_client_release':self.release}
        for name in ('validation.json','deployment.json','hosted-world.json'):
            (folder/name).write_text(json.dumps(dict(passed=True,world_client_release=self.release,runtime_files=self.runtime_hashes)))
        self.assertEqual(tool.publication_gate(folder,release),self.runtime_hashes)
        value=json.loads((folder/'hosted-world.json').read_bytes());value['world_client_release']['candidate_sha256']='0'*64
        (folder/'hosted-world.json').write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'hosted-world'):tool.publication_gate(folder,release)
        (folder/'hosted-world.json').write_text(json.dumps(dict(passed=True,world_client_release=self.release)))
        (folder/'deployment.json').write_text(json.dumps(dict(passed=True,world_client_release=self.release,files=self.runtime_hashes)))
        with self.assertRaisesRegex(ValueError,'runtime_files or hashes'):tool.publication_gate(folder,release)

    def test_prepare_uses_exact_https_bytes_and_preserves_observation_candidate(self):
        project=self.root/'project';folder=project/'reports/gameplay-completion/stage8-world'
        fixture_proof=dict(passed=True,status='PASS',candidate_xml_sha256=tool.sha(self.candidate),candidate_dll_sha256=tool.DLL_SHA,
            loader_cases=[{}]*22,town_cases=[{}]*44,shared_config={'passed':True},float_mapping={'passed':True,'order':['influence','experience','profit']})
        observation=json.dumps({'manifest':json.loads(self.old)}).encode()
        catalog=copy.deepcopy(self.catalog);catalog['observation_sha256']=tool.sha(observation)
        files={'config/world_completion.json':self.policy,
               'reports/gameplay-completion/stage8-world/client/source/zones.xml':self.source,
               'reports/gameplay-completion/stage8-world/client/candidate/zones.xml':self.candidate,
               'reports/gameplay-completion/stage8-world/runtime/evidence/zones_diagnostic.xml':self.runtime,
               'reports/gameplay-completion/stage8-world/source/zones_diagnostic.xml':(self.folder/'source/zones_diagnostic.xml').read_bytes(),
               'reports/gameplay-completion/stage8-world/client/source/observation.json':observation,
               'reports/gameplay-completion/stage8-world/client/native-proof.json':json.dumps(fixture_proof).encode(),
               'reports/gameplay-completion/stage8-world/catalog.json':json.dumps(catalog).encode()}
        for name,raw in files.items():
            path=project/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        with patch.object(tool,'ROOT',project),patch.object(tool,'FOLDER',folder),patch.object(tool,'SOURCE_FILES',()), \
                patch.object(tool,'fetch',side_effect=[self.old,self.source,self.old]) as fetch,patch.object(tool,'remote') as remote:
            result=tool.prepare(folder)
            self.assertEqual((folder/'client/previous-manifest.json').read_bytes(),self.old)
            self.assertEqual((folder/'client/manifest.json').read_bytes(),self.new)
            self.assertFalse(result['published']);self.assertTrue(result['trusted_https'])
            self.assertEqual(tool.prepare(folder),result);self.assertEqual(fetch.call_count,3);remote.assert_not_called()
            self.assertEqual((folder/'client/source/observation.json').read_bytes(),observation)
            self.assertEqual((folder/'client/candidate/zones.xml').read_bytes(),self.candidate)


if __name__=='__main__':unittest.main()
