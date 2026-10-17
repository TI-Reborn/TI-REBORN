"""Publication guards and private backup ordering without running PostgreSQL."""
from contextlib import ExitStack
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from tools import publish_game_tls_download_metadata as metadata


class MetadataPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.launcher=self.root/'launcher.exe';self.launcher.write_bytes(b'MZ'+bytes(1024*1024))
        self.manifest=self.root/'manifest.json';self.manifest.write_text('{"version":"2026.10.07.4"}')
        self.hash=hashlib.sha256(self.launcher.read_bytes()).hexdigest()
        self.size=self.launcher.stat().st_size
        self.old={'id':'main','launcherVersion':'0.1.2','gameVersion':'2026.10.06.5',
            'launcherUrl':'/downloads/TIO-Launcher.exe','downloadUrl':'preserved-url',
            'windowsCompatibility':'preserved-description','fileSizeBytes':118601888,'updatedAt':'2026-10-06T21:30:00'}
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(metadata,'LAUNCHER',self.launcher))
        self.stack.enter_context(patch.object(metadata,'MANIFEST',self.manifest))
        self.stack.enter_context(patch.object(metadata,'validate_backup',return_value=self.root))

    def test_wrong_published_binary_size_hash_or_manifest_blocks_before_database_backup_or_queries(self):
        with patch.object(metadata,'full_backup') as backup,patch.object(metadata,'read_row') as read:
            for expected,size,version in (('0'*64,self.size,metadata.GAME_VERSION),
                    (self.hash,self.size+1,metadata.GAME_VERSION),(self.hash,self.size,'2026.10.06.5'),
                    ('bad',self.size,metadata.GAME_VERSION)):
                with self.subTest(expected=expected,size=size,version=version):
                    with self.assertRaises(ValueError):metadata.publish(self.root,expected,size,version)
            backup.assert_not_called();read.assert_not_called()

    def test_full_backup_and_old_row_file_exist_before_scoped_mutation_and_accounts_are_untouched(self):
        dump=self.root/'full.dump';dump.write_bytes(b'PGDMP synthetic private test backup')
        def update(before,values):
            self.assertTrue(dump.exists())
            row_files=list(self.root.glob('download-main-before-*.json'))
            self.assertEqual(len(row_files),1)
            self.assertEqual(json.loads(row_files[0].read_text()),self.old)
            self.assertEqual(before,self.old)
            self.assertEqual(set(values),set(metadata.FIELDS))
            return {'row':dict(before,**values),'download_rows':1,'web_users':7,'updated_rows':1}
        with (patch.object(metadata,'full_backup',return_value=dump),
                patch.object(metadata,'read_row',return_value={'row':self.old,'download_rows':1,'web_users':7}),
                patch.object(metadata,'replace_metadata',side_effect=update) as replace):
            report=metadata.publish(self.root,self.hash,self.size,metadata.GAME_VERSION)
        self.assertEqual(report['updated_rows'],1)
        self.assertEqual(report['account_writes'],0)
        private=json.loads(Path(report['report']).read_text())
        self.assertEqual(private['after']['row']['launcherUrl'],self.old['launcherUrl'])
        self.assertEqual(private['after']['row']['downloadUrl'],self.old['downloadUrl'])
        self.assertEqual(private['after']['row']['windowsCompatibility'],self.old['windowsCompatibility'])
        self.assertEqual(report['web_users_before'],report['web_users_after'])
        replace.assert_called_once()

    def test_metadata_changed_since_review_is_rejected_without_update(self):
        changed=dict(self.old,launcherVersion='0.1.4')
        with (patch.object(metadata,'full_backup',return_value=self.root/'full.dump'),
                patch.object(metadata,'read_row',return_value={'row':changed}),patch.object(metadata,'replace_metadata') as replace):
            with self.assertRaises(ValueError):metadata.publish(self.root,self.hash,self.size,metadata.GAME_VERSION)
        replace.assert_not_called()

    def test_rollback_guards_exact_current_metadata_and_restores_only_four_fields(self):
        new=dict(self.old,launcherVersion='0.1.3',gameVersion=metadata.GAME_VERSION,fileSizeBytes=self.size,updatedAt='2026-10-07T17:00:00')
        report=self.root/'publication.json'
        report.write_text(json.dumps({'operation':'publish','database':metadata.DATABASE,'before':{'row':self.old},'after':{'row':new}}))
        with (patch.object(metadata,'full_backup',return_value=self.root/'fresh-before-rollback.dump'),
                patch.object(metadata,'replace_metadata',return_value={'row':self.old,'updated_rows':1,'web_users':7}) as replace):
            result=metadata.rollback(report)
        self.assertEqual(replace.call_args.args,(new,{key:self.old[key] for key in metadata.FIELDS}))
        self.assertFalse(result['database_restored'])
        self.assertEqual(result['account_writes'],0)
