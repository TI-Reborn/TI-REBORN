"""Root-only scoped portal metadata publication after launcher TLS acceptance.

The full PostgreSQL backup remains private and is never restored by this tool.
Only DownloadVersion/main is updated; accounts and other website rows are read
only. Rollback restores the four metadata fields with an exact current-row guard.
"""
from datetime import datetime,timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import uuid

DATABASE='tionline_web'
LAUNCHER=Path('/var/www/tio-client/downloads/TIO-Launcher.exe')
MANIFEST=Path('/var/www/tio-client/updates/manifest.json')
DEFAULT_BACKUP=Path('/root/tio-before-game-tls-jzzbxmdu')
GAME_VERSION='2026.10.07.4'
FIELDS=('launcherVersion','gameVersion','fileSizeBytes','updatedAt')
PSQL=['runuser','-u','postgres','--','psql','-X','--no-psqlrc','--quiet',
      '--tuples-only','--no-align','--dbname='+DATABASE,'--set=ON_ERROR_STOP=1']


def sql_json(sql,variables=None):
    args=PSQL+['--set='+key+'='+value for key,value in (variables or {}).items()]
    result=subprocess.run(args,input=sql,capture_output=True,text=True,check=True,timeout=45)
    return json.loads(result.stdout.strip())


def private_json(path,value):
    descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(descriptor,'w',encoding='utf-8') as output:
        output.write(json.dumps(value,indent=2)+'\n')
        output.flush();os.fsync(output.fileno())


def validate_backup(path):
    path=path.resolve(strict=True)
    if path.parent!=Path('/root') or not path.name.startswith('tio-before-game-tls-') or path.stat().st_uid!=0:
        raise ValueError('Expected the existing root-owned game TLS backup directory')
    return path


def full_backup(folder,tag):
    path=folder/('portal-'+tag+'.dump')
    descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(descriptor,'wb') as output:
        subprocess.run(['runuser','-u','postgres','--','pg_dump','--dbname='+DATABASE,'--format=custom'],
            stdout=output,stderr=subprocess.PIPE,check=True,timeout=120)
        output.flush();os.fsync(output.fileno())
    with path.open('rb') as source:
        if source.read(5)!=b'PGDMP':raise RuntimeError('Full PostgreSQL backup did not produce a custom-format archive')
    return path


def validate_publication(expected_hash,expected_bytes,manifest_version):
    if re.fullmatch(r'[0-9a-fA-F]{64}',expected_hash or '') is None or type(expected_bytes) is not int:
        raise ValueError('Expected launcher SHA256 and integer byte count')
    if not 1024*1024<=expected_bytes<=200*1024*1024 or not LAUNCHER.is_file() or LAUNCHER.is_symlink():
        raise ValueError('Unexpected published launcher file/size')
    if LAUNCHER.stat().st_size!=expected_bytes:
        raise ValueError('Published launcher byte count changed')
    hasher=hashlib.sha256()
    with LAUNCHER.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):hasher.update(chunk)
    if hasher.hexdigest()!=expected_hash.lower():raise ValueError('Published launcher SHA256 changed')
    if manifest_version!=GAME_VERSION or json.loads(MANIFEST.read_text())['version']!=manifest_version:
        raise ValueError('Public client manifest version differs from this reviewed publication')


def read_row():
    result=sql_json('''SELECT jsonb_build_object('row',
        (SELECT to_jsonb(d) FROM "DownloadVersion" d WHERE id='main'),
        'download_rows',(SELECT count(*) FROM "DownloadVersion"),
        'web_users',(SELECT count(*) FROM "User"));''')
    if not isinstance(result.get('row'),dict) or result['row'].get('id')!='main':
        raise ValueError('Expected the existing DownloadVersion/main row')
    return result


def replace_metadata(before,values):
    # psql quoted-literal substitutions occur outside the DO dollar quote.
    # JSON values enter transaction-local settings; no string-built SQL values.
    return sql_json(r'''BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='20s';
SELECT set_config('tio_tls.before', :'before', true) AS guard,
       set_config('tio_tls.values', :'values', true) AS replacement \gset
DO $$
DECLARE actual jsonb; replacement jsonb; affected integer;
BEGIN
 SELECT to_jsonb(d) INTO actual FROM "DownloadVersion" d WHERE id='main' FOR UPDATE;
 IF actual IS DISTINCT FROM current_setting('tio_tls.before')::jsonb THEN
   RAISE EXCEPTION 'Download metadata changed since backup';
 END IF;
 replacement := current_setting('tio_tls.values')::jsonb;
 UPDATE "DownloadVersion" SET "launcherVersion"=replacement->>'launcherVersion',
   "gameVersion"=replacement->>'gameVersion',
   "fileSizeBytes"=(replacement->>'fileSizeBytes')::bigint,
   "updatedAt"=(replacement->>'updatedAt')::timestamp(3)
 WHERE id='main';
 GET DIAGNOSTICS affected=ROW_COUNT;
 IF affected<>1 THEN RAISE EXCEPTION 'Expected exactly one download metadata update'; END IF;
END $$;
SELECT jsonb_build_object('row',(SELECT to_jsonb(d) FROM "DownloadVersion" d WHERE id='main'),
 'download_rows',(SELECT count(*) FROM "DownloadVersion"),
 'web_users',(SELECT count(*) FROM "User"),'updated_rows',1);
COMMIT;
''',{'before':json.dumps(before,separators=(',',':')),'values':json.dumps(values,separators=(',',':'))})


def publish(folder,expected_hash,expected_bytes,manifest_version):
    folder=validate_backup(folder)
    validate_publication(expected_hash,expected_bytes,manifest_version)
    tag=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    dump=full_backup(folder,tag)
    before=read_row()
    row=before['row']
    if (row.get('launcherVersion')!='0.1.2' or row.get('gameVersion')!='2026.10.06.5'
            or row.get('launcherUrl')!='/downloads/TIO-Launcher.exe'
            or row.get('fileSizeBytes')!=118601888 or not row.get('updatedAt','').startswith('2026-10-06')):
        raise ValueError('Actual DownloadVersion/main baseline requires reconciliation')
    row_backup=folder/('download-main-before-'+tag+'.json')
    private_json(row_backup,row)
    # The launcher and resource manifest must still match after the dump.
    validate_publication(expected_hash,expected_bytes,manifest_version)
    values={'launcherVersion':'0.1.3','gameVersion':manifest_version,'fileSizeBytes':expected_bytes,
            'updatedAt':datetime.now(timezone.utc).isoformat(timespec='milliseconds')}
    after=replace_metadata(row,values)
    report={'operation':'publish','database':DATABASE,'database_backup':str(dump),'row_backup':str(row_backup),
        'before':before,'after':after,'account_writes':0,'launcher_sha256':expected_hash.lower()}
    report_path=folder/('portal-download-publication-'+tag+'.json')
    private_json(report_path,report)
    return {'operation':'publish','report':str(report_path),'database_backup':str(dump),
        'updated_rows':after['updated_rows'],'web_users_before':before['web_users'],'web_users_after':after['web_users'],
        'download_rows':after['download_rows'],'account_writes':0,'launcher_sha256':expected_hash.lower(),
        'launcher_version':'0.1.3','game_version':manifest_version,'launcher_bytes':expected_bytes}


def rollback(report_path):
    if report_path.is_symlink():raise ValueError('Unexpected publication report symlink')
    report_path=report_path.resolve(strict=True)
    folder=validate_backup(report_path.parent)
    report=json.loads(report_path.read_text())
    if report.get('operation')!='publish' or report.get('database')!=DATABASE:
        raise ValueError('Expected a scoped portal publication report')
    tag=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    dump=full_backup(folder,tag)
    current=report['after']['row'];old=report['before']['row']
    if current.get('id')!='main' or old.get('id')!='main':raise ValueError('Unexpected metadata row identity')
    after=replace_metadata(current,{key:old[key] for key in FIELDS})
    return {'operation':'rollback','updated_rows':after['updated_rows'],'account_writes':0,
            'web_users':after['web_users'],'database_backup':str(dump),'database_restored':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',type=Path,default=DEFAULT_BACKUP)
    parser.add_argument('--launcher-sha256')
    parser.add_argument('--launcher-bytes',type=int)
    parser.add_argument('--manifest-version',default=GAME_VERSION)
    parser.add_argument('--rollback-report',type=Path)
    args=parser.parse_args(argv)
    if not hasattr(os,'geteuid') or os.geteuid()!=0:raise PermissionError('Run only as root on the existing VPS')
    if args.rollback_report:
        if args.launcher_sha256 is not None or args.launcher_bytes is not None:parser.error('Rollback does not publish a launcher')
        result=rollback(args.rollback_report)
    else:
        if args.launcher_sha256 is None or args.launcher_bytes is None:parser.error('Publication requires reviewed launcher SHA256 and bytes')
        result=publish(args.backup,args.launcher_sha256,args.launcher_bytes,args.manifest_version)
    print(json.dumps(result))
    return 0


if __name__=='__main__':raise SystemExit(main())
