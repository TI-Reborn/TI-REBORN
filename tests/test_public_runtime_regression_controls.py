"""Regression runner boundaries: no SSH, hosted saves or real credentials."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import verify_public_runtime_regression as verify


class PublicRegressionControls(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.folder=self.root/'report';self.folder.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(verify,'ROOT',self.root).start()
        patch.object(verify,'FOLDER',self.folder).start()
        patch.object(verify,'BASE_FOLDER',self.folder).start()

    def archive(self,name,raw=b'data'):
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w:gz') as tar:
            member=tarfile.TarInfo(name);member.size=len(raw);tar.addfile(member,io.BytesIO(raw))
        return stream.getvalue()

    def test_snapshot_archive_refuses_parent_and_absolute_paths(self):
        for name in ('../outside.py','/absolute.py','C:/absolute.py','C:\\absolute.py'):
            with self.subTest(name=name),self.assertRaises(ValueError):
                verify.extract(self.archive(name),self.folder/'copy')
        self.assertFalse((self.root/'outside.py').exists())

    def test_local_runtime_fixture_cannot_replace_hosted_snapshot(self):
        original=b'original public runtime\n';local=b'private local runtime\n'
        (self.folder/'snapshot/server').mkdir(parents=True)
        (self.folder/'snapshot/server/multi.py').write_bytes(original)
        (self.root/'server').mkdir();(self.root/'server/multi.py').write_bytes(local)
        (self.root/'config').mkdir();(self.root/'config/server.toml').write_text('game_port=30001\n')
        (self.folder/'test-snapshot/tests').mkdir(parents=True)
        test=self.folder/'test-snapshot/tests/test_minimal.py';test.write_text('import unittest\nimport test_shared_fixture\n')
        helper=test.with_name('test_shared_fixture.py');helper.write_text('fixture_value=1\n')
        source={'server/multi.py':verify.sha(original)}
        (self.folder/'snapshot.json').write_text(json.dumps({'source_sha256':source}))
        (self.folder/'plan.json').write_text(json.dumps({'selected_modules':['test_minimal'],
            'test_source_sha256':{'tests/test_minimal.py':verify.sha(test.read_bytes()),
                                 'tests/test_shared_fixture.py':verify.sha(helper.read_bytes())}}))
        with patch.object(verify,'FIXTURES',('server/multi.py',)),patch.object(verify,'TEST_HELPERS',()):
            raw,fixtures=verify.bundle()
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as tar:
            self.assertEqual(tar.extractfile('server/multi.py').read(),original)
            self.assertEqual(tar.extractfile('tests/test_shared_fixture.py').read(),helper.read_bytes())
        self.assertEqual(fixtures['server/multi.py']['origin'],'hosted snapshot')
        self.assertNotIn(local,raw)

    def test_resume_normalizes_subtest_ids_and_keeps_initial_failure_evidence(self):
        first=self.folder/'hosted-isolated.json';first.write_text('{"passed":false}\n')
        saved=first.read_bytes()
        (self.folder/'hosted-test-events.jsonl').write_text('\n'.join(json.dumps(row) for row in (
            {'test':'test_a.C.test_one','outcome':'passed'},
            {'test':"test_a.C.test_two (town=11, level=4)",'outcome':'failure'})))
        self.assertEqual(verify.completed_ids(),{'test_a.C.test_one','test_a.C.test_two'})
        self.assertEqual(first.read_bytes(),saved)

    def test_repeated_initial_run_refuses_before_any_network_call(self):
        (self.folder/'hosted-isolated.json').write_text('{"passed":false}')
        with patch.object(verify,'remote') as network,self.assertRaises(ValueError):verify.run_action()
        network.assert_not_called()

    def candidate(self,name,raw=b'public=1\n',*,source='runtime.py'):
        parent=self.root/'reports/gameplay-followup/stage1-interfaces/candidate';parent.mkdir(parents=True)
        (parent/'runtime.py').write_bytes(raw)
        (self.folder/'snapshot.json').write_text(json.dumps({'source_sha256':{}}))
        (parent/'candidate-manifest.json').write_text(json.dumps({'files':{name:
            {'source':source,'before':None,'sha256':verify.sha(raw)}}}))
        return parent

    def test_candidate_refuses_save_files_and_private_runtime_without_network(self):
        for name in ('data/players.sqlite3','tio/pve_contracts.py'):
            with self.subTest(name=name):
                parent=self.candidate(name)
                with patch.object(verify,'remote') as network,self.assertRaises(ValueError):
                    verify.prepare_candidate(parent)
                network.assert_not_called()
                self.assertFalse((parent/'public-regression-candidate').exists())
                __import__('shutil').rmtree(parent)

    def test_candidate_refuses_unconfined_source_before_creating_stage(self):
        parent=self.candidate('server/public.py',source='../../../../outside.py')
        with self.assertRaises(ValueError):verify.prepare_candidate(parent)
        self.assertFalse((parent/'public-regression-candidate').exists())

    def test_candidate_refuses_hidden_private_import_before_creating_stage(self):
        parent=self.candidate('server/public.py',raw=b'from tio.pve_contracts import ContractStore\n')
        with self.assertRaisesRegex(ValueError,'private local runtime'):verify.prepare_candidate(parent)
        self.assertFalse((parent/'public-regression-candidate').exists())

    def test_focused_local_modules_cannot_bypass_public_plan(self):
        (self.folder/'snapshot.json').write_text('{}')
        (self.folder/'plan.json').write_text(json.dumps({'selected_modules':['test_public']}))
        for modules in (['test_contract'],['test_public','test_public'],[]):
            with self.subTest(modules=modules),patch.object(verify,'bundle') as builder,self.assertRaises(ValueError):
                verify.local_action(modules=modules)
            builder.assert_not_called()

    def test_rating_candidate_paths_remain_exact_and_confined(self):
        ratings=self.root/'reports/gameplay-followup/stage4-ratings'
        for name in ('validation1','validation2','validation3','validation4','final'):
            self.assertEqual(verify.candidate_folder(ratings/name),ratings/name)
        for name in ('validation1','validation2','final'):
            self.assertEqual(verify.candidate_folder(ratings/'portal'/name),ratings/'portal'/name)
        for path in (ratings/'private',ratings/'portal/private',ratings/'portal/validation1/private','reports/gameplay-followup/other','reports/unrestricted'):
            with self.assertRaises(ValueError):verify.candidate_folder(self.root/path if isinstance(path,str) else path)


if __name__=='__main__':unittest.main()
