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

from tools import publish_battle_icon_centering_remote as tool


def png(width, height):
    def chunk(kind, raw):
        return struct.pack('>I',len(raw))+kind+raw+struct.pack('>I',zlib.crc32(kind+raw)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\0\0\0\0'*width)*height))+chunk(b'IEND',b'')


class BattleIconCenteringPublicationSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old=tool.BASELINE.read_bytes()
        cls.source=tool.BASELINE.parent.joinpath('hd4-bui-glyphs.png').read_bytes()
        cls.silver=tool.BASELINE.parent.joinpath('silver.dll').read_bytes()
        cls.ti=tool.BASELINE.parent.joinpath('ti.exe').read_bytes()
        cls.width,cls.height=struct.unpack_from('>II',cls.source,16)
        cls.candidate=png(cls.width,cls.height)
        cls.package=dict(schema=1,previous_version=tool.PREVIOUS_VERSION,version=tool.VERSION,baseline_manifest_sha256=tool.MANIFEST_SHA,selection=dict(fix='battle-icon-centering'),native_review=None,files=[dict(path=tool.ATLAS_PATH,source='hd4-bui-glyphs.png',sha256=tool.sha(cls.candidate),size=len(cls.candidate),kind='icon_image')])
        cls.package_raw=(json.dumps(cls.package,indent=2)+'\n').encode()
        cls.new_obj=json.loads(cls.old);cls.new_obj['version']=tool.VERSION
        next(row for row in cls.new_obj['files'] if row['path']==tool.ATLAS_PATH).update(sha256=tool.sha(cls.candidate),size=len(cls.candidate))
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
        self.payload=dict(action='apply',package_blob=base64.b64encode(self.package_raw).decode(),package_sha256=tool.sha(self.package_raw),updates={tool.ATLAS_PATH:dict(sha256=tool.sha(self.candidate),size=len(self.candidate),kind='icon_image',blob=base64.b64encode(self.candidate).decode())},before_manifest=base64.b64encode(self.old).decode(),after_manifest=base64.b64encode(self.new).decode(),after_manifest_sha256=tool.sha(self.new),expected_guards=dict(state=copy.deepcopy(self.guards),inspected_utc=datetime.now(timezone.utc).isoformat(),account_credentials_sha256=self.scope['database'](self.db)[1]['account_credentials_sha256']))

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

    def test_asset_only_package_and_manifest_preserve_every_native_and_other_record(self):
        tool.package_identity(self.package_raw,tool.sha(self.package_raw))
        tool.blob_identity(self.package['files'][0],self.candidate,self.source,None)
        scope=tool.manifest_transition(self.old,self.new,self.package)
        self.assertEqual(scope['changed'],[tool.ATLAS_PATH]);self.assertEqual(scope['added'],[]);self.assertEqual(scope['preserved_records'],6543)
        before,after=json.loads(self.old),json.loads(self.new);self.assertEqual(before['news'],after['news'])
        self.assertEqual(len(before['files']),len(after['files']))
        for prior,current in zip(before['files'],after['files']):
            if prior['path']!=tool.ATLAS_PATH:self.assertEqual(prior,current)

    def test_native_other_paths_extra_files_and_non_null_review_are_refused(self):
        for name,kind in (('silver.dll','native'),('ti.exe','native'),('base/config.cfg','icon_image'),('base/ui-hd/battle-controls/hd4-bui-buttons.png','icon_image'),('../hd4-bui-glyphs.png','icon_image')):
            package=copy.deepcopy(self.package);package['files'][0].update(path=name,kind=kind);raw=json.dumps(package).encode()
            with self.assertRaises(ValueError):tool.package_identity(raw,tool.sha(raw))
        for package in (dict(self.package,native_review={}),dict(self.package,files=self.package['files']*2)):
            raw=json.dumps(package).encode()
            with self.assertRaises(ValueError):tool.package_identity(raw,tool.sha(raw))
        bad=copy.deepcopy(self.new_obj);next(row for row in bad['files'] if row['path']=='silver.dll')['sha256']='0'*64
        with self.assertRaises(ValueError):tool.manifest_transition(self.old,json.dumps(bad).encode(),self.package)

    def test_png_dimensions_and_checksum_are_required(self):
        other=png(self.width+1,self.height);item=dict(self.package['files'][0],sha256=tool.sha(other),size=len(other))
        with self.assertRaisesRegex(ValueError,'dimensions'):tool.blob_identity(item,other,self.source,None)
        bad=bytearray(self.candidate);bad[-5]^=1;item=dict(self.package['files'][0],sha256=tool.sha(bad))
        with self.assertRaises(ValueError):tool.blob_identity(item,bytes(bad),self.source,None)

    def test_inspection_is_read_only_and_credentials_must_match_before_writes(self):
        payload=copy.deepcopy(self.payload);payload.update(action='inspect',expected_guards=None)
        result=self.publish(payload);self.assertEqual(result['remote_mutations'],0);self.assertEqual(self.events,[])
        with closing(sqlite3.connect(self.db)) as db:db.execute("UPDATE accounts SET digest='changed' WHERE login='account-0'");db.commit()
        with self.assertRaisesRegex(RuntimeError,'credentials changed'):self.publish()
        self.assertEqual(self.events,[]);self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)

    def test_asset_only_backup_and_blobs_precede_one_atomic_manifest(self):
        result=self.publish();saved=Path(result['backup'])
        self.assertEqual((saved/'previous-manifest.json').read_bytes(),self.old)
        self.assertEqual((saved/'previous-blobs'/tool.sha(self.source)).read_bytes(),self.source)
        self.assertEqual(len(list((saved/'previous-blobs').iterdir())),1)
        with closing(sqlite3.connect(saved/'reservation.sqlite3')) as db:self.assertEqual(db.execute('SELECT count(*) FROM accounts').fetchone()[0],202)
        for name in ('previous-code.tar.gz','previous-config.tar.gz','backup-manifest.json'):self.assertTrue((saved/name).is_file())
        self.assertLess(self.events.index('backup-manifest.json'),self.events.index('sync-private'));self.assertLess(self.events.index('sync-private'),self.events.index('blob'));self.assertLess(self.events.index('blob'),self.events.index('manifest-new'));self.assertEqual(self.events.count('manifest-new'),1)
        self.assertTrue(result['silver_preserved']);self.assertTrue(result['ti_preserved']);self.assertFalse(result['server_restarted']);self.assertFalse(result['database_written']);self.assertFalse(result['local_player_data_uploaded'])
        self.assertEqual((self.live/'blobs'/tool.SILVER_SHA).read_bytes(),self.silver)

    def test_unexpected_native_blob_tampering_refuses_before_any_write(self):
        (self.live/'blobs'/tool.SILVER_SHA).write_bytes(b'corrupt')
        with self.assertRaisesRegex(RuntimeError,'Silver'):self.publish()
        self.assertEqual(self.events,[]);self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)

    def test_concurrent_release_and_postcommit_failure_rollback_do_not_touch_player_data(self):
        original=self.scope['atomic']
        def fail_after_commit(raw,path,expected=None):
            original(raw,path,expected)
            if raw==self.new:self.guards['services']['game']['MainPID']='changed'
        self.scope['atomic']=fail_after_commit
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(db.execute('SELECT count(*) FROM accounts').fetchone()[0],202)

    def test_concurrent_manifest_after_commit_is_not_overwritten(self):
        other=json.dumps(dict(self.new_obj,news='concurrent release')).encode();original=self.scope['atomic']
        def change(raw,path,expected=None):
            original(raw,path,expected)
            if raw==self.new:path.write_bytes(other)
        self.scope['atomic']=change
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),other)

    def test_https_verification_recovers_unknown_outcome_and_checks_unchanged_native(self):
        contents={'manifest.json':self.new,'blobs/'+tool.sha(self.candidate):self.candidate,'blobs/'+tool.SILVER_SHA:self.silver,'blobs/'+tool.TI_SHA:self.ti}
        with patch.object(tool,'fetch',side_effect=lambda path,maximum:contents[path]):
            result=tool.verify_https(self.payload);self.assertTrue(result['passed']);self.assertTrue(result['silver_preserved']);self.assertFalse(result['graphical_validation'])
            contents['blobs/'+tool.SILVER_SHA]=b'corrupt'
            with self.assertRaisesRegex(ValueError,'Silver'):tool.verify_https(self.payload)


if __name__=='__main__':unittest.main()
