"""Guard tests with isolated native fixtures and a temporary hosted filesystem.

No SSH/network call or actual hosted mutation. Native fixture candidates are
deliberately synthetic and are never eligible evidence for graphical QA.
"""
import base64
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_ui_modernization_remote as p


def rva_offset(raw, rva):
    header = struct.unpack_from('<I', raw, 0x3c)[0]
    count = struct.unpack_from('<H', raw, header+6)[0]
    optional = struct.unpack_from('<H', raw, header+20)[0]
    for index in range(count):
        at = header+24+optional+index*40
        _, virtual, size, offset = struct.unpack_from('<IIII', raw, at+8)
        if virtual <= rva < virtual+size:
            return offset+rva-virtual
    raise AssertionError('Fixture RVA absent')


class Guards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp(prefix='publisher-guard-tests-', dir=p.REPORT_ROOT))
        assert cls.folder.resolve().is_relative_to(p.REPORT_ROOT.resolve())
        cls.sources = {name:(p.BASELINE.parent/name).read_bytes() for name in p.SOURCES}
        cls.silver = cls.sources['silver.dll']+b'\0TIO-independent-ui-scale-v1\0TIO-ui-scale-controls-v1\0TIO-portrait-512-preview-v1\0'
        cls.ti = cls.sources['ti.exe']+b'\0isolated-review-fixture\0'
        cls.silver_path, cls.ti_path = cls.folder/'silver.dll', cls.folder/'ti.exe'
        cls.silver_path.write_bytes(cls.silver); cls.ti_path.write_bytes(cls.ti)
        cls.identities = {
            'silver.dll':(cls.silver_path,p.sha(cls.silver),len(cls.silver)),
            'ti.exe':(cls.ti_path,p.sha(cls.ti),len(cls.ti)),
        }
        cls.one = p.make_payload({'silver.dll':cls.identities['silver.dll']},'inspect')
        cls.two = p.make_payload(cls.identities,'inspect')

    @classmethod
    def tearDownClass(cls):
        assert cls.folder.resolve().is_relative_to(p.REPORT_ROOT.resolve())
        shutil.rmtree(cls.folder)

    def payload(self, both=True, action='inspect'):
        value = copy.deepcopy(self.two if both else self.one)
        value['action'] = action
        return value

    def changed_manifest(self, payload, change):
        new = json.loads(base64.b64decode(payload['after_manifest']))
        change(new)
        raw = (json.dumps(new,ensure_ascii=False,indent=2)+'\n').encode()
        payload['after_manifest'] = base64.b64encode(raw).decode()
        payload['after_manifest_sha256'] = p.sha(raw)
        return payload

    def fixture(self):
        folder = Path(tempfile.mkdtemp(prefix='remote-',dir=self.folder))
        fake_fcntl = types.ModuleType('fcntl')
        fake_fcntl.LOCK_EX, fake_fcntl.LOCK_NB = 1, 2
        fake_fcntl.flock = lambda *args:None
        ns = {'__name__':'isolated_remote'}
        with patch.dict(sys.modules, {'fcntl':fake_fcntl}):
            exec(p.REMOTE.split("if __name__=='__main__':")[0],ns)
        live, private, game = folder/'updates', folder/'private', folder/'game'
        for path in (live/'blobs',private,game/'server'):
            path.mkdir(parents=True)
        (game/'server/source.py').write_text('immutable server source\n')
        (live/'manifest.json').write_bytes(p.BASELINE.read_bytes())
        for name, raw in self.sources.items():
            (live/'blobs'/p.SOURCES[name][0]).write_bytes(raw)
        db = folder/'reservation.sqlite3'
        with contextlib.closing(sqlite3.connect(db)) as connection, connection:
            connection.execute('CREATE TABLE accounts(login TEXT PRIMARY KEY)')
            connection.executemany('INSERT INTO accounts VALUES (?)',((f'hosted_{i}',) for i in range(202)))
            connection.execute('CREATE TABLE battle_checkpoints(value INTEGER)')
            connection.execute('CREATE TABLE battle_settlement_jobs(value INTEGER)')
        ns.update(LIVE=live,PRIVATE=private,GAME=game,DB=db)
        # Windows test fixtures simulate POSIX metadata/fsync; production uses
        # the original Linux primitives without these replacements.
        proxy = types.SimpleNamespace(**{key:getattr(os,key) for key in dir(os)})
        proxy.O_NOFOLLOW = getattr(os,'O_NOFOLLOW',0)
        proxy.chown = lambda *args:None
        ns['os'], ns['sync'] = proxy, lambda path:None
        real_state = ns['state']
        ns['state'] = lambda path:dict(real_state(path),uid=0,gid=0,mode=0o644)
        guards = {'services':{'tio-server':{'ActiveState':'active','MainPID':'100','NRestarts':'0'}},
                  'launchers':{'version':'0.1.4'},'configuration':{'sha256':'cfg'},'game_code':{'sha256':'code'}}
        ns['guards'] = lambda:copy.deepcopy(guards)
        return ns, live, private, db, guards

    def test_exact_one_record_transition(self):
        old, new = (json.loads(base64.b64decode(self.one[key])) for key in ('before_manifest','after_manifest'))
        self.assertEqual(new['version'],'2026.10.09.12')
        self.assertEqual([a['path'] for a,b in zip(old['files'],new['files']) if a!=b],['silver.dll'])
        self.assertEqual(len(new['files']),6330)

    def test_exact_two_record_transition(self):
        old, new = (json.loads(base64.b64decode(self.two[key])) for key in ('before_manifest','after_manifest'))
        self.assertEqual({a['path'] for a,b in zip(old['files'],new['files']) if a!=b},{'silver.dll','ti.exe'})
        self.assertEqual(sum(a==b for a,b in zip(old['files'],new['files'])),6328)

    def test_wrong_review_hash_refused(self):
        with self.assertRaises(ValueError):
            p.make_payload({'silver.dll':(self.silver_path,'0'*64,len(self.silver))},'inspect')

    def test_unreviewed_ti_or_missing_silver_refused(self):
        for value in ({'ti.exe':self.identities['ti.exe']},{'orange.dll':self.identities['silver.dll']}):
            with self.assertRaises(ValueError):p.make_payload(value,'inspect')

    def test_size_bounds_and_unchanged_binary_refused(self):
        for length in (p.SOURCES['silver.dll'][1]-1,p.SOURCES['silver.dll'][1]+1024*1024+1):
            with self.assertRaises(ValueError):p.identity('silver.dll',self.silver,p.sha(self.silver),length)
        with self.assertRaises(ValueError):p.identity('silver.dll',self.sources['silver.dll'],*p.SOURCES['silver.dll'])

    def test_candidate_path_scope_refused(self):
        with self.assertRaisesRegex(ValueError,'reports/ui-modernization'):
            p.make_payload({'silver.dll':(ROOT/'reports/screen-settings/client/silver.dll',p.sha(self.silver),len(self.silver))},'inspect')

    def test_partial_optional_ti_cli_refused_before_network(self):
        args=['--silver',str(self.silver_path),'--silver-sha256',p.sha(self.silver),'--silver-bytes',str(len(self.silver)),
              '--ti',str(self.ti_path),'--report',str(self.folder/'unused.json'),'--inspect']
        with patch.object(p,'invoke') as invoke,contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):p.main(args)
        invoke.assert_not_called()

    def test_screen11_payload_hook_and_complete_markers_retained(self):
        for rva in (0x823000,0x483816,0x483844,0x483924):
            raw=bytearray(self.silver);raw[rva_offset(raw,rva)]^=1
            with self.assertRaises(ValueError):p.preserved_native('silver.dll',self.sources['silver.dll'],bytes(raw))
        for marker in (b'TIO-independent-ui-scale-v1',b'TIO-ui-scale-controls-v1',b'TIO-portrait-512-preview-v1'):
            with self.assertRaises(ValueError):p.preserved_native('silver.dll',self.sources['silver.dll'],self.silver.replace(marker,b'X'*len(marker)))

    def test_ti_native_host_guard_retained(self):
        raw=bytearray(self.ti);raw[rva_offset(raw,0x346470)]^=1
        with self.assertRaises(ValueError):p.preserved_native('ti.exe',self.sources['ti.exe'],bytes(raw))

    def test_remote_inspect_writes_nothing(self):
        ns,live,private,db,guards=self.fixture();before_manifest=(live/'manifest.json').read_bytes();before_db=db.read_bytes()
        report=ns['execute'](self.payload())
        self.assertTrue(report['passed']);self.assertEqual(report['remote_mutations'],0)
        self.assertEqual(report['health']['accounts'],202);self.assertFalse(list(private.iterdir()))
        self.assertEqual((live/'manifest.json').read_bytes(),before_manifest);self.assertEqual(db.read_bytes(),before_db)

    def test_remote_other_record_seed_and_order_changes_refused(self):
        ns,*_=self.fixture()
        mutations=(lambda m:m['files'][0].update(size=m['files'][0]['size']+1),
                   lambda m:next(x for x in m['files'] if x['path']=='silver.dll').update(seed=True),
                   lambda m:m['files'].reverse(),lambda m:m['files'].append(dict(m['files'][0])))
        for mutation in mutations:
            with self.assertRaises(ValueError):ns['transition'](self.changed_manifest(self.payload(),mutation))

    def test_remote_metadata_version_and_updates_scope_refused(self):
        ns,*_=self.fixture()
        for mutation in (lambda m:m.update(version='2026.10.09.10'),lambda m:m.update(unreviewed=True)):
            with self.assertRaises(ValueError):ns['transition'](self.changed_manifest(self.payload(),mutation))
        value=self.payload();value['updates']['orange.dll']=value['updates']['ti.exe']
        with self.assertRaises(ValueError):ns['transition'](value)

    def test_remote_baseline_and_source_mismatch_refused(self):
        ns,live,*_=self.fixture();(live/'manifest.json').write_bytes(b'changed')
        with self.assertRaises(RuntimeError):ns['transition'](self.payload())
        (live/'manifest.json').write_bytes(p.BASELINE.read_bytes())
        (live/'blobs'/p.SOURCES['ti.exe'][0]).write_bytes(b'changed')
        with self.assertRaises(RuntimeError):ns['transition'](self.payload())

    def test_remote_candidate_blob_hash_and_hotapply_regression_refused(self):
        ns,*_=self.fixture();value=self.payload();value['updates']['silver.dll']['blob']=base64.b64encode(b'MZwrong').decode()
        with self.assertRaises(ValueError):ns['transition'](value)
        raw=bytearray(self.silver);raw[rva_offset(raw,0x823000)]^=1
        value=self.payload();value['updates']['silver.dll'].update(sha256=p.sha(raw),blob=base64.b64encode(raw).decode())
        value=self.changed_manifest(value,lambda m:next(x for x in m['files'] if x['path']=='silver.dll').update(sha256=p.sha(raw)))
        with self.assertRaises(ValueError):ns['transition'](value)

    def test_atomic_two_blob_publication_and_hosted_backup(self):
        ns,live,private,db,guards=self.fixture();before_db=db.read_bytes();order=[]
        immutable,atomic=ns['immutable'],ns['atomic']
        def blob(raw,path):order.append(('blob',p.sha(raw)));return immutable(raw,path)
        def manifest(raw,path,expected=None):order.append(('manifest',p.sha(raw)));return atomic(raw,path,expected)
        ns['immutable'],ns['atomic']=blob,manifest
        report=ns['execute'](self.payload(action='apply'))
        self.assertEqual([item[0] for item in order],['blob','blob','manifest'])
        self.assertTrue(report['hosted_accounts_preserved']);self.assertEqual(report['accounts_after'],202)
        self.assertEqual(db.read_bytes(),before_db);self.assertEqual(report['version'],'2026.10.09.12')
        backup=Path(report['backup'])
        self.assertEqual((backup/'previous-manifest.json').read_bytes(),p.BASELINE.read_bytes())
        for name,raw in self.sources.items():self.assertEqual((backup/name).read_bytes(),raw)
        with contextlib.closing(sqlite3.connect(backup/'reservation.sqlite3')) as saved:
            self.assertEqual(saved.execute('PRAGMA integrity_check').fetchall(),[('ok',)])
            self.assertEqual(saved.execute('SELECT count(*) FROM accounts').fetchone()[0],202)

    def test_second_blob_failure_never_exposes_partial_manifest(self):
        ns,live,private,db,guards=self.fixture();original=ns['immutable'];calls=[]
        def fail_second(raw,path):
            calls.append(path)
            if len(calls)==2:raise RuntimeError('injected second blob failure')
            return original(raw,path)
        ns['immutable']=fail_second
        with self.assertRaises(RuntimeError):ns['execute'](self.payload(action='apply'))
        self.assertEqual((live/'manifest.json').read_bytes(),p.BASELINE.read_bytes())

    def test_guard_race_after_backup_refuses_commit(self):
        ns,live,private,db,guards=self.fixture();original=ns['backup']
        def raced(*args):
            result=original(*args);guards['configuration']['sha256']='external change';return result
        ns['backup']=raced
        with self.assertRaises(RuntimeError):ns['execute'](self.payload(action='apply'))
        self.assertEqual((live/'manifest.json').read_bytes(),p.BASELINE.read_bytes())

    def test_failed_postpublication_reverts_to_exact11_only(self):
        ns,live,private,db,guards=self.fixture();original=ns['guards'];calls=[]
        def guarded():
            calls.append(1)
            if len(calls)>=5:guards['services']['tio-server']['MainPID']='external restart'
            return original()
        ns['guards']=guarded
        with self.assertRaises(RuntimeError):ns['execute'](self.payload(action='apply'))
        self.assertEqual((live/'manifest.json').read_bytes(),p.BASELINE.read_bytes())
        self.assertEqual(json.loads((live/'manifest.json').read_bytes())['version'],'2026.10.09.11')

    def test_concurrent_publication_never_overwritten_by_rollback(self):
        ns,live,private,db,guards=self.fixture();original=ns['guards'];calls=[]
        def guarded():
            calls.append(1)
            if len(calls)>=5:(live/'manifest.json').write_bytes(b'concurrent unrelated manifest')
            return original()
        ns['guards']=guarded
        with self.assertRaises(RuntimeError):ns['execute'](self.payload(action='apply'))
        self.assertEqual((live/'manifest.json').read_bytes(),b'concurrent unrelated manifest')

    def test_account_identity_loss_refuses_release_without_restoring_db(self):
        ns,live,private,db,guards=self.fixture();original=ns['accounts'];calls=[];before_db=db.read_bytes()
        def accounts():
            ids,health=original();calls.append(1)
            if len(calls)>1:ids.remove('hosted_0')
            return ids,health
        ns['accounts']=accounts
        with self.assertRaises(RuntimeError):ns['execute'](self.payload(action='apply'))
        self.assertEqual((live/'manifest.json').read_bytes(),p.BASELINE.read_bytes())
        self.assertEqual(db.read_bytes(),before_db)

    def test_stale_apply_refused_after_success(self):
        ns,live,private,db,guards=self.fixture();ns['execute'](self.payload(action='apply'))
        existing=list(private.glob('tio-before-ui-modernization-*'))
        with self.assertRaises(RuntimeError):ns['execute'](self.payload(action='apply'))
        self.assertEqual(list(private.glob('tio-before-ui-modernization-*')),existing)

    def test_existing_unrelated_checkpoint_player_fully_preserved(self):
        ns,live,private,db,guards=self.fixture()
        with contextlib.closing(sqlite3.connect(db)) as connection, connection:
            connection.execute('INSERT INTO battle_checkpoints VALUES(17)')
            connection.execute('CREATE TABLE hosted_players(login TEXT PRIMARY KEY,save BLOB)')
            connection.execute('INSERT INTO hosted_players VALUES(?,?)',('unrelated_real_player',b'authoritative-hosted-save'))
        before=db.read_bytes();report=ns['execute'](self.payload(action='apply'))
        self.assertEqual(report['health']['checkpoints'],1);self.assertEqual(db.read_bytes(),before)
        with contextlib.closing(sqlite3.connect(Path(report['backup'])/'reservation.sqlite3')) as saved:
            self.assertEqual(saved.execute('SELECT value FROM battle_checkpoints').fetchall(),[(17,)])
            self.assertEqual(saved.execute('SELECT login,save FROM hosted_players').fetchall(),[('unrelated_real_player',b'authoritative-hosted-save')])


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Guards)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    report=dict(passed=result.wasSuccessful(),tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                remote_mutations=0,network_calls=0,production_candidate_tested=False,
                publisher_sha256=p.sha(Path(p.__file__).read_bytes()),remote_program_sha256=p.sha(p.REMOTE.encode()),
                posix_metadata_and_locking_simulated=True)
    (p.REPORT_ROOT/'publisher-guard-tests.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if not result.wasSuccessful():raise SystemExit(1)
