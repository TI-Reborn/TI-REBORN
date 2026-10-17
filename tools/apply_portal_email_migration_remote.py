"""Apply the bounded portal email migration after verifying hosted backups.

The game service and SQLite data are never changed. PostgreSQL compares existing
User rows inside a locked transaction; public reports contain only aggregates.
Existing reports and failed Prisma migration records are never overwritten.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_NAME = '20261009143000_email_verification'
BASELINE_NAME = '20261006213000_portal'
HOST = 'root@185.184.42.88'

SCHEMA_CHECK = r'''
DO $schema$
DECLARE
  relation oid := 'public."EmailVerification"'::regclass;
  uid smallint;
  token smallint;
  expiry smallint;
  original_id smallint;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_attribute a JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
    WHERE a.attrelid='public."User"'::regclass AND a.attname='emailVerificationRequired'
      AND NOT a.attisdropped AND a.attnotnull
      AND format_type(a.atttypid,a.atttypmod)='boolean'
      AND pg_get_expr(d.adbin,d.adrelid) IN ('false','false::boolean')
  ) THEN RAISE EXCEPTION 'Email requirement column differs from expected schema'; END IF;
  IF (SELECT count(*) FROM information_schema.columns
      WHERE table_schema='public' AND table_name='EmailVerification') <> 6
    OR EXISTS (
      SELECT 1 FROM (VALUES
        ('userId','text','NO',NULL::integer,NULL::integer),
        ('tokenHash','character','NO',64,NULL::integer),
        ('expiresAt','timestamp without time zone','NO',NULL::integer,3),
        ('sentAt','timestamp without time zone','NO',NULL::integer,3),
        ('createdAt','timestamp without time zone','NO',NULL::integer,3),
        ('consumedAt','timestamp without time zone','YES',NULL::integer,3)
      ) AS wanted(name,datatype,nullable,charlength,timeprecision)
      LEFT JOIN information_schema.columns c ON c.table_schema='public'
        AND c.table_name='EmailVerification' AND c.column_name=wanted.name
      WHERE c.column_name IS NULL OR c.data_type<>wanted.datatype OR c.is_nullable<>wanted.nullable
        OR c.character_maximum_length IS DISTINCT FROM wanted.charlength
        OR c.datetime_precision IS DISTINCT FROM wanted.timeprecision
    )
    OR NOT EXISTS (SELECT 1 FROM information_schema.columns
      WHERE table_schema='public' AND table_name='EmailVerification' AND column_name='createdAt'
        AND column_default IN ('CURRENT_TIMESTAMP','now()'))
    OR (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid=relation) <> 'tionline'
  THEN RAISE EXCEPTION 'Email proof table differs from expected schema'; END IF;
  SELECT attnum INTO uid FROM pg_attribute WHERE attrelid=relation AND attname='userId' AND NOT attisdropped;
  SELECT attnum INTO token FROM pg_attribute WHERE attrelid=relation AND attname='tokenHash' AND NOT attisdropped;
  SELECT attnum INTO expiry FROM pg_attribute WHERE attrelid=relation AND attname='expiresAt' AND NOT attisdropped;
  SELECT attnum INTO original_id FROM pg_attribute WHERE attrelid='public."User"'::regclass AND attname='id' AND NOT attisdropped;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid=relation AND contype='p' AND conkey=ARRAY[uid])
    OR NOT EXISTS (SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
      WHERE i.indrelid=relation AND c.relname='EmailVerification_tokenHash_key'
        AND i.indisunique AND i.indisvalid AND i.indisready AND i.indnkeyatts=1 AND i.indnatts=1
        AND i.indkey::text=token::text AND i.indpred IS NULL AND i.indexprs IS NULL)
    OR NOT EXISTS (SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
      WHERE i.indrelid=relation AND c.relname='EmailVerification_expiresAt_idx'
        AND i.indisvalid AND i.indisready AND i.indnkeyatts=1 AND i.indnatts=1
        AND i.indkey::text=expiry::text AND i.indpred IS NULL AND i.indexprs IS NULL)
    OR NOT EXISTS (SELECT 1 FROM pg_constraint
      WHERE conrelid=relation AND conname='EmailVerification_userId_fkey' AND contype='f'
        AND confrelid='public."User"'::regclass AND conkey=ARRAY[uid] AND confkey=ARRAY[original_id]
        AND confdeltype='c' AND confupdtype='c' AND convalidated)
  THEN RAISE EXCEPTION 'Email proof keys differ from expected schema'; END IF;
END $schema$;
'''

REMOTE = r"""
import base64, hashlib, json, os, re, stat, subprocess, sys, uuid
from datetime import datetime, timezone
from pathlib import Path
configuration=CONFIGURATION
schema_check=SCHEMA_CHECK
phase='backup verification'
operation=None
os.umask(0o077)

def require(condition, message):
    if not condition: raise RuntimeError(message)

def digest_file(path):
    result=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''): result.update(chunk)
    return result.hexdigest()

def private_file(path):
    require(path.is_file() and not path.is_symlink(), 'Missing private backup file')
    info=path.stat()
    require(info.st_uid==0 and stat.S_IMODE(info.st_mode)&0o077==0, 'Backup file permissions differ')

def game_identity():
    result=subprocess.run(['systemctl','show','tio-server','--property=MainPID','--property=NRestarts',
                           '--property=ActiveState','--property=ExecMainStartTimestampMonotonic'],
                          capture_output=True,text=True,timeout=10)
    require(result.returncode==0, 'Cannot inspect game service identity')
    return dict(line.split('=',1) for line in result.stdout.strip().splitlines() if '=' in line)

try:
    backup=Path(configuration['backup'])
    require(re.fullmatch(r'/root/tio-before-site-backups-[a-z0-9_]+',str(backup)) is not None,
            'Unexpected backup directory')
    require(backup.is_dir() and not backup.is_symlink() and backup.resolve()==backup,
            'Backup directory is unavailable')
    require(backup.stat().st_uid==0 and stat.S_IMODE(backup.stat().st_mode)&0o077==0,
            'Backup directory permissions differ')
    manifest_path=backup/'backup-manifest.json'
    private_file(manifest_path)
    manifest=json.loads(manifest_path.read_text())
    canonical=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()
    require(hashlib.sha256(canonical).hexdigest()==configuration['backup_manifest_sha256'],
            'Remote backup manifest differs from the provided report')
    require(manifest['sqlite_integrity']=='ok' and manifest['website_dump_structure_verified'] is True
            and manifest['game_restarted'] is False, 'Backup verification evidence differs')
    created=datetime.fromisoformat(manifest['created_utc'])
    require(created.tzinfo is not None and -300 <= (datetime.now(timezone.utc)-created).total_seconds() <= 86400,
            'Pre-update backup is older than 24 hours or has an invalid time')
    require(manifest['backup']==str(backup) and manifest['previous_portal_release']==configuration['previous_release'],
            'Backup release pin differs')
    required_files={'reservation.sqlite3','website.dump','game-code.tar.gz','portal-code.tar.gz','operational-config.tar.gz'}
    require(set(manifest['files'])==required_files, 'Backup file list differs')
    for name in sorted(required_files):
        path=backup/name
        private_file(path)
        expected=manifest['files'][name]
        require(type(expected['bytes']) is int and expected['bytes']>0 and path.stat().st_size==expected['bytes'],
                'Backup file size differs')
        require(digest_file(path)==expected['sha256'], 'Backup file checksum differs')
    previous=Path('/opt/tio-portal/current').resolve(strict=True)
    require(str(previous)==configuration['previous_release'], 'Portal release changed after inspection')
    require(re.fullmatch(r'/opt/tio-portal/releases/tireborn-[a-zA-Z0-9_-]+',str(previous)) is not None,
            'Unexpected portal release layout')
    game_before=game_identity()
    require(game_before.get('ActiveState')=='active' and int(game_before.get('MainPID','0'))>0,
            'Game service is not running')
    migration=base64.b64decode(configuration['migration_b64'],validate=True)
    cleanup=base64.b64decode(configuration['cleanup_b64'],validate=True)
    require(hashlib.sha256(migration).hexdigest()==configuration['migration_sha256'], 'Migration checksum differs')
    require(hashlib.sha256(cleanup).hexdigest()==configuration['cleanup_sha256'], 'Cleanup checksum differs')

    phase='private cleanup backup'
    operation=backup/'email-verification-migration'
    if not operation.exists(): operation.mkdir(mode=0o700)
    require(operation.is_dir() and not operation.is_symlink() and operation.stat().st_uid==0
            and stat.S_IMODE(operation.stat().st_mode)&0o077==0, 'Private migration folder differs')
    cleanup_target=Path('/opt/tio-portal/cleanup.sql')
    require(cleanup_target.is_file() and not cleanup_target.is_symlink(), 'Hosted cleanup file is unavailable')
    info=cleanup_target.stat()
    require(info.st_uid==0 and stat.S_IMODE(info.st_mode)&0o022==0, 'Hosted cleanup ownership differs')
    cleanup_backup=operation/'cleanup.before.sql'
    if cleanup_backup.exists():
        private_file(cleanup_backup)
        require(digest_file(cleanup_target) in {digest_file(cleanup_backup),configuration['cleanup_sha256']},
                'Hosted cleanup changed after its migration backup')
    else:
        require(digest_file(cleanup_target)!=configuration['cleanup_sha256'],
                'New cleanup is present without its previous private backup')
        with cleanup_backup.open('xb') as output:
            output.write(cleanup_target.read_bytes()); output.flush(); os.fsync(output.fileno())
        cleanup_backup.chmod(0o600)
    original_cleanup_sha256=digest_file(cleanup_backup)

    phase='locked PostgreSQL migration'
    name=configuration['migration_name']; checksum=configuration['migration_sha256']
    baseline=configuration['baseline_name']; baseline_checksum=configuration['baseline_sha256']
    require(re.fullmatch(r'[a-f0-9]{64}',checksum) and re.fullmatch(r'[a-f0-9]{64}',baseline_checksum),
            'Invalid migration digest')
    require(name=='20261009143000_email_verification' and baseline=='20261006213000_portal',
            'Unexpected migration name')
    migration_id=str(uuid.UUID(configuration['migration_id']))
    sql=r'''
BEGIN;
SET LOCAL lock_timeout='10s';
SET LOCAL statement_timeout='45s';
SET LOCAL search_path=public,pg_catalog;
DO $lock$ BEGIN PERFORM pg_catalog.pg_advisory_xact_lock(72707369); END $lock$;
DO $owners$
BEGIN
  IF (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='public."User"'::regclass) <> 'tionline'
    OR (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='public._prisma_migrations'::regclass) <> 'tionline'
    OR EXISTS (SELECT 1 FROM pg_class WHERE oid='public."User"'::regclass AND (relrowsecurity OR relforcerowsecurity))
  THEN RAISE EXCEPTION 'Unexpected portal table ownership'; END IF;
END $owners$;
SET LOCAL ROLE tionline;
LOCK TABLE public."User" IN ACCESS EXCLUSIVE MODE;
LOCK TABLE public._prisma_migrations IN SHARE ROW EXCLUSIVE MODE;
DO $history$
BEGIN
  IF EXISTS (SELECT 1 FROM public._prisma_migrations WHERE finished_at IS NULL AND rolled_back_at IS NULL)
  THEN RAISE EXCEPTION 'Unresolved Prisma migration record; refusing changes'; END IF;
  IF (SELECT count(*) FROM public._prisma_migrations WHERE migration_name='BASELINE_NAME'
        AND checksum='BASELINE_SHA256' AND finished_at IS NOT NULL AND rolled_back_at IS NULL
        AND applied_steps_count=1) <> 1
  THEN RAISE EXCEPTION 'Baseline Prisma migration differs'; END IF;
  IF EXISTS (SELECT 1 FROM public._prisma_migrations WHERE migration_name='MIGRATION_NAME')
    AND ((SELECT count(*) FROM public._prisma_migrations WHERE migration_name='MIGRATION_NAME') <> 1
      OR NOT EXISTS (SELECT 1 FROM public._prisma_migrations WHERE migration_name='MIGRATION_NAME'
          AND checksum='MIGRATION_SHA256' AND finished_at IS NOT NULL AND rolled_back_at IS NULL
          AND applied_steps_count=1))
  THEN RAISE EXCEPTION 'Existing email migration record cannot be replaced'; END IF;
END $history$;
SELECT EXISTS (SELECT 1 FROM public._prisma_migrations WHERE migration_name='MIGRATION_NAME') AS email_applied \gset
CREATE TEMP TABLE tio_email_migration_before ON COMMIT DROP AS
SELECT count(*) AS users,
  pg_catalog.sha256(convert_to(COALESCE(string_agg((to_jsonb(u)-'emailVerificationRequired')::text,E'\n' ORDER BY u.id),''),'UTF8')) AS fingerprint
FROM public."User" u;
\if :email_applied
\else
DO $fresh$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='User'
        AND column_name='emailVerificationRequired')
    OR to_regclass('public."EmailVerification"') IS NOT NULL
  THEN RAISE EXCEPTION 'Unrecorded email schema exists; refusing changes'; END IF;
END $fresh$;
MIGRATION_SQL
INSERT INTO public._prisma_migrations
  (id,checksum,finished_at,migration_name,logs,rolled_back_at,started_at,applied_steps_count)
VALUES ('MIGRATION_ID','MIGRATION_SHA256',CURRENT_TIMESTAMP,'MIGRATION_NAME',NULL,NULL,CURRENT_TIMESTAMP,1);
\endif
SCHEMA_SQL
\if :email_applied
\else
DO $legacy$
BEGIN
  IF EXISTS (SELECT 1 FROM public."User" WHERE "emailVerificationRequired" IS DISTINCT FROM false)
  THEN RAISE EXCEPTION 'Migration changed legacy email requirements'; END IF;
END $legacy$;
\endif
DO $preserve$
DECLARE after_count bigint; after_fingerprint bytea;
BEGIN
  SELECT count(*),pg_catalog.sha256(convert_to(COALESCE(string_agg((to_jsonb(u)-'emailVerificationRequired')::text,E'\n' ORDER BY u.id),''),'UTF8'))
    INTO after_count,after_fingerprint FROM public."User" u;
  IF NOT EXISTS (SELECT 1 FROM tio_email_migration_before WHERE users=after_count AND fingerprint=after_fingerprint)
  THEN RAISE EXCEPTION 'Existing User rows changed; transaction rolled back'; END IF;
END $preserve$;
SELECT json_build_object('migration_applied_already',:'email_applied'::boolean,
  'existing_users_count',users,'existing_user_rows_preserved',true,
  'email_required_default_false',true,'schema_verified',true)::text FROM tio_email_migration_before;
COMMIT;
'''
    sql=(sql.replace('BASELINE_NAME',baseline).replace('BASELINE_SHA256',baseline_checksum)
         .replace('MIGRATION_NAME',name).replace('MIGRATION_SHA256',checksum).replace('MIGRATION_ID',migration_id)
         .replace('MIGRATION_SQL',migration.decode('utf-8')).replace('SCHEMA_SQL',schema_check))
    pg=['/usr/sbin/runuser','-u','postgres','--','/usr/bin/env','-i',
        'PATH=/usr/lib/postgresql/16/bin:/usr/bin:/bin','LANG=C.UTF-8',
        '/usr/lib/postgresql/16/bin/psql','--host=/var/run/postgresql','--port=5432','--username=postgres',
        '--no-psqlrc','--quiet','--no-align','--tuples-only','--set=ON_ERROR_STOP=1','--dbname=tionline_web']
    try:
        completed=subprocess.run(pg,input=sql,text=True,capture_output=True,timeout=60)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Bounded PostgreSQL migration timed out') from None
    if completed.returncode:
        # SQL diagnostics remain solely in the root-owned migration folder.
        with (operation/('postgres-error-'+uuid.uuid4().hex+'.log')).open('x') as output:
            output.write(completed.stderr)
        raise RuntimeError('PostgreSQL migration failed; inspect private diagnostics')
    details=json.loads(completed.stdout.strip())
    require(details.get('existing_user_rows_preserved') is True and details.get('schema_verified') is True,
            'Migration result is not verified')

    phase='cleanup installation'
    require(Path('/opt/tio-portal/current').resolve(strict=True)==previous,
            'Portal release changed before cleanup installation')
    require(digest_file(cleanup_target) in {original_cleanup_sha256,configuration['cleanup_sha256']},
            'Hosted cleanup changed during migration')
    if digest_file(cleanup_target)!=configuration['cleanup_sha256']:
        temporary=cleanup_target.with_name('.cleanup-email-'+uuid.uuid4().hex+'.sql')
        try:
            with temporary.open('xb') as output:
                output.write(cleanup); output.flush(); os.fsync(output.fileno())
            temporary.chmod(stat.S_IMODE(info.st_mode)); os.chown(temporary,info.st_uid,info.st_gid)
            temporary.replace(cleanup_target)
            descriptor=os.open(str(cleanup_target.parent),os.O_DIRECTORY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)
    require(digest_file(cleanup_target)==configuration['cleanup_sha256'], 'Installed cleanup checksum differs')
    game_after=game_identity()
    result={'ok':True,'created_utc':datetime.now(timezone.utc).isoformat(),
            'migration':name,'migration_sha256':checksum,'backup':str(backup),
            'backup_verified':True,'previous_portal_release':str(previous),
            'cleanup_sha256':configuration['cleanup_sha256'],
            'previous_cleanup_sha256':original_cleanup_sha256,'previous_cleanup_backup':str(cleanup_backup),
            'cleanup_installed':True,'game_restart_requested':False,'portal_restart_requested':False,
            'game_service_identity_unchanged':game_before==game_after,**details}
    print(json.dumps(result))
except Exception:
    print(json.dumps({'ok':False,'phase':phase,'error':'Portal email migration failed; inspect private backup diagnostics',
                      'migration':configuration.get('migration_name'),'migration_sha256':configuration.get('migration_sha256'),
                      'game_restart_requested':False,'portal_restart_requested':False,
                      'remote_state_requires_recheck':True}))
    sys.exit(1)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-report', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Refusing to replace an existing migration report')
    try:
        prior = json.loads(args.backup_report.read_text(encoding='utf-8'))
        if (not isinstance(prior, dict) or prior.get('sqlite_integrity') != 'ok'
                or prior.get('website_dump_structure_verified') is not True
                or prior.get('game_restarted') is not False
                or not isinstance(prior.get('backup'), str)
                or not isinstance(prior.get('previous_portal_release'), str)):
            raise ValueError('Invalid backup evidence')
        migration = (ROOT/'web/prisma/migrations'/MIGRATION_NAME/'migration.sql').read_bytes()
        baseline = (ROOT/'web/prisma/migrations'/BASELINE_NAME/'migration.sql').read_bytes()
        cleanup = (ROOT/'web/deploy/cleanup.sql').read_bytes()
        migration.decode('utf-8'); cleanup.decode('utf-8')
        settings = {
            'backup': prior['backup'], 'previous_release': prior['previous_portal_release'],
            'backup_manifest_sha256': hashlib.sha256(json.dumps(prior,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'migration_name': MIGRATION_NAME, 'migration_id': str(uuid.uuid4()),
            'migration_sha256': hashlib.sha256(migration).hexdigest(),
            'migration_b64': base64.b64encode(migration).decode('ascii'),
            'baseline_name': BASELINE_NAME, 'baseline_sha256': hashlib.sha256(baseline).hexdigest(),
            'cleanup_sha256': hashlib.sha256(cleanup).hexdigest(),
            'cleanup_b64': base64.b64encode(cleanup).decode('ascii'),
        }
        script = REMOTE.replace('CONFIGURATION',repr(settings),1).replace('SCHEMA_CHECK',repr(SCHEMA_CHECK),1)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        # Reserve the local evidence file before any remote mutation. A failed
        # report is retained rather than overwritten on a later retry.
        with args.report.open('x',encoding='utf-8') as report:
            try:
                completed = subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',
                                            '-o','ConnectTimeout=15',HOST,'python3 -'],
                                           input=script,text=True,capture_output=True,timeout=120)
                data = json.loads(completed.stdout)
                if not isinstance(data,dict) or type(data.get('ok')) is not bool:
                    raise ValueError('Invalid remote result')
                if data['ok'] and (completed.returncode != 0
                        or data.get('migration') != MIGRATION_NAME
                        or data.get('migration_sha256') != settings['migration_sha256']
                        or data.get('cleanup_sha256') != settings['cleanup_sha256']
                        or data.get('existing_user_rows_preserved') is not True
                        or type(data.get('existing_users_count')) is not int
                        or data['existing_users_count'] < 0):
                    raise ValueError('Unverified remote result')
            except (OSError,subprocess.SubprocessError,ValueError):
                data = {'ok':False,'error':'Remote migration outcome could not be confirmed',
                        'migration':MIGRATION_NAME,'migration_sha256':settings['migration_sha256'],
                        'remote_state_requires_recheck':True,'game_restart_requested':False}
            report.write(json.dumps(data,indent=2)+'\n')
        print(json.dumps(data))
        if data['ok'] is not True:
            return 1
        return 0
    except (OSError,ValueError,TypeError,KeyError):
        parser.exit(1,'Portal migration preparation failed; no private values were printed.\n')


if __name__ == '__main__':
    raise SystemExit(main())
