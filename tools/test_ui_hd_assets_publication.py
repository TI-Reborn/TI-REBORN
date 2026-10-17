"""Fault-injected multi-resource publication/verification in owned local fixtures.

No SSH/network/client process is used. POSIX ownership/fsync/flock are simulated
on Windows. Synthetic native candidates are explicitly not graphical evidence.
The fixture directories are retained; no pre-existing temporary data is removed.
"""
from __future__ import annotations
import base64
import contextlib
import copy
from datetime import datetime,timezone
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import publish_ui_hd_assets_remote as p
from tools import verify_ui_hd_assets_publication as v


class Guards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real_baseline=p.BASELINE
        cls.old=cls.real_baseline.read_bytes();cls.source=(cls.real_baseline.parent/'silver.dll').read_bytes()
        cls.ti=(cls.real_baseline.parent/'ti.exe').read_bytes()
        cls.folder=Path(tempfile.mkdtemp(prefix='publisher-fixtures-',dir=p.DEPLOYMENT))
        cls.report_patch=patch.object(p,'REPORT_ROOT',cls.folder);cls.report_patch.start()
        cls.package_root=cls.folder/'client/reviewed';cls.package_root.mkdir(parents=True)
        cls.raws={
            'silver.dll':cls.source+b'\0SYNTHETIC-HD-PUBLISHER-GUARD-FIXTURE-NOT-GRAPHICAL\0',
            'base/ui-hd/fonts/pixel13_125.png':cls.png((32,24),(255,255,255,120)),
            'base/ui-hd/fonts/pixel13_125.xml':b'<font width="32" height="24"><glyph code="192"/></font>',
            'base/ui-hd/icons/classic_125.png':cls.png((50,50),(144,120,61,255)),
            'base/ui-hd/licenses/RobotoCondensed-OFL.txt':(ROOT/'reports/ui-hd-assets/fonts/technical-roboto-condensed/OFL.txt').read_bytes(),
        }
        kinds=['native','font_atlas','font_descriptor','icon_image','license']
        cls.package=dict(schema=1,previous_version=p.PREVIOUS_VERSION,version=p.VERSION,baseline_manifest_sha256=p.MANIFEST_SHA,
                         selection=dict(icons='a-classic-hd',font_family='Roboto Condensed'),files=[])
        for (name,raw),kind in zip(cls.raws.items(),kinds):
            source='files/'+name;path=cls.package_root/source;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            cls.package['files'].append(dict(path=name,source=source,sha256=p.sha(raw),size=len(raw),kind=kind))
        cls.package_path=cls.package_root/'package.json'
        cls.package_bytes=(json.dumps(cls.package,indent=2)+'\n').encode();cls.package_path.write_bytes(cls.package_bytes)
        cls.payload=p.make_payload(cls.package_path,p.sha(cls.package_bytes),'inspect',baseline=cls.real_baseline)

    @classmethod
    def tearDownClass(cls):
        cls.report_patch.stop()

    @staticmethod
    def png(size,color):
        out=BytesIO();Image.new('RGBA',size,color).save(out,format='PNG');return out.getvalue()

    def payload_copy(self,apply=False,guards=None):
        result=copy.deepcopy(self.payload)
        if apply:result.update(action='apply',expected_guards=copy.deepcopy(guards))
        return result

    def fixture(self):
        folder=Path(tempfile.mkdtemp(prefix='hosted-',dir=self.folder));live=folder/'updates';private=folder/'private';game=folder/'game'
        for path in (live/'blobs',private,game/'server'):path.mkdir(parents=True)
        (game/'server/source.py').write_bytes(b'unchanged authoritative hosted code\n')
        (live/'manifest.json').write_bytes(self.old)
        (live/'blobs'/p.SILVER_SHA).write_bytes(self.source);(live/'blobs'/p.TI_SHA).write_bytes(self.ti)
        db=folder/'reservation.sqlite3'
        with contextlib.closing(sqlite3.connect(db)) as connection,connection:
            connection.execute('CREATE TABLE accounts(login TEXT PRIMARY KEY,salt BLOB,digest BLOB,iterations INTEGER)')
            connection.executemany('INSERT INTO accounts VALUES(?,?,?,?)',((f'synthetic_{i}',b'salt'+str(i).encode(),b'digest'+str(i).encode(),600000) for i in range(202)))
            connection.execute('CREATE TABLE battle_checkpoints(value BLOB)')
            connection.execute('INSERT INTO battle_checkpoints VALUES(?)',(b'legitimate foreign checkpoint',))
            connection.execute('CREATE TABLE battle_settlement_jobs(value BLOB)')
            connection.execute('CREATE TABLE hosted_players(login TEXT PRIMARY KEY,save BLOB)')
            connection.execute('INSERT INTO hosted_players VALUES(?,?)',('foreign-player',b'authoritative hosted save'))
        fake_fcntl=types.ModuleType('fcntl');fake_fcntl.LOCK_EX=1;fake_fcntl.LOCK_NB=2;fake_fcntl.flock=lambda *args:None
        ns={'__name__':'isolated_fixture'}
        with patch.dict(sys.modules,{'fcntl':fake_fcntl}):exec(p.REMOTE.split("if __name__=='__main__':")[0],ns)
        ns.update(LIVE=live,PRIVATE=private,GAME=game,DB=db)
        proxy=types.SimpleNamespace(**{key:getattr(os,key) for key in dir(os)})
        proxy.O_NOFOLLOW=getattr(os,'O_NOFOLLOW',0);proxy.chown=lambda *args:None;proxy.fsync=lambda *args:None
        ns['os']=proxy;ns['sync']=lambda path:None;real_state=ns['state']
        ns['state']=lambda path:dict(real_state(path),uid=0,gid=0,mode=0o600 if path.is_relative_to(private) else 0o644)
        guards=dict(services={'tio-server':dict(ActiveState='active',MainPID='100',NRestarts='0')},launchers={'version':'0.1.4'},
                    configuration={},game_code={'server/source.py':real_state(game/'server/source.py')})
        ns['guards']=lambda:copy.deepcopy(guards)
        return ns,live,private,game,db,guards

    def checker(self,fixture):
        pub,live,private,game,db,guards=fixture
        ns={'__name__':'isolated_read_only_checker'}
        exec(v.REMOTE.split("if __name__=='__main__':")[0],ns)
        ns.update(LIVE=live,PRIVATE=private,GAME=game,DB=db)
        original=ns['state'];ns['state']=lambda path:dict(original(path),uid=0,gid=0,mode=0o600 if path.is_relative_to(private) else 0o644)
        ns['guards']=lambda:copy.deepcopy(guards)
        ns['private_directory']=lambda path:ns['directory'](path)
        return ns

    def changed_manifest(self,payload,change):
        result=copy.deepcopy(payload);manifest=json.loads(base64.b64decode(result['after_manifest']));change(manifest)
        raw=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode();result['after_manifest']=base64.b64encode(raw).decode();result['after_manifest_sha256']=p.sha(raw)
        return result

    def invalid_package(self,change):
        value=copy.deepcopy(self.package);change(value);raw=json.dumps(value).encode()
        return raw,p.sha(raw)

    def inspect_and_publish(self):
        fixture=self.fixture();ns,*rest=fixture;inspected=ns['execute'](self.payload_copy())
        receipt=ns['execute'](self.payload_copy(True,fixture[-1]))
        request=v.make_request(self.payload,receipt,inspected)
        return fixture,receipt,request

    def test_exact_package_identity_and_read_only_loader(self):
        package,raws=p.load_package(self.package_path,p.sha(self.package_bytes),baseline=self.real_baseline)
        self.assertEqual(package,self.package);self.assertEqual(raws,self.raws)

    def test_multi_entry_transition_preserves_all_unrelated_records(self):
        old=json.loads(base64.b64decode(self.payload['before_manifest']));new=json.loads(base64.b64decode(self.payload['after_manifest']))
        self.assertEqual([a['path'] for a,b in zip(old['files'],new['files']) if a!=b],['silver.dll'])
        self.assertEqual(len(new['files']),6334);self.assertEqual(sum(a==b for a,b in zip(old['files'],new['files'])),6329)
        self.assertEqual([x['path'] for x in new['files'][6330:]],sorted(set(self.raws)-{'silver.dll'}))
        self.assertEqual({k:v for k,v in old.items() if k not in ('version','files')},{k:v for k,v in new.items() if k not in ('version','files')})

    def test_wrong_reviewed_package_sha_refused(self):
        with self.assertRaises(ValueError):p.load_package(self.package_path,'0'*64,baseline=self.real_baseline)

    def test_selected_style_and_font_required(self):
        for change in (lambda m:m['selection'].update(icons='b-tactical'),lambda m:m['selection'].update(font_family='Exo 2')):
            with self.assertRaises(ValueError):p.package_identity(*self.invalid_package(change))

    def test_ti_launcher_player_seed_and_original_fallback_paths_refused(self):
        for name in ('ti.exe','TIO-Launcher.exe','base/autoexec.cfg','base/login.ini','base/fonts/pixel13.png','base/pda/icon_button_inventory.png'):
            raw,digest=self.invalid_package(lambda m:m['files'][0].update(path=name))
            with self.assertRaises(ValueError):p.package_identity(raw,digest)

    def test_traversal_ads_devices_case_duplicates_and_prefix_collisions_refused(self):
        mutations=(lambda m:m['files'][1].update(source='../outside.png'),lambda m:m['files'][1].update(path='base/ui-hd/fonts/a.png:secret'),
                   lambda m:m['files'][1].update(path='base/ui-hd/fonts/CON.png'),lambda m:m['files'][1].update(path='base/ui-hd/fonts./a.png'),
                   lambda m:m['files'].append(dict(m['files'][0],path='SILVER.DLL')),
                   lambda m:m['files'][2].update(path=m['files'][1]['path']+'/b.xml'))
        for change in mutations:
            with self.assertRaises(ValueError):p.package_identity(*self.invalid_package(change))

    def test_unknown_metadata_kind_and_incomplete_package_refused(self):
        for change in (lambda m:m.update(secret_data=True),lambda m:m.update(schema=True),lambda m:m['files'][1].update(kind='save'),lambda m:m['files'].pop()):
            with self.assertRaises(ValueError):p.package_identity(*self.invalid_package(change))

    def test_candidate_blob_hash_corruption_refused(self):
        value=self.payload_copy();value['updates']['base/ui-hd/icons/classic_125.png']['blob']=base64.b64encode(b'wrong').decode()
        ns,*_=self.fixture()
        with self.assertRaises(ValueError):ns['transition'](value)

    def test_png_crc_bounds_xml_entity_and_license_refused(self):
        image=next(x for x in self.package['files'] if x['kind']=='icon_image');raw=bytearray(self.raws[image['path']]);raw[35]^=1
        item=dict(image,sha256=p.sha(raw));
        with self.assertRaises(ValueError):p.blob_identity(item,raw)
        descriptor=next(x for x in self.package['files'] if x['kind']=='font_descriptor');raw=b'<!DOCTYPE a [<!ENTITY b SYSTEM "file:///secret">]><a>&b;</a>'
        with self.assertRaises(ValueError):p.blob_identity(dict(descriptor,sha256=p.sha(raw),size=len(raw)),raw)
        notice=next(x for x in self.package['files'] if x['kind']=='license');raw=b'Unreviewed license'
        with self.assertRaises(ValueError):p.blob_identity(dict(notice,sha256=p.sha(raw),size=len(raw)),raw)

    def test_native_screen11_payload_hook_and_12_markers_retained(self):
        from tools.test_publish_ui_modernization_remote import rva_offset
        for rva in (0x823000,0x82dfff,0x483816,0x483844,0x483924,p.AUTH_SPANS[0][0]-0x400000):
            raw=bytearray(self.raws['silver.dll']);raw[rva_offset(raw,rva)]^=1
            with self.assertRaises(ValueError):p.native_preserved(self.source,raw)
        raw=self.raws['silver.dll'].replace(b'TIO-portrait-512-preview-v1',b'X'*len(b'TIO-portrait-512-preview-v1'))
        with self.assertRaises(ValueError):p.native_preserved(self.source,raw)

    def test_unreviewed_metadata_seed_record_order_and_missing_addition_refused(self):
        ns,*_=self.fixture()
        changes=(lambda m:m['files'][0].update(size=m['files'][0]['size']+1),lambda m:m.update(news='unexpected change'),lambda m:m.update(schema=True),
                 lambda m:m['files'].reverse(),lambda m:m['files'].pop(),lambda m:m['files'][-1].update(seed=True),lambda m:m['files'][-1].update(seed=0))
        for change in changes:
            with self.assertRaises(ValueError):ns['transition'](self.changed_manifest(self.payload,change))

    def test_inspect_writes_nothing_and_keeps_foreign_checkpoint(self):
        ns,live,private,game,db,guards=self.fixture();before=db.read_bytes();report=ns['execute'](self.payload_copy())
        self.assertEqual(report['remote_mutations'],0);self.assertEqual(report['health']['checkpoints'],1)
        self.assertEqual(db.read_bytes(),before);self.assertEqual((live/'manifest.json').read_bytes(),self.old);self.assertEqual(list(private.iterdir()),[])

    def test_apply_requires_exact_inspected_guards(self):
        ns,live,private,game,db,guards=self.fixture();wrong=copy.deepcopy(guards);wrong['services']['tio-server']['MainPID']='different'
        with self.assertRaises(RuntimeError):ns['execute'](self.payload_copy(True,wrong))
        self.assertEqual(list(private.iterdir()),[]);self.assertEqual((live/'manifest.json').read_bytes(),self.old)

    def test_all_immutable_blobs_uploaded_before_single_atomic_commit(self):
        ns,live,private,game,db,guards=self.fixture();before=db.read_bytes();order=[];immutable=ns['immutable'];atomic=ns['atomic']
        def upload(raw,target):
            self.assertEqual((live/'manifest.json').read_bytes(),self.old);order.append('blob');return immutable(raw,target)
        def commit(raw,target,expected=None):
            self.assertEqual(order,['blob']*len(self.raws));order.append('manifest');return atomic(raw,target,expected)
        ns['immutable']=upload;ns['atomic']=commit;receipt=ns['execute'](self.payload_copy(True,guards))
        self.assertEqual(order,['blob']*len(self.raws)+['manifest']);self.assertEqual(db.read_bytes(),before)
        self.assertEqual(receipt['patch_scope']['preserved_records'],6329);self.assertEqual(receipt['health']['checkpoints'],1)
        folder=Path(receipt['backup']);self.assertEqual((folder/'previous-manifest.json').read_bytes(),self.old)
        self.assertEqual((folder/'previous-blobs'/p.SILVER_SHA).read_bytes(),self.source)
        with contextlib.closing(sqlite3.connect(folder/'reservation.sqlite3')) as saved:
            self.assertEqual(saved.execute('SELECT save FROM hosted_players').fetchone()[0],b'authoritative hosted save')
            self.assertEqual(saved.execute('SELECT value FROM battle_checkpoints').fetchone()[0],b'legitimate foreign checkpoint')

    def test_second_blob_upload_failure_never_exposes_partial_manifest(self):
        ns,live,private,game,db,guards=self.fixture();original=ns['immutable'];calls=[]
        def upload(raw,target):
            calls.append(target)
            if len(calls)==2:raise RuntimeError('injected second upload failure')
            return original(raw,target)
        ns['immutable']=upload
        with self.assertRaises(RuntimeError):ns['execute'](self.payload_copy(True,guards))
        self.assertEqual((live/'manifest.json').read_bytes(),self.old)

    def test_guard_race_after_backup_refuses_commit(self):
        ns,live,private,game,db,guards=self.fixture();original=ns['backup']
        def raced(*args):
            result=original(*args);guards['services']['tio-server']['MainPID']='external restart';return result
        ns['backup']=raced
        with self.assertRaises(RuntimeError):ns['execute'](self.payload_copy(True,guards))
        self.assertEqual((live/'manifest.json').read_bytes(),self.old)

    def test_postcommit_failure_restores_exact12_manifest_only(self):
        ns,live,private,game,db,guards=self.fixture();before=db.read_bytes();original=ns['database'];calls=[]
        def database(path):
            rows,health=original(path);calls.append(1)
            if len(calls)==2:rows.remove(next(iter(rows)))
            return rows,health
        ns['database']=database
        with self.assertRaises(RuntimeError):ns['execute'](self.payload_copy(True,guards))
        self.assertEqual((live/'manifest.json').read_bytes(),self.old);self.assertEqual(db.read_bytes(),before)

    def test_concurrent_manifest_never_overwritten_by_rollback(self):
        ns,live,private,game,db,guards=self.fixture();original=ns['database'];calls=[]
        def database(path):
            result=original(path);calls.append(1)
            if len(calls)==2:(live/'manifest.json').write_bytes(b'new unrelated concurrent release')
            return result
        ns['database']=database
        with self.assertRaises(RuntimeError):ns['execute'](self.payload_copy(True,guards))
        self.assertEqual((live/'manifest.json').read_bytes(),b'new unrelated concurrent release')

    def test_failed_durable_receipt_restores_exact12_manifest(self):
        ns,live,private,game,db,guards=self.fixture();before=db.read_bytes();original=ns['private_json']
        def receipt(path,value):
            if path.name=='publication.json':raise RuntimeError('injected durable receipt write failure')
            return original(path,value)
        ns['private_json']=receipt
        with self.assertRaises(RuntimeError):ns['execute'](self.payload_copy(True,guards))
        self.assertEqual((live/'manifest.json').read_bytes(),self.old);self.assertEqual(db.read_bytes(),before)

    def test_stale_apply_refused_after_success_without_second_backup(self):
        ns,live,private,game,db,guards=self.fixture();ns['execute'](self.payload_copy(True,guards));before=list(private.glob('tio-before-ui-hd-assets-*'))
        with self.assertRaises(RuntimeError):ns['execute'](self.payload_copy(True,guards))
        self.assertEqual(list(private.glob('tio-before-ui-hd-assets-*')),before)

    def test_independent_checker_success_read_only_and_full_backup_integrity(self):
        fixture,receipt,request=self.inspect_and_publish();checker=self.checker(fixture);db=fixture[4];before=db.read_bytes();manifest=(fixture[1]/'manifest.json').read_bytes()
        result=checker['verify'](request)
        self.assertEqual(result['remote_mutations'],0);self.assertEqual(result['preserved_records'],6329);self.assertEqual(result['backup_accounts'],202)
        self.assertEqual(result['backup_code_files_verified'],1);self.assertEqual(result['backup_file_checksums_verified'],6)
        self.assertEqual(db.read_bytes(),before);self.assertEqual((fixture[1]/'manifest.json').read_bytes(),manifest)

    def test_checker_receipt_and_guard_tampering_refused(self):
        fixture,receipt,request=self.inspect_and_publish();checker=self.checker(fixture)
        for mutation in (lambda r:r['receipt'].update(package_sha256='0'*64),lambda r:r['inspected_guards']['launchers'].update(version='changed')):
            value=copy.deepcopy(request);mutation(value)
            with self.assertRaises(RuntimeError):checker['verify'](value)

    def test_checker_published_resource_and_pinned_ti_tampering_refused(self):
        for digest in (self.package['files'][3]['sha256'],p.TI_SHA):
            fixture,receipt,request=self.inspect_and_publish();(fixture[1]/'blobs'/digest).write_bytes(b'tampered immutable file')
            with self.assertRaises((RuntimeError,ValueError)):self.checker(fixture)['verify'](request)

    def test_checker_backup_blob_corruption_and_inventory_loss_refused(self):
        for tamper in ('blob','inventory'):
            fixture,receipt,request=self.inspect_and_publish();folder=Path(receipt['backup'])
            if tamper=='blob':(folder/'previous-blobs'/p.SILVER_SHA).write_bytes(b'tampered previous native')
            else:
                path=folder/'backup-manifest.json';value=json.loads(path.read_bytes());value['files'].pop('reservation.sqlite3');path.write_text(json.dumps(value))
            with self.assertRaises(RuntimeError):self.checker(fixture)['verify'](request)

    def test_checker_account_credential_loss_refused(self):
        fixture,receipt,request=self.inspect_and_publish()
        with contextlib.closing(sqlite3.connect(fixture[4])) as db,db:db.execute("UPDATE accounts SET digest=? WHERE login='synthetic_0'",(b'changed foreign credential',))
        with self.assertRaises(RuntimeError):self.checker(fixture)['verify'](request)

    def test_checker_durable_journal_tampering_refused(self):
        fixture,receipt,request=self.inspect_and_publish();path=Path(receipt['backup'])/'publication-journal.json';value=json.loads(path.read_bytes());value['package_sha256']='0'*64;path.write_text(json.dumps(value))
        with self.assertRaises(RuntimeError):self.checker(fixture)['verify'](request)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(Guards))
    report=dict(passed=result.wasSuccessful(),tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),remote_mutations=0,network_calls=0,
                fixture_path=str(Guards.folder),fixture_directories_retained=True,posix_metadata_and_locking_simulated=True,production_candidate_tested=False,
                publisher_sha256=p.sha(Path(p.__file__).read_bytes()),checker_sha256=p.sha(Path(v.__file__).read_bytes()),
                publisher_remote_program_sha256=p.sha(p.REMOTE.encode()),checker_remote_program_sha256=p.sha(v.REMOTE.encode()),
                finished_utc=datetime.now(timezone.utc).isoformat())
    path=p.DEPLOYMENT/('publication-guard-tests-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'.json')
    path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],tests=report['tests'],report=str(path))))
    if not result.wasSuccessful():raise SystemExit(1)
