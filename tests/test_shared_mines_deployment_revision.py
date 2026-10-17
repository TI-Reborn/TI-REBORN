"""Local revision manifest checks; no SSH or deployment execution."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import deploy_shared_mines as deploy


class SharedMinesDeploymentRevisionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.folder=self.root/'reports'/'shared-mines';self.folder.mkdir(parents=True)
        self.revision=self.folder/'revision3';self.revision.mkdir()
        self.old=dict(backup='/root/tio-before-site-backups-original',files={'reservation.sqlite3':{'sha256':'a'*64}})
        self.fresh=dict(backup='/root/tio-before-site-backups-fresh184',files={'reservation.sqlite3':{'sha256':'b'*64},'game-code.tar.gz':{'sha256':'c'*64}})
        self.original=json.dumps(self.old).encode();(self.folder/'pre-update-backup.json').write_bytes(self.original)
        (self.folder/'remote-baseline.json').write_text(json.dumps(dict(guards={'/etc/tio-server/server.toml':'d'*64})))
        self.name='server/battle_journal.py';self.target=self.root/self.name;self.target.parent.mkdir()
        self.source=b'changed_public_source=True\n';self.target.write_bytes(self.source)
        self.actual={self.name:dict(sha256=hashlib.sha256(b'old_public_source=True\n').hexdigest(),source='old_public_source=True\n')}

    def prepare(self):
        with patch.object(deploy,'ROOT',self.root),patch.object(deploy,'FOLDER',self.folder),\
             patch.object(deploy.sys,'argv',['deploy_shared_mines','prepare','--attempt','3','--files',self.name]),\
             patch.object(deploy.guarded,'remote',return_value=self.actual) as remote,redirect_stdout(io.StringIO()):
            deploy.main();remote.assert_called_once_with(deploy.guarded.INSPECT,{'files':[self.name]})
        return json.loads((self.revision/'deployment-manifest.json').read_text())

    def deploy_rejected(self,pattern):
        with patch.object(deploy,'ROOT',self.root),patch.object(deploy,'FOLDER',self.folder),\
             patch.object(deploy.sys,'argv',['deploy_shared_mines','deploy','--attempt','3']),\
             patch.object(deploy.guarded,'remote') as remote:
            with self.assertRaisesRegex(RuntimeError,pattern):deploy.main()
            remote.assert_not_called()

    def test_revision3_pins_fresh_complete_backup_and_previous_reference_survives(self):
        (self.revision/'pre-update-backup.json').write_text(json.dumps(self.fresh))
        prepared=self.prepare()
        self.assertEqual(prepared['complete_backup'],self.fresh['backup'])
        self.assertEqual(prepared['complete_backup_files'],{k:v['sha256'] for k,v in self.fresh['files'].items()})
        self.assertEqual(prepared['files'][self.name]['after'],hashlib.sha256(self.source).hexdigest())
        self.assertEqual(prepared['deployment_program_sha256'],hashlib.sha256(deploy.remote_program().encode()).hexdigest())
        self.assertEqual((self.folder/'pre-update-backup.json').read_bytes(),self.original)
        self.assertFalse((self.revision/'deployment.json').exists())

    def test_default_and_legacy_revision_without_own_backup_keep_original(self):
        with patch.object(deploy,'FOLDER',self.folder):
            self.assertEqual(deploy.complete_backup_for(self.folder),self.old)
            self.assertEqual(deploy.complete_backup_for(self.revision),self.old)
        self.assertEqual(self.prepare()['complete_backup'],self.old['backup'])
        self.assertEqual((self.folder/'pre-update-backup.json').read_bytes(),self.original)

    def test_changed_candidate_after_prepare_aborts_before_ssh(self):
        self.prepare();self.target.write_bytes(b'different_public_source=True\n')
        self.deploy_rejected('Candidate changed after review')

    def test_changed_deployment_program_pin_aborts_before_ssh(self):
        prepared=self.prepare();prepared['deployment_program_sha256']='0'*64
        (self.revision/'deployment-manifest.json').write_text(json.dumps(prepared))
        self.deploy_rejected('Deployment program changed after review')


if __name__=='__main__':unittest.main()
