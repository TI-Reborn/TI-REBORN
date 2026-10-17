"""Real temporary files/SQLite; no SSH, services, or production paths.

Only subprocess commands and Windows-unavailable Linux lock/owner primitives
are simulated. These tests do not validate actual Linux permissions/locking.
"""
from contextlib import closing, redirect_stdout
import base64
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

from tools.deploy_stage4_economy import DEPLOY


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


class Stage4DeploymentTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.workspace=self.root/'code';self.private=self.root/'private'
        self.database=self.root/'state/reservation.sqlite3'
        self.configuration=self.root/'etc/server.toml'
        self.unit=self.root/'etc/tio-server.service'
        for directory in (self.workspace/'tio',self.private,self.database.parent,self.configuration.parent):
            directory.mkdir(parents=True,exist_ok=True)
        self.source=self.workspace/'tio/wallets.py';self.source.write_bytes(b'START_CREDITS=10000\n')
        self.candidate=b'START_CREDITS=3000\nSTART_GOLD=0\n'
        self.configuration.write_text('[server]\nfixture=true\n')
        self.unit.write_text('[Service]\nfixture=true\n')
        self.complete=self.private/'tio-before-site-backups-fixture';self.complete.mkdir()
        (self.complete/'archive').write_bytes(b'complete pre-update backup fixture')
        with closing(sqlite3.connect(self.database)) as db,db:
            db.execute('CREATE TABLE accounts(account TEXT PRIMARY KEY)')
            db.execute("INSERT INTO accounts VALUES ('existing_player')")
            db.execute('CREATE TABLE wallets(account TEXT PRIMARY KEY,credits INTEGER,gold INTEGER)')
            db.execute("INSERT INTO wallets VALUES ('existing_player',12345,67)")
            db.execute('CREATE TABLE battle_checkpoints(match_id TEXT PRIMARY KEY)')
            db.execute('CREATE TABLE battle_settlement_jobs(match_id TEXT PRIMARY KEY)')
        self.payload=dict(complete_backup=str(self.complete),complete_backup_files={'archive':sha(self.complete/'archive')},
            guards={str(self.configuration):sha(self.configuration)},files={'tio/wallets.py':{
                'before':sha(self.source),'after':hashlib.sha256(self.candidate).hexdigest(),
                'content':base64.b64encode(self.candidate).decode('ascii')}})
        remapping={
            '/opt/tio-emulator':self.workspace,
            '/var/lib/tio-server/reservation.sqlite3':self.database,
            '/etc/tio-server/server.toml':self.configuration,
            '/etc/systemd/system/tio-server.service':self.unit,
            '/root':self.private,
        }
        self.script=DEPLOY
        for original,target in remapping.items():
            self.assertIn(original,self.script)
            self.assertTrue(target.resolve().is_relative_to(self.root))
            self.script=self.script.replace(original,target.as_posix())
        for original in remapping:self.assertNotIn(original,self.script)
        compile(self.script,'temporary-remapped-stage4-deployment','exec')
        self.active=True;self.stops=0;self.starts=0;self.commands=[];self.locks=[];self.owner_changes=[]
        self.late_battle=False;self.post_start_battle=False;self.preflight_failure=False

    def checkpoint(self,name):
        with closing(sqlite3.connect(self.database)) as db,db:
            db.execute('INSERT INTO battle_checkpoints VALUES (?)',(name,))

    def run_command(self,args,**kwargs):
        self.assertEqual(Path(kwargs['cwd']).resolve(),self.workspace)
        self.commands.append(tuple(args))
        if args[0]=='ss':output=''
        elif args[:2]==('systemctl','is-active') or list(args[:2])==['systemctl','is-active']:
            if not self.active:raise subprocess.CalledProcessError(3,args)
            output='active'
        elif list(args[:2])==['systemctl','show']:
            output='MainPID=100\nActiveState=active\nNRestarts=0\nExecMainStatus=0'
        elif list(args[:2])==['systemctl','stop']:
            self.active=False;self.stops+=1;output=''
            if self.late_battle and self.stops==1:self.checkpoint('late-before-stop')
        elif list(args[:2])==['systemctl','start']:
            self.active=True;self.starts+=1;output=''
            if self.post_start_battle and self.starts==1:self.checkpoint('new-after-start')
        elif args[0]=='runuser':
            self.assertEqual(args[-5:],('-m','server','--config',self.configuration.as_posix(),'--check'))
            if self.preflight_failure:raise subprocess.CalledProcessError(1,args)
            output='Configuration OK'
        else:raise AssertionError('Unexpected subprocess command')
        if args[0]=='ss' and '-Hltn' in args:
            output='\n'.join('LISTEN 0 64 0.0.0.0:'+str(port) for port in (28512,28513,29512,29513))
        return subprocess.CompletedProcess(args,0,stdout=output,stderr='')

    def flock(self,stream,flags):
        path=Path(stream.name).resolve();self.assertTrue(path.is_relative_to(self.root))
        self.locks.append((str(path),flags))

    def chown(self,path,uid,gid):
        resolved=Path(path).resolve();self.assertTrue(resolved.is_relative_to(self.root))
        self.owner_changes.append((str(resolved),uid,gid))

    def execute(self):
        output=io.StringIO();fake_fcntl=ModuleType('fcntl')
        fake_fcntl.flock=self.flock;fake_fcntl.LOCK_EX=1;fake_fcntl.LOCK_NB=2
        caught=None;namespace={'__name__':'temporary_stage4_deployment'}
        with patch.dict(sys.modules,{'fcntl':fake_fcntl}), patch('os.chown',self.chown,create=True), \
                patch('subprocess.run',self.run_command), patch.object(sys,'stdin',io.StringIO(json.dumps(self.payload))), \
                redirect_stdout(output):
            try:exec(self.script,namespace)
            except SystemExit as error:
                if error.code not in (None,0):caught=error
            except BaseException as error:caught=error
            finally:
                # The real remote interpreter exits after the script and
                # releases this handle. Here an exception traceback can retain
                # its globals, so explicitly close the same real temp file.
                if namespace.get('lock') is not None:namespace['lock'].close()
        report=json.loads(output.getvalue()) if output.getvalue().strip() else None
        return report,caught

    def rows(self,table):
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute('SELECT * FROM '+table).fetchall()

    def test_happy_path_preserves_every_existing_row_and_installs_only_source(self):
        report,error=self.execute();self.assertIsNone(error)
        self.assertEqual(self.source.read_bytes(),self.candidate)
        self.assertEqual((self.stops,self.starts,self.active),(1,1,True))
        self.assertEqual(self.rows('wallets'),[('existing_player',12345,67)])
        self.assertEqual((report['accounts_preserved'],report['wallets_preserved']),(1,1))
        self.assertEqual(report['tables_before'],report['tables_after'])
        self.assertTrue(report['source_parity']);self.assertFalse(report['database_restored'])
        backup=Path(report['backup']);self.assertTrue(backup.is_relative_to(self.private))
        self.assertEqual((backup/'files/tio/wallets.py').read_bytes(),b'START_CREDITS=10000\n')
        with closing(sqlite3.connect(backup/'reservation.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT * FROM wallets').fetchall(),self.rows('wallets'))
        self.assertEqual(len(self.locks),1);self.assertTrue(self.owner_changes)

    def test_stale_source_checksum_aborts_before_service_stop(self):
        self.source.write_bytes(b'START_CREDITS=9999\n')
        report,error=self.execute();self.assertIsNone(report);self.assertIsInstance(error,RuntimeError)
        self.assertEqual((self.stops,self.starts,self.active),(0,0,True))
        self.assertEqual(self.source.read_bytes(),b'START_CREDITS=9999\n')

    def test_bad_candidate_checksum_aborts_before_service_stop(self):
        self.payload['files']['tio/wallets.py']['after']='0'*64
        report,error=self.execute();self.assertIsNone(report);self.assertIsInstance(error,RuntimeError)
        self.assertEqual((self.stops,self.starts,self.active),(0,0,True))

    def test_operational_configuration_guard_aborts_before_service_stop(self):
        self.configuration.write_text('[server]\nfixture=changed\n')
        report,error=self.execute();self.assertIsNone(report);self.assertIsInstance(error,RuntimeError)
        self.assertEqual((self.stops,self.starts,self.active),(0,0,True))

    def test_complete_backup_checksum_guard_aborts_before_service_stop(self):
        (self.complete/'archive').write_bytes(b'changed backup')
        report,error=self.execute();self.assertIsNone(report);self.assertIsInstance(error,RuntimeError)
        self.assertEqual((self.stops,self.starts,self.active),(0,0,True))

    def test_late_battle_before_stop_keeps_old_source_and_restarts_old_service(self):
        self.late_battle=True
        report,error=self.execute();self.assertIsNone(report);self.assertIsInstance(error,RuntimeError)
        self.assertEqual(self.source.read_bytes(),b'START_CREDITS=10000\n')
        self.assertTrue(self.active);self.assertEqual(self.starts,1)
        self.assertEqual(self.rows('battle_checkpoints'),[('late-before-stop',)])
        self.assertEqual(self.rows('wallets'),[('existing_player',12345,67)])

    def test_new_battle_after_start_returns_attention_and_retains_candidate(self):
        self.post_start_battle=True
        report,error=self.execute();self.assertIsNone(error)
        self.assertEqual(report['status'],'attention');self.assertTrue(report['rollback_deferred'])
        self.assertEqual(self.source.read_bytes(),self.candidate)
        self.assertEqual((self.stops,self.starts,self.active),(1,1,True))
        self.assertEqual(self.rows('battle_checkpoints'),[('new-after-start',)])
        self.assertFalse(report['database_restored'])
        self.assertTrue((Path(report['backup'])/'deployment-attention.json').is_file())

    def test_preflight_failure_restores_old_source_and_restarts_without_data_restore(self):
        self.preflight_failure=True
        report,error=self.execute();self.assertIsNone(report);self.assertIsInstance(error,subprocess.CalledProcessError)
        self.assertEqual(self.source.read_bytes(),b'START_CREDITS=10000\n')
        self.assertTrue(self.active);self.assertEqual(self.starts,1)
        self.assertEqual(self.rows('wallets'),[('existing_player',12345,67)])
        self.assertFalse(self.rows('battle_checkpoints'));self.assertGreaterEqual(len(self.owner_changes),2)


if __name__=='__main__':unittest.main()
