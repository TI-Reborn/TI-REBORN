"""Operator capture wrapper tests: no SSH, no real credentials or plaintext disk.

DPAPI/capture are simulated; the existing archive verifier and SQLite in-memory
restore execute against a complete synthetic platform bundle.
"""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import capture_shared_mines_recovery as capture

SOURCE_FILES=(
    'server/battle_events.py','server/battle_journal.py','server/battle_reconnect.py',
    'server/mine_arena.py','server/team_arena.py','tio/arena_service.py',
    'tio/battle_rewards.py','tio/clans.py','tio/crystal_market.py','tio/mine_claims.py',
    'tio/mine_map.py','tio/mining.py','tio/protocol/mining.py',
    'tools/manage_mine_claims.py','tools/mining_scene.py')
MARKER='SYNTHETIC_PRIVATE_VALUE_MUST_NOT_BE_LOGGED'


class SharedMinesRecoveryCaptureTests(unittest.TestCase):
    def setUp(self):
        from tests.test_offsite_backup_windows import OffsiteBackupTests
        self.case=OffsiteBackupTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.report=self.case.directory/'reports';self.report.mkdir()
        self.case.files['config/tio-portal/portal.env']=MARKER.encode()
        self.expected={}
        for name in SOURCE_FILES:
            raw=('Synthetic deployed source '+name).encode()
            self.case.files['game/'+name]=raw;self.expected[name]=hashlib.sha256(raw).hexdigest()
        self.deployment=dict(source_parity=True,source_sha256=self.expected)
        self.write_deployment()

    def write_deployment(self):
        (self.report/'deployment.json').write_text(json.dumps(self.deployment))

    def invoke(self,argv=()):
        payload=self.case.payload()
        captured=dict(status='captured',path=str(self.case.directory/'copy.dpapi'),accounts=2,
            encrypted_bytes=len(payload)+len(capture.backup.MAGIC),bundle_sha256=hashlib.sha256(payload).hexdigest())
        stdout=io.StringIO()
        with patch.object(capture,'REPORT',self.report),patch.object(capture.subprocess,'run',return_value=SimpleNamespace(
                returncode=0,stdout=json.dumps(captured),stderr='')) as run,\
             patch.object(capture.backup,'_read_encrypted',return_value=capture.backup.MAGIC+payload),\
             patch.object(capture.backup,'crypt',side_effect=lambda data,**kwargs:data),redirect_stdout(stdout):
            error=None
            try:capture.main(argv)
            except SystemExit as e:error=e
        return stdout.getvalue(),error,run

    def test_all_fifteen_deployed_paths_verified_and_private_bytes_stay_in_memory(self):
        output,error,run=self.invoke();self.assertIsNone(error);run.assert_called_once()
        verified=json.loads((self.report/'offsite-verified.json').read_text())
        self.assertTrue(verified['passed']);self.assertEqual(verified['deployed_source_files'],15)
        self.assertEqual(verified['source_sha256'],self.expected)
        self.assertEqual(verified['verified_restore'],['in-memory SQLite','remote isolated PostgreSQL'])
        self.assertFalse(verified['local_plaintext_written']);self.assertNotIn(MARKER,output)
        for file in self.report.iterdir():
            self.assertTrue(file.name.endswith('.json'));self.assertNotIn(MARKER,file.read_text())
        self.assertFalse((self.case.directory/'copy.dpapi').exists())

    def test_one_consistent_archive_source_change_fails_deployment_parity(self):
        self.case.files['game/server/mine_arena.py']=b'Different synthetic deployed revision'
        output,error,_=self.invoke();self.assertEqual(error.code,1)
        verified=json.loads((self.report/'offsite-verified.json').read_text())
        self.assertEqual(verified['integrity'],'ok');self.assertFalse(verified['deployed_source_parity'])
        self.assertFalse(verified['passed']);self.assertNotIn(MARKER,output)

    def test_invalid_or_missing_deployment_record_aborts_before_capture(self):
        with patch.object(capture,'REPORT',self.report),patch.object(capture.subprocess,'run') as run:
            for bad in ({'source_parity':True,'source_sha256':{}},
                        {'source_parity':False,'source_sha256':self.expected},
                        {'source_parity':True,'source_sha256':{'../escape':'0'*64}},
                        {'source_parity':True,'source_sha256':{'server/mine_arena.py':'invalid'}}):
                with self.subTest(bad=bad):
                    (self.report/'deployment.json').write_text(json.dumps(bad))
                    with self.assertRaises(ValueError):capture.main()
            (self.report/'deployment.json').unlink()
            with self.assertRaises(FileNotFoundError):capture.main()
            run.assert_not_called()

    def test_prior_reports_are_preserved_before_any_remote_capture(self):
        prior=self.report/'offsite-verified.json';prior.write_text('Earlier verified evidence')
        with patch.object(capture,'REPORT',self.report),patch.object(capture.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'Preserve'):capture.main()
            run.assert_not_called()
        self.assertEqual(prior.read_text(),'Earlier verified evidence')

    def test_post_fix_manifest_and_prefix_preserve_original_evidence(self):
        original=(self.report/'deployment.json').read_bytes()
        self.case.files['game/server/battle_journal.py']=b'Synthetic verified post-fix source'
        final=dict(self.expected,**{'server/battle_journal.py':hashlib.sha256(self.case.files['game/server/battle_journal.py']).hexdigest()})
        path=self.report/'deployment-final.json';path.write_text(json.dumps(dict(source_parity=True,source_sha256=final)))
        old={'offsite-capture.json':'Earlier capture evidence','offsite-verified.json':'Earlier verification evidence'}
        for name,text in old.items():(self.report/name).write_text(text)
        _,error,_=self.invoke(['--deployment',str(path),'--output-prefix','post-fix-offsite'])
        self.assertIsNone(error)
        verified=json.loads((self.report/'post-fix-offsite-verified.json').read_text())
        self.assertTrue(verified['passed']);self.assertEqual(verified['source_sha256'],final)
        self.assertEqual(verified['deployed_source_files'],15)
        for name,text in old.items():self.assertEqual((self.report/name).read_text(),text)
        self.assertEqual((self.report/'deployment.json').read_bytes(),original)

    def test_unsafe_prefix_and_outside_manifest_abort_before_capture(self):
        outside=self.case.directory/'outside.json';outside.write_text(json.dumps(self.deployment))
        with patch.object(capture,'REPORT',self.report),patch.object(capture.subprocess,'run') as run:
            for prefix in ('../escape','post/fix','Uppercase','', 'a'*65):
                with self.subTest(prefix=prefix),self.assertRaises(ValueError):capture.main(['--output-prefix',prefix])
            with self.assertRaisesRegex(ValueError,'public report path'):capture.main(['--deployment',str(outside)])
            run.assert_not_called()


if __name__=='__main__':unittest.main()
