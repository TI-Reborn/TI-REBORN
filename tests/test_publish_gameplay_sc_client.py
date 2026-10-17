import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import publish_gameplay_sc_client as tool
from deploy.client_sc_auction import patch as client_patch, patch_plan

BASE_CLIENT=tool.ROOT/'reports/gameplay-completion/stage3-items/client/candidate/silver.dll'


class SCPublishSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=BASE_CLIENT.read_bytes();cls.after=client_patch(cls.before)
        cls.plan=patch_plan(cls.before,cls.after)

    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)
        self.live=self.root/'updates';self.downloads=self.root/'downloads';self.game=self.root/'game';self.private=self.root/'private'
        for p in (self.live/'blobs',self.downloads,self.game,self.private):p.mkdir(parents=True)
        for name in ('TIO-Launcher.exe','TIO-Launcher-0.1.4.exe'):(self.downloads/name).write_bytes(b'unchanged launcher')
        self.config=self.root/'server.toml';self.config.write_bytes(b'untouched configuration')
        rows=[]
        for name,raw,seed in (('silver.dll',self.before,False),('base/config.cfg',b'client seed',True),
                              ('base/shared config/contracts.xml',b'unchanged parallel contracts',False)):
            digest=tool.sha(raw);(self.live/'blobs'/digest).write_bytes(raw)
            rows.append(dict(path=name,size=len(raw),sha256=digest,seed=seed))
        self.old=(json.dumps(dict(schema=1,version=tool.PREVIOUS_VERSION,news='unchanged news',files=rows))+'\n').encode()
        self.new=tool.new_manifest(self.old);(self.live/'manifest.json').write_bytes(self.old)
        abi={}
        for name in ('tio/protocol/sc_auction_view.py','tio/protocol/sc_auction.py'):
            target=self.game/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((tool.ROOT/name).read_bytes());abi[name]=tool.sha(target.read_bytes())
        self.payload=dict(operation='1'*32,before_manifest=base64.b64encode(self.old).decode(),after_manifest=base64.b64encode(self.new).decode(),
            candidate=base64.b64encode(self.after).decode(),plan=copy.deepcopy(self.plan),server_abi=abi)
        self.scope={};exec(compile(tool.REMOTE,'reviewed-sc-remote','exec'),self.scope)
        self.scope.update(LIVE=self.live,DOWNLOADS=self.downloads,GAME=self.game,PRIVATE=self.private,CONFIGS=(self.config,),
            service=lambda:dict(ActiveState='active',MainPID='123',NRestarts='0'))
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules,fcntl=SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *args:None)).start()

    def publish(self,payload=None):return self.scope['publish'](self.payload if payload is None else payload)

    def test_prepared_manifest_preserves_news_seeds_and_parallel_contracts(self):
        self.assertEqual(tool.transition(self.old,self.new),['silver.dll'])
        a,b=json.loads(self.old),json.loads(self.new)
        self.assertEqual(a['news'],b['news']);self.assertEqual(a['files'][1:],b['files'][1:])
        self.assertEqual(tool.sha(self.after),tool.CANDIDATE_SHA);self.assertEqual(len(self.after),tool.CANDIDATE_BYTES)
        for name in ('../evil','base\\evil','C:/evil','base/../evil','base//evil','base/evil\0'):
            broken=copy.deepcopy(a);broken['files'][1]['path']=name;raw=json.dumps(broken).encode()
            with self.assertRaises(ValueError):tool.checked_manifest(raw,version=tool.PREVIOUS_VERSION)
            with self.assertRaises(ValueError):self.scope['catalogue'](raw,tool.PREVIOUS_VERSION)

    def test_existing_empty_client_files_remain_valid_and_preserved(self):
        raw=(tool.ROOT/'reports/gameplay-completion/stage4-mines/client/manifest.json').read_bytes()
        before=tool.checked_manifest(raw,version=tool.PREVIOUS_VERSION)
        self.assertTrue(any(row['size']==0 for row in before['files']))
        self.assertEqual(tool.transition(raw,tool.new_manifest(raw)),['silver.dll'])
        self.assertEqual(self.scope['catalogue'](raw,tool.PREVIOUS_VERSION),before)

    def test_complete_publication_backs_up_files_without_database_or_service_mutation(self):
        before_guards=self.scope['guards']();result=self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.new)
        self.assertEqual(self.scope['guards'](),before_guards)
        saved=Path(result['backup'])
        self.assertEqual((saved/'manifest.json').read_bytes(),self.old);self.assertEqual((saved/'silver.dll').read_bytes(),self.before)
        self.assertEqual((saved/'TIO-Launcher.exe').read_bytes(),b'unchanged launcher')
        self.assertTrue((saved/'previous-code-config.tar.gz').is_file())
        self.assertFalse(result['database_opened']);self.assertFalse(result['server_restarted']);self.assertFalse(result['local_player_data_uploaded'])
        self.assertTrue(result['other_client_files_preserved']);self.assertEqual(result['blob_coverage']['verified_records'],3)
        self.assertNotIn('sqlite3',tool.REMOTE);self.assertNotIn('psql',tool.REMOTE)

    def test_completed_publication_recovers_same_operation_without_second_backup(self):
        first=self.publish();second=self.publish()
        self.assertTrue(second['recovered_completed_publication']);self.assertEqual(first['backup'],second['backup'])
        self.assertEqual(len(list(self.private.glob('tio-before-sc-client-*'))),1)

    def test_corrupt_other_blob_refuses_before_manifest_write(self):
        row=json.loads(self.old)['files'][2];(self.live/'blobs'/row['sha256']).write_bytes(b'corrupt')
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)
        self.assertEqual(list(self.private.glob('tio-before-sc-client-*')),[])

    def test_unrelated_xml_change_and_wrong_server_abi_refuse(self):
        broken=copy.deepcopy(self.payload);manifest=json.loads(self.new);manifest['files'][2]['seed']=True
        broken['after_manifest']=base64.b64encode(json.dumps(manifest).encode()).decode()
        with self.assertRaises(ValueError):self.publish(broken)
        broken=copy.deepcopy(self.payload);broken['server_abi']['tio/protocol/sc_auction_view.py']='0'*64
        with self.assertRaises(RuntimeError):self.publish(broken)
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)

    def test_bounded_plan_and_candidate_tampering_refuse(self):
        broken=copy.deepcopy(self.payload);broken['plan']['changes'].pop()
        with self.assertRaises(ValueError):self.publish(broken)
        broken=copy.deepcopy(self.payload);raw=bytearray(self.after);raw[-1]^=1;broken['candidate']=base64.b64encode(raw).decode()
        with self.assertRaises(ValueError):self.publish(broken)
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)

    def test_competing_manifest_during_backup_is_preserved(self):
        competing=json.loads(self.old);competing['news']='another reviewed release';raw=json.dumps(competing).encode()
        original=self.scope['backup']
        def changed(*args):
            result=original(*args);(self.live/'manifest.json').write_bytes(raw);return result
        self.scope['backup']=changed
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),raw)

    def test_service_change_after_commit_rolls_back_only_our_manifest(self):
        original=self.scope['atomic']
        def changed(raw,path):
            original(raw,path)
            if path==self.live/'manifest.json' and raw==self.new:
                self.scope['service']=lambda:dict(ActiveState='active',MainPID='456',NRestarts='1')
        self.scope['atomic']=changed
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)
        saved=next(self.private.glob('tio-before-sc-client-*'))
        self.assertTrue(json.loads((saved/'rollback.json').read_text())['manifest_restored'])

    def test_concurrent_manifest_after_commit_is_not_overwritten_by_rollback(self):
        other=json.loads(self.new);other['news']='newer concurrent metadata';other_raw=json.dumps(other).encode()
        original=self.scope['atomic']
        def changed(raw,path):
            original(raw,path)
            if path==self.live/'manifest.json' and raw==self.new:path.write_bytes(other_raw)
        self.scope['atomic']=changed
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),other_raw)

    def test_final_private_audit_failure_restores_old_manifest(self):
        original=self.scope['private_json']
        def failed(path,value):
            if path.name=='publication.json':raise OSError('injected audit failure')
            return original(path,value)
        self.scope['private_json']=failed
        with self.assertRaises(OSError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)
        self.assertFalse((self.private/('tio-sc-client-'+'1'*32+'.json')).exists())


if __name__=='__main__':unittest.main()
