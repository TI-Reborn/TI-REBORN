"""Version-aware publication packaging checks with all network calls mocked."""
import ast
from contextlib import redirect_stdout
from io import StringIO
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import run_launcher_update_publication as runner


class PublicationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.candidate=self.root/'candidate.exe'
        self.candidate.write_bytes(b'n'*(1024*1024))
        self.backup_report=self.root/'preupdate-backup.json';self.reports=self.root/'reports'
        self.baseline={'version':'0.1.5','sha256':'b'*64,'size':118737056}
        self.backup={'backup':'/root/tio-before-launcher-fresh','sqlite_integrity':'ok','website_full_isolated_restore':True,
                     'publication_baseline':{'launcher':{'sha256':'b'*64,'bytes':118737056,'mode':0o644,'uid':0,'gid':0},
                                             'metadata':{'row':{'launcherVersion':'0.1.5','launcherUrl':'/downloads/TIO-Launcher-0.1.5.exe','fileSizeBytes':118737056}}}}
        self.backup_report.write_text(json.dumps(self.backup),encoding='utf-8')
        self.args=['--candidate',str(self.candidate),'--backup-report',str(self.backup_report),
                   '--reports',str(self.reports),'--version','0.1.6']

    def inspect(self):
        with patch.object(runner.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{}',stderr='')) as command,redirect_stdout(StringIO()):
            runner.main(self.args)
        return command

    def ssh_arguments(self,call):
        tree=ast.parse(call.kwargs['input'])
        return ast.literal_eval(tree.body[1].value)

    def test_inspection_package_pins_016_and_015_baseline_with_source_snapshot(self):
        commands=self.inspect()
        package=json.loads((self.reports/'publication-package.json').read_text())
        self.assertEqual(package['version'],'0.1.6');self.assertEqual(package['baseline'],self.baseline)
        self.assertEqual(package['remote_candidate'],'/root/TIO-Launcher-0.1.6-'+package['sha256'][:12]+'.exe')
        source=Path(package['publisher_source']).read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(),package['publisher_sha256'])
        self.assertEqual(package['backup_report_sha256'],hashlib.sha256(self.backup_report.read_bytes()).hexdigest())
        arguments=self.ssh_arguments(commands.call_args)
        for option,value in (('--version','0.1.6'),('--baseline-version','0.1.5'),('--baseline-sha256','b'*64),('--baseline-bytes','118737056')):
            self.assertEqual(arguments[arguments.index(option)+1],value)

    def test_apply_reuses_pinned_source_and_passes_matching_baseline(self):
        self.inspect()
        with patch.object(runner.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{}',stderr='')) as command,redirect_stdout(StringIO()):
            runner.main([*self.args,'--apply'])
        self.assertEqual(command.call_count,1)
        self.assertEqual(command.call_args.args[0][0],'ssh')
        self.assertIn('--apply',self.ssh_arguments(command.call_args))
        self.assertEqual(self.ssh_arguments(command.call_args)[-6:],['--baseline-version','0.1.5','--baseline-sha256','b'*64,'--baseline-bytes','118737056'])

    def test_changed_source_snapshot_blocks_apply_before_network(self):
        self.inspect();source=self.reports/'publication-source.py'
        source.write_text(source.read_text()+'\n# changed after inspection\n',encoding='utf-8')
        with patch.object(runner.subprocess,'run') as command,self.assertRaisesRegex(ValueError,'snapshot changed'):
            runner.main([*self.args,'--apply'])
        command.assert_not_called()

    def test_changed_package_version_blocks_apply_before_network(self):
        self.inspect();path=self.reports/'publication-package.json';package=json.loads(path.read_text())
        package['version']='0.1.7';path.write_text(json.dumps(package),encoding='utf-8')
        with patch.object(runner.subprocess,'run') as command,self.assertRaisesRegex(ValueError,'version'):
            runner.main([*self.args,'--apply'])
        command.assert_not_called()

    def test_backup_metadata_mismatch_blocks_staging(self):
        self.backup['publication_baseline']['metadata']['row']['fileSizeBytes']=1
        self.backup_report.write_text(json.dumps(self.backup),encoding='utf-8')
        with patch.object(runner.subprocess,'run') as command,self.assertRaisesRegex(ValueError,'disagree'):
            runner.main(self.args)
        command.assert_not_called();self.assertFalse(self.reports.exists())

    def test_older_target_version_blocks_staging(self):
        args=[*self.args[:-1],'0.1.5']
        with patch.object(runner.subprocess,'run') as command,self.assertRaisesRegex(ValueError,'newer'):
            runner.main(args)
        command.assert_not_called();self.assertFalse(self.reports.exists())


if __name__=='__main__':unittest.main()
