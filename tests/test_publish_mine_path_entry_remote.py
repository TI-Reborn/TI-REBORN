import base64
import copy
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

from tools import publish_mine_path_entry_remote as tool


class MinePathEntryPublicationSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old=tool.BASELINE.read_bytes()
        cls.source=tool.BASELINE.parent.joinpath('silver.dll').read_bytes()
        cls.silver=cls.source
        cls.ti=tool.BASELINE.parent.joinpath('ti.exe').read_bytes()
        cls.candidate=(tool.REPORT_ROOT/'client/silver.dll').read_bytes()
        cls.review=json.loads((tool.REPORT_ROOT/'client/native-review.json').read_bytes())['native_review']
        cls.package=dict(schema=1,previous_version=tool.PREVIOUS_VERSION,version=tool.VERSION,baseline_manifest_sha256=tool.MANIFEST_SHA,selection=dict(fix='completed-scene-native-path-cache'),native_review=cls.review,files=[dict(path='silver.dll',source='silver.dll',sha256=tool.sha(cls.candidate),size=len(cls.candidate),kind='native')])
        cls.package_raw=(json.dumps(cls.package,indent=2)+'\n').encode()
        cls.new_obj=json.loads(cls.old);cls.new_obj['version']=tool.VERSION
        next(row for row in cls.new_obj['files'] if row['path']=='silver.dll').update(sha256=tool.sha(cls.candidate),size=len(cls.candidate))
        cls.new=(json.dumps(cls.new_obj,ensure_ascii=False,indent=2)+'\n').encode()

    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.live=self.root/'live';self.private=self.root/'private';self.game=self.root/'game'
        for path in (self.live/'blobs',self.private,self.game):path.mkdir(parents=True)
        (self.live/'manifest.json').write_bytes(self.old)
        for raw in (self.source,self.silver,self.ti):(self.live/'blobs'/tool.sha(raw)).write_bytes(raw)
        self.db=self.root/'reservation.sqlite3'
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript('CREATE TABLE accounts(login TEXT,salt TEXT,digest TEXT,iterations INTEGER);CREATE TABLE battle_checkpoints(id INTEGER);CREATE TABLE battle_settlement_jobs(id INTEGER);')
            db.executemany('INSERT INTO accounts VALUES(?,?,?,?)',[(f'account-{i}','salt','digest',1) for i in range(202)]);db.commit()
        patch.dict(sys.modules,fcntl=SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *args:None)).start()
        patch.object(os,'O_NOFOLLOW',0,create=True).start();patch.object(os,'fsync',lambda fd:None).start();self.addCleanup(patch.stopall)
        self.scope={};exec(compile(tool.REMOTE,'battle-icon-centering-test','exec'),self.scope)
        self.guards=dict(services=dict(game=dict(MainPID='111',ActiveState='active'),api=dict(MainPID='222',ActiveState='active')),configuration=dict(config='fixed'),launchers=dict(launcher='fixed'),game_code=dict(code='fixed'))
        self.events=[]
        self.scope.update(LIVE=self.live,PRIVATE=self.private,GAME=self.game,DB=self.db,guards=lambda:copy.deepcopy(self.guards),sync=lambda path:self.events.append('sync-'+path.name),state=self.state,private_json=self.private_json,atomic=self.atomic,immutable=self.immutable)
        self.payload=dict(action='apply',package_blob=base64.b64encode(self.package_raw).decode(),package_sha256=tool.sha(self.package_raw),updates={'silver.dll':dict(sha256=tool.sha(self.candidate),size=len(self.candidate),kind='native',blob=base64.b64encode(self.candidate).decode())},before_manifest=base64.b64encode(self.old).decode(),after_manifest=base64.b64encode(self.new).decode(),after_manifest_sha256=tool.sha(self.new),expected_guards=dict(state=copy.deepcopy(self.guards),inspected_utc=datetime.now(timezone.utc).isoformat(),account_credentials_sha256=self.scope['database'](self.db)[1]['account_credentials_sha256']))

    def state(self,path):
        self.scope['regular'](path);raw=path.read_bytes()
        return dict(sha256=tool.sha(raw),size=len(raw),uid=0,gid=0,mode=0o644)

    def private_json(self,path,value):
        self.events.append(path.name)
        with path.open('x',encoding='utf-8') as out:json.dump(value,out)

    def atomic(self,raw,path,expected=None):
        if expected is not None and path.read_bytes()!=expected:raise RuntimeError('Atomic publication target changed')
        pending=path.parent/'pending.json';pending.write_bytes(raw);os.replace(pending,path)
        self.events.append('manifest-new' if raw==self.new else 'manifest-old')

    def immutable(self,raw,path):
        self.events.append('blob')
        if path.exists():
            if path.read_bytes()!=raw:raise RuntimeError('Immutable blob differs')
        else:
            with path.open('xb') as out:out.write(raw)

    def publish(self,payload=None):return self.scope['execute'](self.payload if payload is None else payload)

    def test_exact_candidate_and_transition_preserve_every_other_record(self):
        tool.package_identity(self.package_raw,tool.sha(self.package_raw))
        result=tool.blob_identity(self.package['files'][0],self.candidate,self.source,self.review)
        self.assertTrue(result['all_undeclared_native_bytes_preserved'])
        self.assertEqual(result['appended_bytes'],512)
        result=tool.manifest_transition(self.old,self.new,self.package)
        self.assertEqual(result['changed'],['silver.dll']);self.assertEqual(result['added'],[])
        self.assertEqual(result['preserved_records'],6543)
        before,after=json.loads(self.old),json.loads(self.new)
        for prior,current in zip(before['files'],after['files']):
            if prior['path']!='silver.dll':self.assertEqual(prior,current)

    def test_other_resources_old_versions_and_extra_files_are_refused(self):
        for name,kind in (('ti.exe','native'),('base/config.cfg','native'),('base/ui-hd/battle-controls/hd4-bui-glyphs.png','icon_image'),('../silver.dll','native')):
            package=copy.deepcopy(self.package);package['files'][0].update(path=name,kind=kind);raw=json.dumps(package).encode()
            with self.assertRaises(ValueError):tool.package_identity(raw,tool.sha(raw))
        for package in (dict(self.package,native_review=None),dict(self.package,files=self.package['files']*2),dict(self.package,previous_version='2026.10.10.2')):
            raw=json.dumps(package).encode()
            with self.assertRaises(ValueError):tool.package_identity(raw,tool.sha(raw))
        bad=copy.deepcopy(self.new_obj);next(row for row in bad['files'] if row['path']=='ti.exe')['sha256']='0'*64
        with self.assertRaises(ValueError):tool.manifest_transition(self.old,json.dumps(bad).encode(),self.package)

    def test_undeclared_bytes_reviewed_append_and_wrong_native_are_refused(self):
        for at in (2000,len(self.source)+20):
            bad=bytearray(self.candidate);bad[at]^=1
            item=dict(self.package['files'][0],sha256=tool.sha(bad))
            with self.assertRaisesRegex(ValueError,'exact validated'):tool.blob_identity(item,bytes(bad),self.source,self.review)
            with self.assertRaises(ValueError):tool.native_preserved(self.source,bytes(bad),self.review)
        bad=copy.deepcopy(self.review);bad['appended_size']+=512
        with self.assertRaises(ValueError):tool.native_review_identity(bad)
        bad=bytearray(self.source);bad[2000]^=1
        with self.assertRaisesRegex(ValueError,'source required'):tool.blob_identity(self.package['files'][0],self.candidate,bytes(bad),self.review)

    def test_inspect_is_read_only_and_changed_credentials_refuse_before_writes(self):
        payload=copy.deepcopy(self.payload);payload.update(action='inspect',expected_guards=None)
        result=self.publish(payload);self.assertEqual(result['remote_mutations'],0);self.assertEqual(self.events,[])
        with closing(sqlite3.connect(self.db)) as db:db.execute("UPDATE accounts SET digest='changed' WHERE login='account-0'");db.commit()
        with self.assertRaisesRegex(RuntimeError,'credentials changed'):self.publish()
        self.assertEqual(self.events,[]);self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)

    def test_backup_and_immutable_blob_precede_atomic_manifest(self):
        result=self.publish();saved=Path(result['backup'])
        self.assertEqual((saved/'previous-manifest.json').read_bytes(),self.old)
        self.assertEqual((saved/'previous-blobs'/tool.sha(self.source)).read_bytes(),self.source)
        with closing(sqlite3.connect(saved/'reservation.sqlite3')) as db:self.assertEqual(db.execute('SELECT count(*) FROM accounts').fetchone()[0],202)
        for name in ('previous-code.tar.gz','previous-config.tar.gz','backup-manifest.json'):self.assertTrue((saved/name).is_file())
        self.assertLess(self.events.index('backup-manifest.json'),self.events.index('blob'));self.assertLess(self.events.index('blob'),self.events.index('manifest-new'))
        self.assertEqual(self.events.count('manifest-new'),1)
        self.assertTrue(result['ti_preserved']);self.assertFalse(result['server_restarted']);self.assertFalse(result['database_written']);self.assertFalse(result['local_player_data_uploaded'])
        self.assertEqual((self.live/'blobs'/tool.TI_SHA).read_bytes(),self.ti)

    def test_corrupt_prior_blob_and_stale_host_refuse_before_writes(self):
        (self.live/'blobs'/tool.SILVER_SHA).write_bytes(b'corrupt')
        with self.assertRaisesRegex(RuntimeError,'prior reviewed'):self.publish()
        self.assertEqual(self.events,[])
        (self.live/'blobs'/tool.SILVER_SHA).write_bytes(self.source)
        (self.live/'manifest.json').write_bytes(self.new)
        with self.assertRaisesRegex(RuntimeError,'baseline changed'):self.publish()
        self.assertEqual(self.events,[])

    def test_postcommit_failure_rolls_back_manifest_preserving_database(self):
        original=self.scope['atomic']
        def fail_after_commit(raw,path,expected=None):
            original(raw,path,expected)
            if raw==self.new:self.guards['services']['game']['MainPID']='changed'
        self.scope['atomic']=fail_after_commit
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(db.execute('SELECT count(*) FROM accounts').fetchone()[0],202)

    def test_concurrent_release_after_commit_is_not_overwritten(self):
        other=json.dumps(dict(self.new_obj,news='concurrent release')).encode();original=self.scope['atomic']
        def change(raw,path,expected=None):
            original(raw,path,expected)
            if raw==self.new:path.write_bytes(other)
        self.scope['atomic']=change
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),other)

    def test_https_verification_checks_candidate_and_unchanged_ti(self):
        contents={'manifest.json':self.new,'blobs/'+tool.sha(self.candidate):self.candidate,'blobs/'+tool.TI_SHA:self.ti}
        with patch.object(tool,'fetch',side_effect=lambda path,maximum:contents[path]):
            result=tool.verify_https(self.payload);self.assertTrue(result['passed']);self.assertTrue(result['ti_preserved']);self.assertFalse(result['graphical_validation'])
            contents['blobs/'+tool.TI_SHA]=b'corrupt'
            with self.assertRaisesRegex(ValueError,'TI'):tool.verify_https(self.payload)


if __name__=='__main__':unittest.main()
