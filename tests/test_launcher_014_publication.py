"""Local publication safeguards; never connect to production."""
from datetime import datetime
from contextlib import nullcontext
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import publish_launcher_014_remote as publication
from tools.prepare_launcher_publication import remote_source


class LauncherPublicationTests(unittest.TestCase):
    def setUp(self):
        self.before={'id':'main','launcherVersion':'0.1.3','launcherUrl':'/downloads/TIO-Launcher.exe',
            'gameVersion':'2026.10.07.4','fileSizeBytes':118679712,'updatedAt':'2026-10-07T15:33:23.5',
            'downloadUrl':'','windowsCompatibility':'Windows 10 / 11 (x64)'}
        self.values={'launcherVersion':'0.1.4','launcherUrl':'/downloads/TIO-Launcher-0.1.4.exe',
                     'fileSizeBytes':118679712,'updatedAt':'2026-10-07T19:40:00.100'}

    def test_only_public_launcher_fields_written(self):
        with patch.object(publication,'sql_json',return_value={}) as sql:
            publication.replace_metadata(self.before,self.values)
        statement,variables=sql.call_args.args[0],sql.call_args.args[1]
        update=statement.split(' UPDATE ')[1].split('GET DIAGNOSTICS')[0]
        self.assertNotIn('gameVersion',update)
        self.assertNotIn('"User"',update)
        self.assertNotIn('"Account"',update)
        self.assertIn('FOR UPDATE',statement)
        self.assertIn('IS DISTINCT FROM',statement)
        self.assertEqual(json.loads(variables['before']),self.before)

    def test_reject_added_game_field(self):
        with self.assertRaises(ValueError):publication.replace_metadata(self.before,{**self.values,'gameVersion':'new'})

    def test_timestamp_output_format_is_normalized(self):
        actual={**self.before,**self.values,'updatedAt':'2026-10-07T19:40:00.1'}
        self.assertTrue(publication.matches_after(actual,self.before,self.values))

    def test_reject_other_field_mutation(self):
        actual={**self.before,**self.values,'gameVersion':'other'}
        self.assertFalse(publication.matches_after(actual,self.before,self.values))

    def test_timeout_after_commit_reconciles_without_binary_rollback(self):
        actual={'row':{**self.before,**self.values}}
        with patch.object(publication,'replace_metadata',side_effect=RuntimeError),patch.object(publication,'read_row',return_value=actual):
            self.assertEqual(publication.reconcile_metadata(self.before,self.values),actual)

    def test_failed_transaction_identifies_unchanged_row(self):
        with patch.object(publication,'replace_metadata',side_effect=RuntimeError),patch.object(publication,'read_row',return_value={'row':self.before}):
            with self.assertRaisesRegex(RuntimeError,'unchanged'):publication.reconcile_metadata(self.before,self.values)

    def test_concurrent_row_is_not_compensated_blindly(self):
        other={**self.before,'launcherVersion':'0.1.5'}
        with patch.object(publication,'replace_metadata',side_effect=RuntimeError),patch.object(publication,'read_row',return_value={'row':other}):
            with self.assertRaisesRegex(RuntimeError,'concurrently'):publication.reconcile_metadata(self.before,self.values)

    def test_alias_hash_guard_blocks_competing_publisher(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);alias=folder/'alias.exe';source=folder/'candidate.exe';temporary=folder/'temporary'
            alias.write_bytes(b'competing');source.write_bytes(b'candidate');temporary.write_bytes(b'candidate')
            with patch.object(publication,'ALIAS',alias),patch.object(publication,'DOWNLOADS',folder),patch.object(publication,'stage_file',return_value=temporary):
                with self.assertRaisesRegex(ValueError,'changed'):publication.replace_alias(source,'unused',9,'previous')
            self.assertEqual(alias.read_bytes(),b'competing');self.assertFalse(temporary.exists())

    def test_private_receipt_refuses_collision(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'receipt.json';path.write_text('existing')
            with self.assertRaises(FileExistsError):publication.private_json(path,{})
            self.assertEqual(path.read_text(),'existing')

    def test_regular_file_guard_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source';path.write_bytes(b'original');link=Path(folder)/'link'
            try:link.symlink_to(path)
            except OSError:self.skipTest('Windows symlink privilege unavailable')
            with self.assertRaises(ValueError):publication.state(link)

    def test_backup_adapter_uses_real_isolated_checker_and_assets(self):
        source=remote_source(True);ast.parse(source)
        self.assertIn('checker.validate_dump(dump)',source)
        self.assertIn('checker._command',source)
        self.assertNotIn("['pg_restore','--list'",source)
        self.assertIn("folder/'client-manifest.json'",source)
        self.assertIn("folder/'publication-before.json'",source)
        self.assertIn("'website_full_isolated_restore':True",source)
        self.assertNotIn("'systemctl','restart'",source)
        self.assertNotIn("'systemctl', 'restart'",source)

    def test_readonly_inspection_has_no_backup_or_publication(self):
        source=remote_source(False);ast.parse(source)
        self.assertNotIn('mkdtemp',source)
        self.assertNotIn('UPDATE ',source)
        self.assertNotIn('shutil.copyfileobj',source)
        self.assertNotIn('validate_dump(',source)

    def test_immutable_owner_and_mode_guards(self):
        valid={'sha256':'candidate','bytes':118679712,'uid':0,'gid':0,'mode':0o644}
        for changed in ({'sha256':'different'},{'uid':987},{'gid':987},{'mode':0o666},{'bytes':1}):
            with self.subTest(changed=changed),patch.object(publication,'state',return_value={**valid,**changed}):
                with self.assertRaises(ValueError):publication.validate_immutable('unused','candidate',118679712)

    def test_rollback_checks_binary_before_writing_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);journal_path=folder/'journal.json'
            before={'metadata':{'row':self.before},'launcher':{'sha256':'old'}}
            journal_path.write_text(json.dumps({'kind':'launcher-0.1.4','before':before,'backup':str(folder),
                                               'values':self.values,'candidate_sha256':'candidate'}))
            with patch.object(publication,'publication_lock',return_value=nullcontext()),patch.object(publication,'load_backup',return_value=(folder,before)),patch.object(publication,'check_preserved'),patch.object(publication,'read_row',return_value={'row':{**self.before,**self.values}}),patch.object(publication,'state',return_value={'sha256':'competing'}),patch.object(publication,'replace_metadata') as write:
                with self.assertRaisesRegex(ValueError,'before metadata'):publication.rollback(journal_path)
                write.assert_not_called()


if __name__=='__main__':unittest.main()
