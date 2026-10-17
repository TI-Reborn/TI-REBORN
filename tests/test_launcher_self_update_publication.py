"""Isolated launcher publication/recovery checks; never contact the hosted server."""
from contextlib import nullcontext
import ast
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import publish_launcher_update_remote as publication


class ReleaseGuardTests(unittest.TestCase):
    def test_explicit_015_baseline_allows_016_and_rejects_same_version(self):
        with patch.object(publication,'OLD_VERSION','0.1.4'),patch.object(publication,'OLD_HASH','a'*64),patch.object(publication,'OLD_BYTES',1234567):
            baseline=publication.configure_baseline(SimpleNamespace(baseline_version='0.1.5',baseline_sha256='b'*64,baseline_bytes=2345678))
            self.assertEqual(baseline,{'version':'0.1.5','sha256':'b'*64,'size':2345678})
            self.assertEqual(publication.validate_release('0.1.6','c'*64,3456789).name,'TIO-Launcher-0.1.6.exe')
            with self.assertRaisesRegex(ValueError,'newer'):
                publication.validate_release('0.1.5','c'*64,3456789)

    def test_invalid_baseline_configuration_does_not_partially_change_guards(self):
        before=publication.baseline_identity()
        with self.assertRaises(ValueError):
            publication.configure_baseline(SimpleNamespace(baseline_version='0.1.5',baseline_sha256='b'*64,baseline_bytes=0))
        self.assertEqual(publication.baseline_identity(),before)

    def test_manifest_is_small_fixed_origin_schema(self):
        value=json.loads(publication.self_manifest_bytes('0.1.5','a'*64,1234567))
        self.assertEqual(value,{'schema':1,'version':'0.1.5','sha256':'a'*64,'size':1234567})
        self.assertNotIn('url',value)
        self.assertEqual(publication.validate_release('0.1.5','a'*64,1234567).name,'TIO-Launcher-0.1.5.exe')

    def test_reject_versions_that_could_escape_or_downgrade(self):
        for version in ('../0.1.5','0.1.5/evil','0.1.5?x','0.1.5.0','00.1.5','0.1.4','0.1.3','','latest',None):
            with self.subTest(version=version),self.assertRaises(ValueError):
                publication.validate_release(version,'a'*64,1234567)

    def test_numeric_versions_compare_numerically(self):
        self.assertEqual(publication.validate_release('0.1.10','a'*64,1234567).name,'TIO-Launcher-0.1.10.exe')

    def test_reject_invalid_hash_and_unbounded_size(self):
        for digest,size in (('A'*64,1234567),('a'*63,1234567),('a'*64,0),('a'*64,True),('a'*64,300*1024*1024)):
            with self.subTest(digest=digest,size=size),self.assertRaises(ValueError):
                publication.validate_release('0.1.5',digest,size)

    def test_only_launcher_metadata_fields_written_with_compare_and_swap(self):
        before={'id':'main','launcherVersion':'0.1.4','gameVersion':'client-version','updatedAt':'2026-10-10T07:00:00'}
        values={'launcherVersion':'0.1.5','launcherUrl':'/downloads/TIO-Launcher-0.1.5.exe',
                'fileSizeBytes':1234567,'updatedAt':'2026-10-10T08:00:00'}
        with patch.object(publication,'sql_json',return_value={}) as operation:
            publication.replace_metadata(before,values)
        statement,arguments=operation.call_args.args
        update=statement.split(' UPDATE ')[1].split('GET DIAGNOSTICS')[0]
        self.assertNotIn('gameVersion',update)
        self.assertNotIn('User',update)
        self.assertIn('FOR UPDATE',statement)
        self.assertIn('IS DISTINCT FROM',statement)
        self.assertEqual(json.loads(arguments['before']),before)
        with self.assertRaises(ValueError):publication.replace_metadata(before,{**values,'gameVersion':'oops'})

    def test_timeout_after_commit_reconciles_by_rereading(self):
        before={'id':'main','updatedAt':'2026-10-10T07:00:00','launcherVersion':'0.1.4'}
        values={'updatedAt':'2026-10-10T08:00:00.100','launcherVersion':'0.1.5'}
        actual={'row':{**before,**values,'updatedAt':'2026-10-10T08:00:00.1'}}
        with patch.object(publication,'replace_metadata',side_effect=RuntimeError),patch.object(publication,'read_row',return_value=actual):
            self.assertEqual(publication.reconcile_metadata(before,values),actual)

    def test_concurrent_metadata_is_preserved(self):
        with patch.object(publication,'replace_metadata',side_effect=RuntimeError),patch.object(publication,'read_row',return_value={'row':{'id':'main','launcherVersion':'0.1.6'}}):
            with self.assertRaisesRegex(RuntimeError,'concurrently'):
                publication.reconcile_metadata({'id':'main','launcherVersion':'0.1.4'},{'launcherVersion':'0.1.5'})

    def test_tool_is_self_contained_and_inspect_has_no_writes(self):
        source=Path(publication.__file__).read_text(encoding='utf-8');tree=ast.parse(source)
        imports=[node for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom))]
        self.assertFalse(any(isinstance(node,ast.ImportFrom) and (node.module or '').startswith('tools') for node in imports))
        inspect=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='inspect')
        names={node.func.id for node in ast.walk(inspect) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)}
        self.assertFalse(names&{'copy_private','private_json','replace_metadata','replace_alias','replace_self_manifest'})
        self.assertIn("receipt.get('website_full_isolated_restore') is not True",source)
        self.assertIn("receipt['files'][name]",source)


class PublicationFlowTests(unittest.TestCase):
    """Real temporary file operations with isolated database/permission boundaries."""
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.downloads=self.root/'downloads';self.downloads.mkdir()
        self.backup=self.root/'backup';self.backup.mkdir()
        self.alias=self.downloads/'TIO-Launcher.exe';self.self_manifest=self.downloads/'launcher-manifest.json'
        self.old=b'old-reviewed-launcher';self.new=b'new-reviewed-launcher'
        self.old_hash=hashlib.sha256(self.old).hexdigest();self.new_hash=hashlib.sha256(self.new).hexdigest()
        self.alias.write_bytes(self.old);(self.backup/'TIO-Launcher.exe').write_bytes(self.old)
        self.candidate=self.root/'candidate.exe';self.candidate.write_bytes(self.new)
        self.before={'launcher':self.file_state(self.alias),'metadata':{'row':{
            'id':'main','launcherVersion':'0.1.4','launcherUrl':'/downloads/TIO-Launcher-0.1.4.exe',
            'fileSizeBytes':len(self.old),'updatedAt':'2026-10-10T07:00:00.100','gameVersion':'existing-client'}}}
        self.row=dict(self.before['metadata']['row']);self.events=[]
        for name,value in (('DOWNLOADS',self.downloads),('ALIAS',self.alias),('SELF_MANIFEST',self.self_manifest),
                           ('OLD_HASH',self.old_hash),('OLD_BYTES',len(self.old)),('MIN_BYTES',1),
                           ('state',self.file_state),('sync_directory',lambda path:None),
                           ('publication_lock',lambda:nullcontext()),('check_preserved',lambda before:None),
                           ('load_backup',lambda folder:(Path(folder),self.before)),
                           ('read_row',lambda:{'row':dict(self.row)}),('replace_metadata',self.metadata)):
            patcher=patch.object(publication,name,value);patcher.start();self.addCleanup(patcher.stop)
        for name,value in (('O_NOFOLLOW',0),('chown',lambda *args:None)):
            patcher=patch.object(publication.os,name,value,create=True);patcher.start();self.addCleanup(patcher.stop)
        patcher=patch.object(publication,'inspect',self.inspect);patcher.start();self.addCleanup(patcher.stop)
        self.replace_manifest=publication.replace_self_manifest
        patcher=patch.object(publication,'replace_self_manifest',self.commit_manifest);patcher.start();self.addCleanup(patcher.stop)

    def file_state(self,path):
        path=Path(path)
        raw=path.read_bytes()
        return {'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),
                'mode':0o600 if path.parent==self.backup else 0o644,'uid':0,'gid':0}

    def inspect(self,folder,candidate,version,digest,size):
        if self.file_state(self.alias)!=self.before['launcher']:raise ValueError('Changed alias')
        return Path(folder),self.before,publication.prior_self_manifest()

    def metadata(self,before,values):
        if before!=self.row:raise ValueError('Concurrent metadata')
        self.events.append('metadata');self.row={**self.row,**values}
        return {'row':dict(self.row)}

    def commit_manifest(self,raw,guard):
        self.events.append('manifest')
        self.assertEqual(self.alias.read_bytes(),self.new)
        self.assertEqual(self.row['launcherVersion'],'0.1.5')
        return self.replace_manifest(raw,guard)

    def publish(self):
        return publication.publish(self.backup,self.candidate,'0.1.5',self.new_hash,len(self.new))

    def test_manifest_published_after_verified_binary_and_metadata(self):
        report=self.publish()
        self.assertEqual(self.events,['metadata','manifest'])
        self.assertEqual(self.alias.read_bytes(),self.new)
        self.assertEqual(json.loads(self.self_manifest.read_bytes()),{'schema':1,'version':'0.1.5','sha256':self.new_hash,'size':len(self.new)})
        self.assertEqual((self.downloads/'TIO-Launcher-0.1.5.exe').read_bytes(),self.new)
        self.assertEqual(self.row['gameVersion'],'existing-client')
        self.assertEqual(report['account_writes'],0)
        self.assertEqual(report['service_restarts'],0)
        self.assertFalse(report['database_restored'])
        self.assertTrue(Path(report['journal']).is_file())

    def test_rollback_removes_first_manifest_and_preserves_immutable(self):
        report=self.publish();result=publication.rollback(report['journal'])
        self.assertFalse(self.self_manifest.exists())
        self.assertEqual(self.alias.read_bytes(),self.old)
        self.assertEqual(self.row,self.before['metadata']['row'])
        self.assertTrue((self.downloads/'TIO-Launcher-0.1.5.exe').exists())
        self.assertTrue(result['immutable_retained'])

    def test_previous_manifest_captured_and_restored_byte_for_byte(self):
        raw=(json.dumps({'schema':1,'version':'0.1.4','sha256':self.old_hash,'size':len(self.old)},separators=(',',':'))+'\n').encode()
        self.self_manifest.write_bytes(raw)
        report=self.publish()
        self.assertTrue(report['previous_self_manifest_backed_up'])
        self.assertEqual(len(list(self.backup.glob('launcher-manifest-before-*.json'))),1)
        # Recovery also calls the guarded writer after withdrawing the new pointer.
        with patch.object(publication,'replace_self_manifest',self.replace_manifest):
            publication.rollback(report['journal'])
        self.assertEqual(self.self_manifest.read_bytes(),raw)

    def test_existing_immutable_is_never_overwritten(self):
        immutable=self.downloads/'TIO-Launcher-0.1.5.exe';immutable.write_bytes(b'other-release')
        with self.assertRaisesRegex(RuntimeError,'restored'):self.publish()
        self.assertEqual(immutable.read_bytes(),b'other-release')
        self.assertEqual(self.alias.read_bytes(),self.old)
        self.assertFalse(self.self_manifest.exists())

    def test_failed_manifest_commit_restores_alias_and_metadata(self):
        with patch.object(publication,'replace_self_manifest',side_effect=OSError('synthetic disk failure')):
            with self.assertRaisesRegex(RuntimeError,'state was restored'):self.publish()
        self.assertEqual(self.alias.read_bytes(),self.old)
        self.assertEqual(self.row,self.before['metadata']['row'])
        self.assertFalse(self.self_manifest.exists())

    def test_concurrent_manifest_guard_keeps_other_publisher_state(self):
        report=self.publish();self.self_manifest.write_bytes(b'other publisher')
        with self.assertRaisesRegex(ValueError,'Concurrent launcher manifest'):
            publication.rollback(report['journal'])
        self.assertEqual(self.self_manifest.read_bytes(),b'other publisher')
        self.assertEqual(self.alias.read_bytes(),self.new)
        self.assertEqual(self.row['launcherVersion'],'0.1.5')

    def test_concurrent_alias_guard_blocks_all_rollback_writes(self):
        report=self.publish();self.alias.write_bytes(b'other publisher')
        manifest=self.self_manifest.read_bytes()
        with self.assertRaisesRegex(ValueError,'Concurrent launcher binary'):
            publication.rollback(report['journal'])
        self.assertEqual(self.self_manifest.read_bytes(),manifest)
        self.assertEqual(self.alias.read_bytes(),b'other publisher')
        self.assertEqual(self.row['launcherVersion'],'0.1.5')

    def test_concurrent_metadata_guard_blocks_all_rollback_writes(self):
        report=self.publish();self.row['gameVersion']='concurrent-client'
        manifest=self.self_manifest.read_bytes()
        with self.assertRaisesRegex(ValueError,'Concurrent metadata'):
            publication.rollback(report['journal'])
        self.assertEqual(self.self_manifest.read_bytes(),manifest)
        self.assertEqual(self.alias.read_bytes(),self.new)
        self.assertEqual(self.row['gameVersion'],'concurrent-client')

    def test_atomic_manifest_guard_rejects_change_and_removes_temporary(self):
        self.self_manifest.write_bytes(b'concurrent')
        with self.assertRaisesRegex(ValueError,'concurrently'):
            self.replace_manifest(b'candidate',None)
        self.assertEqual(self.self_manifest.read_bytes(),b'concurrent')
        self.assertEqual(list(self.downloads.glob('.tio-launcher-manifest-*')),[])

    def test_rollback_is_idempotent(self):
        report=self.publish()
        publication.rollback(report['journal']);publication.rollback(report['journal'])
        self.assertEqual(self.alias.read_bytes(),self.old)
        self.assertFalse(self.self_manifest.exists())

    def test_015_to_016_preserves_explicit_baseline_and_restores_previous_manifest(self):
        with patch.object(publication,'OLD_VERSION','0.1.5'),patch.object(publication,'replace_self_manifest',self.replace_manifest):
            publication.configure_baseline(SimpleNamespace(baseline_version='0.1.5',baseline_sha256=self.old_hash,baseline_bytes=len(self.old)))
            self.before['metadata']['row'].update(launcherVersion='0.1.5',launcherUrl='/downloads/TIO-Launcher-0.1.5.exe')
            self.row=dict(self.before['metadata']['row'])
            previous=(json.dumps({'schema':1,'version':'0.1.5','sha256':self.old_hash,'size':len(self.old)})+'\n').encode()
            self.self_manifest.write_bytes(previous)
            report=publication.publish(self.backup,self.candidate,'0.1.6',self.new_hash,len(self.new))
            journal=json.loads(Path(report['journal']).read_text())
            self.assertEqual(journal['baseline'],{'version':'0.1.5','sha256':self.old_hash,'size':len(self.old)})
            self.assertEqual(json.loads(self.self_manifest.read_bytes())['version'],'0.1.6')
            publication.rollback(report['journal'])
            self.assertEqual(self.alias.read_bytes(),self.old)
            self.assertEqual(self.self_manifest.read_bytes(),previous)
            self.assertEqual(self.row['launcherVersion'],'0.1.5')

    def test_rollback_requires_matching_explicit_baseline_before_loading_backup(self):
        report=self.publish()
        with patch.object(publication,'OLD_VERSION','0.1.5'),patch.object(publication,'load_backup') as loader:
            with self.assertRaisesRegex(ValueError,'explicitly pinned baseline'):
                publication.rollback(report['journal'])
        loader.assert_not_called()
        self.assertEqual(self.alias.read_bytes(),self.new)


if __name__=='__main__':unittest.main()
