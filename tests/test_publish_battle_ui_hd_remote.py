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

from tools import publish_battle_ui_hd_remote as tool


def png():
    def chunk(kind, raw):
        return struct.pack('>I', len(raw)) + kind + raw + struct.pack('>I', zlib.crc32(kind + raw) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff\xff')) + chunk(b'IEND', b'')

def review_for(source,candidate):
    changes=[];index=0
    while index<len(source):
        if source[index]==candidate[index]:index+=1;continue
        end=index+1
        while end<len(source) and source[end]!=candidate[end]:end+=1
        changes.append(dict(offset=index,size=end-index,source_sha256=tool.sha(source[index:end]),candidate_sha256=tool.sha(candidate[index:end]),purpose='Declared synthetic structure test span'))
        index=end
    return dict(changes=changes,appended_size=len(candidate)-len(source),appended_sha256=tool.sha(candidate[len(source):]))


class BattleUIPublicationSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = tool.BASELINE.read_bytes()
        cls.source = tool.BASELINE.parent.joinpath('silver.dll').read_bytes()
        cls.ti = tool.BASELINE.parent.joinpath('ti.exe').read_bytes()
        candidate = bytearray(cls.source)
        candidate[0x20] ^= 1
        cls.candidate = bytes(candidate)
        cls.review = dict(changes=[dict(offset=0x20, size=1, source_sha256=tool.sha(cls.source[0x20:0x21]), candidate_sha256=tool.sha(cls.candidate[0x20:0x21]), purpose='Synthetic bounded validation range')], appended_size=0, appended_sha256=tool.sha(b''))
        cls.package = dict(schema=1, previous_version=tool.PREVIOUS_VERSION, version=tool.VERSION, baseline_manifest_sha256=tool.MANIFEST_SHA, selection=dict(fix='battle-ui-quality-and-tooltip'), native_review=cls.review, files=[dict(path='silver.dll', source='silver.dll', sha256=tool.sha(cls.candidate), size=len(cls.candidate), kind='native'), dict(path='base/ui-hd/battle-test.png', source='image.png', sha256=tool.sha(png()), size=len(png()), kind='icon_image')])
        cls.package_raw = (json.dumps(cls.package, indent=2) + '\n').encode()
        cls.new_obj = json.loads(cls.old)
        cls.new_obj['version'] = tool.VERSION
        next(x for x in cls.new_obj['files'] if x['path']=='silver.dll').update(sha256=tool.sha(cls.candidate), size=len(cls.candidate))
        cls.new_obj['files'].append(dict(path='base/ui-hd/battle-test.png', size=len(png()), sha256=tool.sha(png()), seed=False))
        cls.new = (json.dumps(cls.new_obj, ensure_ascii=False, indent=2) + '\n').encode()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.live = self.root/'live'; self.private = self.root/'private'; self.game = self.root/'game'
        for path in (self.live/'blobs', self.private, self.game): path.mkdir(parents=True)
        (self.live/'manifest.json').write_bytes(self.old)
        for raw in (self.source, self.ti): (self.live/'blobs'/tool.sha(raw)).write_bytes(raw)
        self.db = self.root/'reservation.sqlite3'
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript('CREATE TABLE accounts(login TEXT,salt TEXT,digest TEXT,iterations INTEGER);CREATE TABLE battle_checkpoints(id INTEGER);CREATE TABLE battle_settlement_jobs(id INTEGER);')
            db.executemany('INSERT INTO accounts VALUES(?,?,?,?)', [(f'account-{i}', 'salt', 'digest', 1) for i in range(202)])
            db.commit()
        self.scope = {}
        patch.dict(sys.modules, fcntl=SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *args:None)).start()
        patch.object(os, 'O_NOFOLLOW', 0, create=True).start()
        patch.object(os, 'fsync', lambda fd:None).start()
        self.addCleanup(patch.stopall)
        exec(compile(tool.REMOTE, 'scoped-battle-ui-remote-test', 'exec'), self.scope)
        self.guards = dict(services=dict(game=dict(MainPID='111',ActiveState='active'),api=dict(MainPID='222',ActiveState='active')),configuration=dict(config='fixed'),launchers=dict(launcher='fixed'),game_code=dict(code='fixed'))
        self.events=[]
        self.scope.update(LIVE=self.live, PRIVATE=self.private, GAME=self.game, DB=self.db, guards=lambda:copy.deepcopy(self.guards), sync=lambda path:self.events.append('sync-'+path.name), state=self.state, private_json=self.private_json, atomic=self.atomic, immutable=self.immutable)
        self.payload=dict(action='apply',package_blob=base64.b64encode(self.package_raw).decode(),package_sha256=tool.sha(self.package_raw),updates={x['path']:dict(sha256=x['sha256'],size=x['size'],kind=x['kind'],blob=base64.b64encode(self.candidate if x['kind']=='native' else png()).decode()) for x in self.package['files']},before_manifest=base64.b64encode(self.old).decode(),after_manifest=base64.b64encode(self.new).decode(),after_manifest_sha256=tool.sha(self.new),expected_guards=dict(state=copy.deepcopy(self.guards),inspected_utc=datetime.now(timezone.utc).isoformat(),account_credentials_sha256=self.scope['database'](self.db)[1]['account_credentials_sha256']))

    def state(self, path):
        self.scope['regular'](path)
        raw=path.read_bytes()
        return dict(sha256=tool.sha(raw),size=len(raw),uid=0,gid=0,mode=0o644)

    def private_json(self,path,value):
        self.events.append(path.name)
        with path.open('x',encoding='utf-8') as out: json.dump(value,out)

    def atomic(self,raw,path,expected=None):
        if expected is not None and path.read_bytes()!=expected:raise RuntimeError('Publication target changed before atomic replace')
        pending=path.parent/'pending.json';pending.write_bytes(raw);os.replace(pending,path)
        self.events.append('manifest-new' if raw==self.new else 'manifest-old')

    def immutable(self,raw,path):
        self.events.append('blob')
        if path.exists():
            if path.read_bytes()!=raw:raise RuntimeError('Existing immutable blob differs')
        else:
            with path.open('xb') as out:out.write(raw)

    def publish(self,payload=None):return self.scope['execute'](self.payload if payload is None else payload)

    def test_package_and_manifest_preserve_every_other_record(self):
        tool.package_identity(self.package_raw,tool.sha(self.package_raw))
        tool.blob_identity(self.package['files'][0],self.candidate,self.source,self.review)
        result=tool.manifest_transition(self.old,self.new,self.package)
        self.assertEqual(result['changed'],['silver.dll']);self.assertEqual(result['added'],['base/ui-hd/battle-test.png'])
        a,b=json.loads(self.old),json.loads(self.new)
        self.assertEqual(a['news'],b['news'])
        for prior,after in zip(a['files'],b['files']):
            if prior['path']!='silver.dll':self.assertEqual(prior,after)

    def test_unreviewed_native_bytes_and_changed_authentication_refuse(self):
        bad=bytearray(self.candidate);bad[0x21]^=1
        with self.assertRaises(ValueError):tool.native_preserved(self.source,bytes(bad),self.review)
        review=copy.deepcopy(self.review);review['changes'][0]['candidate_sha256']='0'*64
        with self.assertRaises(ValueError):tool.native_preserved(self.source,self.candidate,review)
        marker=tool.pe_at(self.source,tool.AUTH_SPANS[0][0]-0x400000,tool.AUTH_SPANS[0][1])
        at=self.source.index(marker);bad=bytearray(self.source);bad[at]^=1
        review=dict(changes=[dict(offset=at,size=1,source_sha256=tool.sha(self.source[at:at+1]),candidate_sha256=tool.sha(bad[at:at+1]),purpose='Must still refuse an authentication edit')],appended_size=0,appended_sha256=tool.sha(b''))
        with self.assertRaisesRegex(ValueError,'authentication'):tool.native_preserved(self.source,bytes(bad),review)

    def test_unapproved_resources_metadata_paths_png_and_manifest_refuse(self):
        for path in ('ti.exe','base/config.cfg','base/ui-hd/fonts/atlas.png','../evil.png','base/ui-hd//evil.png','base/ui-hd/CON.png'):
            package=copy.deepcopy(self.package);package['files'][1]['path']=path;raw=json.dumps(package).encode()
            with self.assertRaises(ValueError):tool.package_identity(raw,tool.sha(raw))
        bad=bytearray(png());bad[-5]^=1;item=dict(self.package['files'][1],sha256=tool.sha(bad))
        with self.assertRaises(ValueError):tool.blob_identity(item,bytes(bad))
        bad=copy.deepcopy(self.new_obj);bad['files'][0]['seed']=not bad['files'][0]['seed']
        with self.assertRaises(ValueError):tool.manifest_transition(self.old,json.dumps(bad).encode(),self.package)

    def test_declared_invalid_pe_headers_and_unmapped_append_are_refused(self):
        layout=tool.pe_layout(self.source);optional=layout['optional'];sections=layout['sections'];last=sections[-1]
        bad_cases=[]
        for at,value in ((optional+56,0),(optional+16,0),(sections[0]['at']+20,sections[1]['offset']),(last['at']+20,last['offset']-0x200),(last['at']+36,0),(layout['header']+6,14)):
            raw=bytearray(self.source)
            if at==layout['header']+6:struct.pack_into('<H',raw,at,value)
            else:struct.pack_into('<I',raw,at,value)
            bad_cases.append(bytes(raw))
        bad_cases.append(self.candidate+b'UNMAPPED!')
        for candidate in bad_cases:
            with self.subTest(candidate_sha=tool.sha(candidate)):
                with self.assertRaises(ValueError):tool.native_preserved(self.source,candidate,review_for(self.source,candidate))

    def test_final_section_reviewed_aligned_append_is_mapped(self):
        layout=tool.pe_layout(self.source);last=layout['sections'][-1];raw=bytearray(self.source)
        append=b'\0'*0x1000
        struct.pack_into('<I',raw,last['at']+8,last['virtual_size']+len(append))
        struct.pack_into('<I',raw,last['at']+16,last['raw_size']+len(append))
        struct.pack_into('<I',raw,layout['optional']+56,layout['image_size']+len(append))
        raw.extend(append);candidate=bytes(raw)
        result=tool.native_preserved(self.source,candidate,review_for(self.source,candidate))
        self.assertTrue(result['pe_structure']['final_section_append_mapped']);self.assertEqual(result['pe_structure']['sections'],13)

    def test_inspect_is_read_only_and_evidence_is_fresh(self):
        payload=copy.deepcopy(self.payload);payload['action']='inspect';payload['expected_guards']=None
        result=self.publish(payload)
        self.assertEqual(result['remote_mutations'],0);self.assertEqual(self.events,[]);self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)
        payload=copy.deepcopy(self.payload);payload['expected_guards']['inspected_utc']='2020-01-01T00:00:00+00:00'
        with self.assertRaises(RuntimeError):self.publish(payload)
        self.assertEqual(self.events,[])

    def test_publication_online_backup_precedes_all_blobs_and_single_manifest(self):
        result=self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.new)
        saved=Path(result['backup']);self.assertEqual((saved/'previous-manifest.json').read_bytes(),self.old)
        self.assertEqual((saved/'previous-blobs'/tool.SILVER_SHA).read_bytes(),self.source)
        with closing(sqlite3.connect(saved/'reservation.sqlite3')) as db:self.assertEqual(db.execute('SELECT count(*) FROM accounts').fetchone()[0],202)
        self.assertLess(self.events.index('backup-manifest.json'),self.events.index('blob'))
        self.assertLess(self.events.index('backup-manifest.json'),self.events.index('sync-private'))
        self.assertLess(self.events.index('sync-private'),self.events.index('blob'))
        self.assertLess(max(i for i,event in enumerate(self.events) if event=='blob'),self.events.index('manifest-new'))
        self.assertEqual(self.events.count('manifest-new'),1)
        self.assertFalse(result['server_restarted']);self.assertFalse(result['database_written']);self.assertFalse(result['local_player_data_uploaded'])
        with self.assertRaises(RuntimeError):self.publish()

    def test_credentials_change_between_inspection_and_apply_refuses_before_writes(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE accounts SET digest='changed' WHERE login='account-0'");db.commit()
        with self.assertRaisesRegex(RuntimeError,'credentials changed'):self.publish()
        self.assertEqual(self.events,[]);self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)
        self.assertEqual(list(self.private.iterdir()),[])

    def test_active_gameplay_and_new_accounts_are_preserved(self):
        original=self.scope['immutable'];updated=False
        def mutate(raw,path):
            nonlocal updated
            original(raw,path)
            if not updated:
                with closing(sqlite3.connect(self.db)) as db:
                    db.execute('INSERT INTO battle_checkpoints VALUES(1)');db.execute("INSERT INTO accounts VALUES('new','salt','digest',1)")
                    db.commit()
                updated=True
        self.scope['immutable']=mutate
        result=self.publish()
        self.assertEqual(result['accounts_after'],203);self.assertEqual(result['health']['checkpoints'],1)
        self.assertTrue(result['account_identities_and_credentials_preserved']);self.assertTrue(result['database_gameplay_changes_allowed'])
        self.assertNotEqual(result['account_credentials_sha256_before'],result['account_credentials_sha256_after'])

    def test_guard_change_after_commit_restores_only_our_manifest(self):
        original=self.scope['atomic']
        def mutate(raw,path,expected=None):
            original(raw,path,expected)
            if raw==self.new:self.guards['services']['game']['MainPID']='changed'
        self.scope['atomic']=mutate
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(db.execute('SELECT count(*) FROM accounts').fetchone()[0],202)

    def test_concurrent_manifest_after_commit_is_never_overwritten(self):
        other=json.dumps(dict(self.new_obj,news='concurrent release')).encode();original=self.scope['atomic']
        def mutate(raw,path,expected=None):
            original(raw,path,expected)
            if raw==self.new:path.write_bytes(other)
        self.scope['atomic']=mutate
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),other)

    def test_private_receipt_failure_rolls_back_manifest(self):
        original=self.scope['private_json']
        def fail(path,value):
            if path.name=='publication.json':raise OSError('injected receipt failure')
            original(path,value)
        self.scope['private_json']=fail
        with self.assertRaises(OSError):self.publish()
        self.assertEqual((self.live/'manifest.json').read_bytes(),self.old)

    def test_https_verification_recovers_unknown_apply_outcome_and_detects_tampering(self):
        contents={'manifest.json':self.new,'blobs/'+tool.sha(self.candidate):self.candidate,'blobs/'+tool.sha(png()):png(),'blobs/'+tool.TI_SHA:self.ti}
        with patch.object(tool,'fetch',side_effect=lambda path,maximum:contents[path]):
            result=tool.verify_https(self.payload)
            self.assertTrue(result['passed']);self.assertFalse(result['graphical_validation'])
            contents['manifest.json']=self.old
            with self.assertRaises(ValueError):tool.verify_https(self.payload)


if __name__=='__main__':unittest.main()
