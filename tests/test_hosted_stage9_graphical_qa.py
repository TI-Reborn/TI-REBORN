"""Offline adapter guards; no GUI, Frida attach, production DB or game sockets."""
import argparse
from contextlib import ExitStack,redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch,Mock

from tools import hosted_stage9_graphical_qa as qa


class GraphicalAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=(qa.SOURCE/'manifest-2026.10.08.5.json').read_bytes()
        cls.dll5=(qa.ROOT/'reports/gameplay-followup/stage1-interfaces/nvg/source/silver.dll').read_bytes()
        cls.dll6=qa.CANDIDATE.read_bytes()
        cls.exe=(qa.QA_BASE/'game-a/ti.exe').read_bytes();cls.orange=(qa.QA_BASE/'game-a/orange.dll').read_bytes()
        cls.native_cache={}

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.base=Path(self.temporary.name);self.qa_base=self.base/'copies';self.folder=self.base/'report'
        self.fixture_path=self.base/'private-fixture.json';self.fixture_data=dict(version=1,host='185.184.42.88',prefix='qsabcdef12',
            names=['qsabcdef12a','qsabcdef12b'],passwords=['Owned-Secret-A-1234','Owned-Secret-B-1234'],
            backup='/root/tio-before-surroundings-qa-owned123',key=r'C:\Users\jundu\.ssh\tio_server')
        self.fixture_path.write_text(json.dumps(self.fixture_data),encoding='utf-8')
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name,value in (('QA_BASE',self.qa_base),('FOLDER',self.folder),('FIXTURE',self.fixture_path)):
            self.stack.enter_context(patch.object(qa,name,value))
        self.roots={c:self.make_copy(c) for c in ('a','b')}

    def make_copy(self,c):
        root=self.qa_base/('game-'+c);(root/'base').mkdir(parents=True)
        (root/qa.MARKER).write_text(json.dumps(dict(schema=1,creator=qa.CREATOR,root=str(root))),encoding='utf-8')
        for name,data in (('ti.exe',self.exe),('orange.dll',self.orange),('silver.dll',self.dll5)):(root/name).write_bytes(data)
        for name in ('autoexec.cfg','config.cfg'):
            (root/'base'/name).write_bytes(b'orange_addr 185.184.42.88\r\norange_port 28512\r\nr_fullscreen 0\r\n')
        return root

    def test_exact_public_and_candidate_full_spans_are_preserved(self):
        for data in (self.dll5,self.dll6):
            (self.roots['a']/'silver.dll').write_bytes(data)
            guards=qa.native_guards(self.roots['a'])
            self.assertEqual(len(guards),16);self.assertEqual([g['name'] for g in guards],[r[0] for r in qa.original.SPANS])
            self.assertTrue(all(len(g['entry12'])==24 for g in guards))

    def test_tampered_dll_rejected_without_whitelist_expansion(self):
        data=bytearray(self.dll5);data[3000]^=1;(self.roots['a']/'silver.dll').write_bytes(data)
        with self.assertRaises(ValueError):qa.native_guards(self.roots['a'])
        self.assertNotIn(qa.nvg.NVG_BASE_SHA,qa.original.accepted_native_hashes('silver.dll'))
        self.assertNotIn(qa.CANDIDATE_SHA,qa.original.accepted_native_hashes('silver.dll'))

    def test_full_auth_span_damage_detected_even_with_mocked_release_digest(self):
        import pefile
        data=bytearray(self.dll5);pe=pefile.PE(data=data);data[pe.get_offset_from_rva(0x87ce60-0x400000)+100]^=1
        (self.roots['a']/'silver.dll').write_bytes(data)
        real_hash=qa.hashlib.sha256
        class DamagedDigest:
            def hexdigest(self):return qa.nvg.NVG_BASE_SHA
        def sha(data=b''):
            return DamagedDigest() if len(data)==len(self.dll5) else real_hash(data)
        with patch.object(qa.hashlib,'sha256',side_effect=sha):
            with self.assertRaisesRegex(ValueError,'span'):qa.native_guards(self.roots['a'])

    def test_foreign_contract_root_and_unmarked_root_rejected(self):
        for path in (self.base/'contracts-local/client-a',self.base/'ContractA',self.qa_base/'game-c'):
            with self.subTest(path=path),self.assertRaises(ValueError):qa.own_copy(path)
        (self.roots['a']/qa.MARKER).unlink()
        with self.assertRaises(ValueError):qa.own_copy(self.roots['a'])

    def test_marker_login_and_seed_endpoint_guards(self):
        marker=self.roots['a']/qa.MARKER;old=marker.read_bytes()
        marker.write_text(json.dumps(dict(schema=1,creator='other-task',root=str(self.roots['a']))))
        with self.assertRaises(ValueError):qa.own_copy(self.roots['a'])
        marker.write_bytes(old);login=self.roots['a']/'base/login.ini';login.write_bytes(b'must-not-read')
        with self.assertRaisesRegex(ValueError,'login.ini'):qa.own_copy(self.roots['a'])
        login.unlink();(self.roots['a']/'base/config.cfg').write_text('orange_addr 127.0.0.1\norange_port 28512\n')
        with self.assertRaisesRegex(ValueError,'endpoint'):qa.native_guards(self.roots['a'])

    def test_path_traversal_windows_names_and_foreign_ancestors_rejected(self):
        for relative in ('../outside','base/../../outside','C:/outside','base/NUL.txt','base/foo.','base\\bad'):
            with self.subTest(relative=relative),self.assertRaises(ValueError):qa.safe_path(self.roots['a'],relative)
        with patch.object(Path,'is_symlink',return_value=True):
            with self.assertRaises(ValueError):qa.safe_path(self.roots['a'],'silver.dll')

    def test_exact_manifest_and_only_reviewed_one_dll_successor_accepted(self):
        self.assertEqual(qa.validate_manifest(self.manifest)['version'],'2026.10.08.5')
        m=json.loads(self.manifest);m['version']='2026.10.08.6';row=next(r for r in m['files'] if r['path']=='silver.dll')
        row.update(size=len(self.dll6),sha256=qa.CANDIDATE_SHA)
        self.assertEqual(qa.validate_manifest(json.dumps(m).encode())['version'],'2026.10.08.6')
        for changed in ('news','path','seed','extra','other-resource'):
            damaged=copy.deepcopy(m)
            if changed=='news':damaged['news']=[]
            elif changed=='path':damaged['files'][0]['path']='base/../login.ini'
            elif changed=='seed':damaged['files'][0]['seed']=not damaged['files'][0]['seed']
            elif changed=='extra':damaged['files'].append(damaged['files'][0])
            else:damaged['files'][1]['sha256']='0'*64
            with self.subTest(changed=changed),self.assertRaises(ValueError):qa.validate_manifest(json.dumps(damaged).encode())

    def test_only_retained_private_fixture_is_accepted_without_printing_secrets(self):
        fixture=qa.private_fixture(self.fixture_path);self.assertEqual(len(fixture.names),2)
        with self.assertRaises(ValueError):qa.private_fixture(self.base/'foreign.json')
        damaged=dict(self.fixture_data,host='127.0.0.1');self.fixture_path.write_text(json.dumps(damaged))
        with self.assertRaises(ValueError):qa.private_fixture(self.fixture_path)

    def test_check_only_has_no_process_network_or_frida_actions(self):
        output=io.StringIO()
        with patch.object(qa,'private_fixture',return_value=Mock()),patch.object(qa.subprocess,'run',side_effect=AssertionError('process forbidden')),\
             patch.object(qa,'https',side_effect=AssertionError('network forbidden')),redirect_stdout(output):
            self.assertEqual(qa.main(['check','--copies','a']),0)
        value=json.loads(output.getvalue());self.assertEqual(value['graphical_clients_started'],0)
        self.assertEqual(value['copies'][0]['full_native_functions'],16)
        self.assertNotIn('Secret',output.getvalue())

    def test_route_014_byte_mode_and_all_other_original_guards_preserved(self):
        old=qa.tls_original.native_source(41001,41002);new=qa.native_source(41001,41002)
        self.assertEqual(new,old.replace('0x8b,0x44,0x24,0x18,0x83,0xf8,0,0xb8','0x8b,0x44,0x24,0x18,0x80,0xf8,0,0xb8'))
        self.assertIn('Production route original target differs',new)
        self.assertIn('Native function entry differs',new)
        self.assertIn('Observed character is not the expected selectable owned QA character',new)
        self.assertIn("['pointer', 'uint32', 'pointer', 'uint32'], 'mscdecl'",new)
        for ports in ((0,41002),(41001,41001),(True,41002)):
            with self.assertRaises(ValueError):qa.native_source(*ports)

    def test_changed_original_js_source_fails_closed(self):
        actual=qa.digest
        def damaged(path):return '0'*64 if Path(path).name=='hosted_graphical_qa_bridge.js' else actual(path)
        with patch.object(qa,'digest',side_effect=damaged):
            with self.assertRaises(ValueError):qa.native_source(41001,41002)

    def test_redaction_removes_credentials_and_owned_account_values(self):
        fixture=qa.private_fixture(self.fixture_path)
        value=dict(login=fixture.names[0],password=fixture.passwords[0],state=dict(name=fixture.names[1],note='x'+fixture.passwords[1]))
        public=json.dumps(qa.redact(value,fixture))
        self.assertTrue(all(secret not in public for secret in fixture.names+fixture.passwords))

    def test_sync_check_only_never_writes_or_queries_game_processes(self):
        with patch.object(qa,'https',return_value=self.manifest),patch.object(qa,'native_guards',return_value=[]),\
             patch.object(qa,'no_running_copy',side_effect=AssertionError('process query forbidden')),\
             patch.object(qa,'atomic_write',side_effect=AssertionError('write forbidden')):
            result=qa.synchronize(['a'],'candidate6',check_only=True)
        self.assertTrue(result['check_only']);self.assertEqual(result['manifest_files'],6330)
        self.assertEqual((self.roots['a']/'silver.dll').read_bytes(),self.dll5)

    def test_sync_preserves_seed_bytes_and_does_not_truncate_hardlinked_source(self):
        relative='base/shared config/test-asset.xml';target=qa.safe_path(self.roots['a'],relative);target.parent.mkdir(parents=True)
        source=self.base/'outside-asset.xml';source.write_bytes(b'original-outside');os.link(source,target)
        new=b'public-new';row=dict(path=relative,size=len(new),sha256=hashlib.sha256(new).hexdigest(),seed=False)
        rows=[dict(path=r,size=0,sha256='0'*64,seed=True) for r in qa.CONFIGS]+[row]
        value=dict(version='2026.10.08.5',files=rows)
        seeds={r:(self.roots['a']/r).read_bytes() for r in qa.CONFIGS}
        with patch.object(qa,'https',side_effect=lambda url,limit:self.manifest if url.endswith('manifest.json') else new),\
             patch.object(qa,'validate_manifest',return_value=value),patch.object(qa,'no_running_copy'):
            result=qa.synchronize(['a'],'published5',check_only=False)
        self.assertEqual(target.read_bytes(),new);self.assertEqual(source.read_bytes(),b'original-outside')
        self.assertEqual({r:(self.roots['a']/r).read_bytes() for r in qa.CONFIGS},seeds)
        self.assertTrue(Path(result['backup']).is_relative_to(self.folder))

    def test_sync_refuses_running_owned_copy_before_first_write(self):
        value=dict(version='2026.10.08.5',files=[dict(path=r,size=0,sha256='0'*64,seed=True) for r in qa.CONFIGS])
        with patch.object(qa,'https',return_value=self.manifest),patch.object(qa,'validate_manifest',return_value=value),\
             patch.object(qa,'native_guards',return_value=[]),patch.object(qa,'no_running_copy',side_effect=ValueError('running')),\
             patch.object(qa,'atomic_write') as write:
            with self.assertRaises(ValueError):qa.synchronize(['a'],'published5',check_only=False)
        write.assert_not_called()

    def test_attach_check_only_cannot_allocate_credentials_or_attach(self):
        fixture=qa.private_fixture(self.fixture_path);fixture.remote=Mock(side_effect=AssertionError('SSH forbidden'))
        args=argparse.Namespace(fixture=self.fixture_path,copies=['a'],status_a=self.base/'ready.json',launcher=qa.LAUNCHER,check_only=True)
        with patch.object(qa,'private_fixture',return_value=fixture),patch.object(qa,'native_guards',return_value=[]),\
             patch.object(qa,'readiness',return_value=dict(Pid=100,BridgePid=101,LoginPort=41001,SessionPort=41002)),\
             patch.object(qa,'Attached',side_effect=AssertionError('attach forbidden')):
            self.assertEqual(qa.observe(args)['attached'],0)
        fixture.remote.assert_not_called()

    def test_readiness_ownership_certificate_listener_and_path_guards(self):
        directory=self.folder/'readiness';directory.mkdir(parents=True);path=directory/'a.json'
        baseline=dict(Pid=101,BridgePid=102,LoginPort=41001,SessionPort=41002,EndpointCertificatesValidated=True)
        actual=dict(Game=str(self.roots['a']/'ti.exe'),Bridge=str(qa.LAUNCHER),Listeners=[
            dict(LocalAddress='127.0.0.1',LocalPort=41001,OwningProcess=102),
            dict(LocalAddress='127.0.0.1',LocalPort=41002,OwningProcess=102)])
        def check(value,process):
            path.write_text(json.dumps(value))
            with patch.object(qa,'launcher_guard',return_value=qa.LAUNCHER.absolute()),\
                 patch.object(qa.subprocess,'run',return_value=Mock(returncode=0,stdout=json.dumps(process))):
                return qa.readiness(path,self.roots['a'],qa.LAUNCHER)
        self.assertEqual(check(baseline,actual),baseline)
        for value in (dict(baseline,EndpointCertificatesValidated=False),dict(baseline,Pid=True),dict(baseline,Extra=1)):
            with self.assertRaises(ValueError):check(value,actual)
        for field,value in (('Game',str(self.base/'ContractA/ti.exe')),('Bridge',str(self.base/'other.exe'))):
            with self.assertRaises(ValueError):check(baseline,dict(actual,**{field:value}))
        damaged=copy.deepcopy(actual);damaged['Listeners'][0]['OwningProcess']=99
        with self.assertRaises(ValueError):check(baseline,damaged)
        with patch.object(qa,'launcher_guard',return_value=qa.LAUNCHER.absolute()):
            with self.assertRaises(ValueError):qa.readiness(directory/'../foreign.json',self.roots['a'],qa.LAUNCHER)


if __name__=='__main__':unittest.main()
