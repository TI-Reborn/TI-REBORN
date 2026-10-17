"""Isolated rollout/renewal guards; no real SSH, systemd, firewall or player saves."""
from contextlib import ExitStack,nullcontext,closing,redirect_stderr
from pathlib import Path
from types import SimpleNamespace
import hashlib
import io
import json
import os
import ssl
import sqlite3
import tarfile
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from deploy import renew_game_tls as renew
from tools import deploy_game_tls_remote as deploy

FIXTURES=Path(__file__).parent/'fixtures/game_tls'


class RenewalTests(unittest.TestCase):
    def test_certificate_pair_domain_and_expiry_are_validated_before_install(self):
        with patch.object(renew,'DOMAIN','localhost'):
            valid=renew.validate(FIXTURES/'valid-chain.pem',FIXTURES/'valid-key.pem')
            self.assertEqual(valid['domain'],'localhost')
            for cert,key in (('valid-chain.pem','rotated-key.pem'),('wrongsan-chain.pem','wrongsan-key.pem'),
                    ('expired-chain.pem','expired-key.pem'),('missing.pem','valid-key.pem')):
                with self.subTest(cert=cert):
                    with self.assertRaises((ValueError,OSError)):
                        renew.validate(FIXTURES/cert,FIXTURES/key)

    def test_other_certificate_lineage_does_not_install_or_reload(self):
        with patch.dict(os.environ,{'RENEWED_LINEAGE':'/etc/letsencrypt/live/unrelated.invalid'}),patch.object(renew,'install') as install:
            self.assertEqual(renew.main([]),0)
            install.assert_not_called()

    def test_immutable_generation_permissions_and_reload_failure_restore_previous_link(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            probe=folder/'probe'
            try:probe.symlink_to(folder,target_is_directory=True)
            except OSError:self.skipTest('Host does not permit directory symlinks')
            probe.unlink()
            lineage=folder/'lineage';lineage.mkdir()
            (lineage/'fullchain.pem').write_bytes((FIXTURES/'valid-chain.pem').read_bytes())
            (lineage/'privkey.pem').write_bytes((FIXTURES/'valid-key.pem').read_bytes())
            destination=folder/'tls'
            with ExitStack() as stack:
                stack.enter_context(patch.object(renew,'LINEAGE',lineage))
                stack.enter_context(patch.object(renew,'DESTINATION',destination))
                stack.enter_context(patch.object(renew,'DOMAIN','localhost'))
                stack.enter_context(patch.object(renew,'renewal_lock',return_value=nullcontext()))
                stack.enter_context(patch.object(renew.os,'geteuid',return_value=0,create=True))
                chown=stack.enter_context(patch.object(renew.os,'chown',create=True))
                stack.enter_context(patch.dict('sys.modules',{'grp':SimpleNamespace(getgrnam=lambda _:SimpleNamespace(gr_gid=4711))}))
                result=renew.install(reload_service=False)
                self.assertFalse(result['reload_requested'])
                self.assertTrue((destination/'current').is_symlink())
                first=os.readlink(destination/'current')
                self.assertEqual((destination/'current/privkey.pem').read_bytes(),(FIXTURES/'valid-key.pem').read_bytes())
                self.assertTrue(all(call.args[1:]==(0,4711) for call in chown.call_args_list))
                with patch.object(renew.subprocess,'run',side_effect=RuntimeError('Synthetic reload failure')):
                    with self.assertRaises(RuntimeError):renew.install()
                self.assertEqual(os.readlink(destination/'current'),first)


class RolloutGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.code=self.root/'code';self.code.mkdir()
        self.db=self.root/'hosted.sqlite3'
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('CREATE TABLE accounts(name TEXT)')
            db.execute("INSERT INTO accounts VALUES ('retained-account')")
            db.execute('CREATE TABLE battle_checkpoints(match_id TEXT)')
            db.execute('CREATE TABLE battle_settlement_jobs(match_id TEXT)')
        self.config=self.root/'server.toml'
        self.config.write_text('multi_account=true\ngame_port=28512\nsession_port=28513\n')
        self.launcher=self.root/'launcher.exe';self.launcher.write_bytes(b'old-launcher')
        self.client_manifest=self.root/'client-manifest.json';self.client_manifest.write_text('{}')
        self.dropin=self.root/'dropin.conf'
        self.hook=self.root/'renewal-hook'
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name,value in (('ROOT',self.code),('DATABASE',self.db),('CONFIG',self.config),
                ('LAUNCHER',self.launcher),('CLIENT_MANIFEST',self.client_manifest),('DROPIN',self.dropin),('HOOK',self.hook)):
            self.stack.enter_context(patch.object(deploy,name,value))
        self.command=self.stack.enter_context(patch.object(deploy,'command',side_effect=self.command_result))
        self.manifest={'schema':1,'files':{},'server_config_before':deploy.digest(self.config),
            'launcher_before':deploy.digest(self.launcher),'client_manifest':deploy.digest(self.client_manifest),
            'launcher_after':hashlib.sha256(b'new-launcher').hexdigest()}
        for name in deploy.ALLOWED:
            path=self.code/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('before')
            self.manifest['files'][name]={'before':deploy.digest(path),'after':hashlib.sha256(b'after').hexdigest()}

    @staticmethod
    def command_result(*args,**kwargs):
        if args[:2]==('systemctl','is-active'):return 'active'
        if args[:2]==('ss','-Hltn'):return 'LISTEN 0 32 0.0.0.0:28512 0.0.0.0:*'
        return ''

    def test_actual_file_config_launcher_and_manifest_baselines_are_guarded(self):
        deploy.verify_baseline(self.manifest)
        for path in (self.code/'server/multi.py',self.config,self.launcher,self.client_manifest):
            with self.subTest(path=path):
                before=path.read_bytes();path.write_bytes(b'changed')
                with self.assertRaises(RuntimeError):deploy.verify_baseline(self.manifest)
                path.write_bytes(before)

    def test_active_sockets_and_durable_battles_block_before_stop(self):
        with patch.object(deploy,'command',side_effect=lambda *args,**kwargs:'active' if args[0]=='systemctl' else 'ESTAB 0 0 peer' if args[:2]==('ss','-Htn') else ''):
            with self.assertRaisesRegex(RuntimeError,'Active gameplay'):deploy.verify_baseline(self.manifest)
        for table in ('battle_checkpoints','battle_settlement_jobs'):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.db)) as db,db:db.execute('INSERT INTO '+table+" VALUES ('pending')")
                with self.assertRaisesRegex(RuntimeError,'Durable gameplay'):deploy.verify_baseline(self.manifest)
                with closing(sqlite3.connect(self.db)) as db,db:db.execute('DELETE FROM '+table)
        self.assertFalse(any(call.args[:2]==('systemctl','stop') for call in self.command.call_args_list))

    def archive(self,*,extra=None):
        source=self.root/'archive-source';source.mkdir(exist_ok=True)
        for name in deploy.ALLOWED:
            path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'after')
        (source/'TIO-Launcher.exe').write_bytes(b'new-launcher')
        (source/'manifest.json').write_text(json.dumps(self.manifest))
        path=self.root/'patch.tar.gz'
        with tarfile.open(path,'w:gz') as bundle:
            for name in sorted(deploy.ALLOWED|{'manifest.json','TIO-Launcher.exe'}):bundle.add(source/name,arcname=name)
            if extra:
                fake=source/'unexpected';fake.write_bytes(b'player-data')
                bundle.add(fake,arcname=extra)
        return path

    def unpack(self,archive):
        stage=self.root/('stage-'+str(len(list(self.root.glob('stage-*')))));stage.mkdir()
        with patch.object(deploy.tempfile,'mkdtemp',return_value=str(stage)):
            return deploy.unpack(archive)

    def test_stage_allowlist_and_hashes_reject_unexpected_or_changed_payloads(self):
        stage,manifest=self.unpack(self.archive())
        self.assertEqual(manifest,self.manifest)
        self.assertEqual((stage/'server/tls.py').read_bytes(),b'after')
        with self.assertRaises(ValueError):self.unpack(self.archive(extra='data/players.sqlite3'))
        self.manifest['files']['server/tls.py']['after']='0'*64
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.unpack(self.archive())

    def test_atomic_replace_preserves_existing_owner_for_readable_configuration(self):
        source=self.root/'new-config';source.write_text('new')
        before=self.config.stat()
        with patch.object(deploy.os,'chown',create=True) as chown:
            deploy.atomic_copy(source,self.config,0o640)
        chown.assert_called_once()
        self.assertEqual(chown.call_args.args[1:],(before.st_uid,before.st_gid))
        self.assertEqual(self.config.read_text(),'new')

    def test_rollback_restores_only_code_and_config_never_hosted_database(self):
        backup=self.root/'tio-before-game-tls-test';backup.mkdir()
        for name in deploy.ALLOWED:
            path=backup/'files'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('old')
        (backup/'server.toml').write_text('old-config')
        state={'files':{name:True for name in deploy.ALLOWED},
            'system_files':{str(self.config):True,str(self.dropin):False,str(self.hook):False},
            'launcher_published':False,'firewall_added':[29512]}
        (backup/'state.json').write_text(json.dumps(state))
        # A deliberately different backup DB proves it must never be restored.
        (backup/'reservation.sqlite3').write_bytes(b'never-restore-this')
        before=self.db.read_bytes()
        actual_path=Path
        with patch.object(deploy,'Path',side_effect=lambda value: self.root if str(value)=='/root' else actual_path(value)):
            result=deploy.rollback(backup)
        self.assertFalse(result['database_restored'])
        self.assertEqual(self.db.read_bytes(),before)
        self.assertEqual(self.config.read_text(),'old-config')
        self.assertTrue(all((self.code/name).read_text()=='old' for name in deploy.ALLOWED))
        self.assertEqual(self.launcher.read_bytes(),b'old-launcher')

    def test_successful_rollout_writes_valid_tls_config_and_delays_launcher_publication(self):
        stage,manifest=self.unpack(self.archive())
        backup=self.root/'tio-before-game-tls-test';backup.mkdir()
        state={'firewall_added':[],'launcher_published':False}
        before=deploy.table_digests(self.db)
        def command(*args,**kwargs):
            if args[0]==str(self.code/'.venv/bin/python'):
                return '{"certificate_sha256":"synthetic-test-only"}'
            return self.command_result(*args,**kwargs)
        with patch.object(deploy,'backup_host',return_value=(backup,state,before)),patch.object(deploy,'command',side_effect=command):
            report=deploy.deploy(stage,manifest)
        config=tomllib.loads(self.config.read_text())
        self.assertTrue(config['tls']['enabled'])
        self.assertEqual(config['tls']['certificate'],'/etc/tio-server/tls/current/fullchain.pem')
        self.assertFalse(report['launcher_published'])
        self.assertEqual(self.launcher.read_bytes(),b'old-launcher')
        self.assertEqual(deploy.table_digests(self.db),before)

    def publication_fixture(self):
        stage,manifest=self.unpack(self.archive())
        for name in deploy.ALLOWED:(self.code/name).write_bytes(b'after')
        backup=self.root/'tio-before-game-tls-test';backup.mkdir()
        (backup/'manifest.json').write_text(json.dumps(manifest))
        (backup/'state.json').write_text('{"launcher_published":false}')
        (backup/'deployment.json').write_text('{"launcher_published":false}')
        candidate=self.root/'reviewed-launcher.exe'
        candidate.write_bytes(b'MZ'+bytes(1024*1024))
        return stage,manifest,backup,candidate

    def publication_scope(self):
        scope=ExitStack()
        actual_path=Path
        scope.enter_context(patch.object(deploy,'Path',side_effect=lambda value:self.root if str(value)=='/root' else actual_path(value)))
        scope.enter_context(patch.object(deploy,'LAUNCHER_CANDIDATE_ROOT',self.root))
        return scope

    def test_reviewed_candidate_publication_records_exact_hash_and_keeps_original_backup_manifest(self):
        stage,manifest,backup,candidate=self.publication_fixture()
        original_manifest=(backup/'manifest.json').read_bytes()
        expected=deploy.digest(candidate)
        before_db=self.db.read_bytes()
        with self.publication_scope():
            result=deploy.publish_launcher(stage,manifest,backup,launcher_candidate=candidate,launcher_sha256=expected.upper())
        self.assertEqual(deploy.digest(self.launcher),expected)
        self.assertEqual(result['launcher_sha256'],expected)
        self.assertEqual(result['reviewed_launcher_candidate']['sha256'],expected)
        self.assertEqual((backup/'manifest.json').read_bytes(),original_manifest)
        self.assertEqual(self.db.read_bytes(),before_db)
        self.assertEqual(deploy.digest(self.client_manifest),manifest['client_manifest'])

    def test_candidate_guard_failure_never_changes_public_file_or_publication_state(self):
        stage,manifest,backup,candidate=self.publication_fixture()
        public_before=self.launcher.read_bytes()
        state_before=(backup/'state.json').read_bytes()
        with self.publication_scope():
            for value,expected in ((candidate,None),(None,'0'*64),(candidate,'not-a-hash'),
                    (candidate,'0'*64),(Path('relative.exe'),deploy.digest(candidate)),
                    (FIXTURES/'valid-chain.pem',deploy.digest(candidate))):
                with self.subTest(value=value,expected=expected):
                    with self.assertRaises(ValueError):
                        deploy.publish_launcher(stage,manifest,backup,launcher_candidate=value,launcher_sha256=expected)
                    self.assertEqual(self.launcher.read_bytes(),public_before)
                    self.assertEqual((backup/'state.json').read_bytes(),state_before)

    def test_candidate_arguments_are_paired_and_exclusive_to_publication(self):
        for args in (['--launcher-candidate','/root/candidate.exe'],
                ['--publish-launcher','--launcher-candidate','/root/candidate.exe'],
                ['--launcher-candidate','/root/candidate.exe','--launcher-sha256','0'*64],
                ['--publish-launcher','--launcher-candidate','/root/candidate.exe','--launcher-sha256','wrong'],
                ['--publish-launcher','--rollback']):
            with self.subTest(args=args),redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as failure:deploy.main(args)
                self.assertEqual(failure.exception.code,2)
