"""Root-only, guarded launcher 0.1.4 publication; no game code or DB restore.

Publishes one immutable EXE and the current alias, then updates only the public
DownloadVersion/main launcher fields. A durable journal supports guarded
rollback. Run through reviewed SSH stdin; do not install this tool as a service.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

DOWNLOADS=Path('/var/www/tio-client/downloads')
ALIAS=DOWNLOADS/'TIO-Launcher.exe'
IMMUTABLE=DOWNLOADS/'TIO-Launcher-0.1.4.exe'
MANIFEST=Path('/var/www/tio-client/updates/manifest.json')
OLD_HASH='8a34ea68124eebfb6ded5f2c9d8c96dee85befb9eb99b5efb57d5dea708b4d52'
OLD_BYTES=118679712
FIELDS=('launcherVersion','launcherUrl','fileSizeBytes','updatedAt')
MIN_BYTES,MAX_BYTES=1024*1024,200*1024*1024
PG='/usr/lib/postgresql/16/bin/psql'
ENV={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C.UTF-8'}


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()


def state(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or any(p.is_symlink() for p in path.parents):
        raise ValueError('Expected a regular publication file without symlink parents')
    info=path.stat()
    return {'sha256':digest(path),'bytes':info.st_size,'mode':info.st_mode&0o777,
            'uid':info.st_uid,'gid':info.st_gid}


def private_json(path,value):
    descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
        stream.write(json.dumps(value,indent=2)+'\n');stream.flush();os.fsync(stream.fileno())
    sync_directory(Path(path).parent)


def sync_directory(path):
    descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def command(arguments):
    try:return subprocess.run(arguments,check=True,capture_output=True,text=True,env=ENV,timeout=45).stdout.strip()
    except (OSError,subprocess.SubprocessError):raise RuntimeError('Publication command failed; private output suppressed') from None


def preserved():
    services={}
    for name in ('tio-server','tio-game-api','tio-portal'):
        output=command(['/usr/bin/systemctl','show',name,'-p','MainPID','-p','NRestarts','-p','ActiveState'])
        services[name]=dict(line.split('=',1) for line in output.splitlines() if '=' in line)
    return {'client_manifest':state(MANIFEST),'client_version':json.loads(MANIFEST.read_text())['version'],
            'portal_release':str(Path('/opt/tio-portal/current').resolve(strict=True)),
            'services':services,'configuration':{name:state(name) for name in
            ('/etc/tio-server/server.toml','/etc/tio-portal/portal.env','/etc/nginx/snippets/tio-updates.conf')}}


def sql_json(sql,variables=None):
    arguments=['/usr/sbin/runuser','-u','postgres','--','/usr/bin/env','-i',
        'PATH=/usr/lib/postgresql/16/bin:/usr/bin:/bin','LANG=C.UTF-8',PG,
        '--host=/var/run/postgresql','--port=5432','--username=postgres','-X',
        '--no-psqlrc','--quiet','--no-align','--tuples-only','--dbname=tionline_web','--set=ON_ERROR_STOP=1']
    arguments+=['--set='+key+'='+value for key,value in (variables or {}).items()]
    try:
        result=subprocess.run(arguments,input=sql,check=True,capture_output=True,text=True,env=ENV,timeout=45)
        return json.loads(result.stdout.strip())
    except (OSError,subprocess.SubprocessError,ValueError):
        raise RuntimeError('Public metadata operation failed; private output suppressed') from None


def read_row():
    result=sql_json('''SELECT jsonb_build_object('row',(SELECT to_jsonb(d) FROM "DownloadVersion" d WHERE id='main'),
      'download_rows',(SELECT count(*) FROM "DownloadVersion"),'web_users',(SELECT count(*) FROM "User"));''')
    if not isinstance(result.get('row'),dict) or result['row'].get('id')!='main':raise ValueError('Missing public metadata row')
    return result


def replace_metadata(before,values):
    if set(values)!=set(FIELDS):raise ValueError('Only launcher fields may change')
    return sql_json(r'''BEGIN;
SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='20s';
SELECT set_config('tio_launcher.before', :'before', true) AS guard,
       set_config('tio_launcher.values', :'values', true) AS replacement \gset
DO $$
DECLARE actual jsonb; replacement jsonb; affected integer;
BEGIN
 SELECT to_jsonb(d) INTO actual FROM "DownloadVersion" d WHERE id='main' FOR UPDATE;
 IF actual IS DISTINCT FROM current_setting('tio_launcher.before')::jsonb THEN
   RAISE EXCEPTION 'Public download metadata changed';
 END IF;
 replacement:=current_setting('tio_launcher.values')::jsonb;
 UPDATE "DownloadVersion" SET "launcherVersion"=replacement->>'launcherVersion',
   "launcherUrl"=replacement->>'launcherUrl',"fileSizeBytes"=(replacement->>'fileSizeBytes')::bigint,
   "updatedAt"=(replacement->>'updatedAt')::timestamp(3) WHERE id='main';
 GET DIAGNOSTICS affected=ROW_COUNT;
 IF affected<>1 THEN RAISE EXCEPTION 'Expected exactly one metadata row'; END IF;
END $$;
COMMIT;
SELECT jsonb_build_object('row',(SELECT to_jsonb(d) FROM "DownloadVersion" d WHERE id='main'),
 'download_rows',(SELECT count(*) FROM "DownloadVersion"),'web_users',(SELECT count(*) FROM "User"));
''',{'before':json.dumps(before,separators=(',',':')),'values':json.dumps(values,separators=(',',':'))})


def matches_after(row,before,values):
    expected={**before,**values}
    actual=dict(row)
    try:
        actual['updatedAt']=datetime.fromisoformat(actual['updatedAt'])
        expected['updatedAt']=datetime.fromisoformat(expected['updatedAt'])
    except (KeyError,TypeError,ValueError):return False
    return actual==expected


def load_backup(folder):
    folder=Path(folder)
    if (folder.is_symlink() or folder.parent!=Path('/root') or not folder.name.startswith('tio-before-launcher-')
            or folder.stat().st_uid!=0 or folder.stat().st_mode&0o077):raise ValueError('Expected private root launcher backup')
    before=json.loads((folder/'publication-before.json').read_text())
    receipt=json.loads((folder/'backup-manifest.json').read_text())
    if receipt.get('sqlite_integrity')!='ok' or receipt.get('website_full_isolated_restore') is not True:
        raise ValueError('Consistent database backup and isolated PostgreSQL restore are required')
    for name in ('reservation.sqlite3','website.dump','game-code.tar.gz','portal-code.tar.gz',
                 'operational-config.tar.gz','TIO-Launcher.exe','client-manifest.json','publication-before.json'):
        actual=state(folder/name); expected=receipt['files'][name]
        if actual['sha256']!=expected['sha256'] or actual['bytes']!=expected['bytes']:
            raise ValueError('Private prepublication backup changed')
    if (before['launcher']['sha256']!=OLD_HASH or before['launcher']['bytes']!=OLD_BYTES
            or before['launcher']['uid']!=0 or before['launcher']['gid']!=0 or before['launcher']['mode']!=0o644):
        raise ValueError('Expected reviewed 0.1.3 binary baseline')
    row=before['metadata']['row']
    if row['launcherVersion']!='0.1.3' or row['launcherUrl']!='/downloads/TIO-Launcher.exe' or row['fileSizeBytes']!=OLD_BYTES:
        raise ValueError('Expected reviewed 0.1.3 metadata baseline')
    return folder,before


def check_preserved(before):
    current=preserved()
    if any(current[key]!=before[key] for key in current):raise ValueError('Manifest, release, service or configuration changed')


def inspect(folder,candidate,expected,size):
    folder,before=load_backup(folder)
    if not re.fullmatch('[0-9a-f]{64}',expected or '') or type(size) is not int or not MIN_BYTES<=size<=MAX_BYTES:
        raise ValueError('Reviewed hash and bounded byte count are required')
    candidate=Path(candidate)
    if candidate.parent!=Path('/root') or candidate.stat().st_uid!=0:raise ValueError('Candidate must be a direct root-owned /root file')
    if state(candidate)['sha256']!=expected or candidate.stat().st_size!=size:raise ValueError('Reviewed candidate differs')
    if state(ALIAS)!=before['launcher'] or read_row()['row']!=before['metadata']['row']:
        raise ValueError('Current alias or metadata differs from backup')
    check_preserved(before)
    if IMMUTABLE.exists() or IMMUTABLE.is_symlink():
        validate_immutable(IMMUTABLE,expected,size)
    return folder,before


def validate_immutable(path,expected,size):
    actual=state(path)
    if (actual['sha256']!=expected or actual['bytes']!=size or actual['uid']!=0
            or actual['gid']!=0 or actual['mode']!=0o644):
        raise ValueError('Immutable version file differs in content, ownership or permissions')


def stage_file(source,expected,size):
    descriptor,name=tempfile.mkstemp(prefix='.tio-launcher-',dir=DOWNLOADS)
    path=Path(name)
    try:
        with os.fdopen(descriptor,'wb') as output,Path(source).open('rb') as stream:
            shutil.copyfileobj(stream,output,1024*1024);output.flush();os.fsync(output.fileno())
        actual=state(path)
        if actual['sha256']!=expected or actual['bytes']!=size:raise ValueError('Source changed while staging')
        path.chmod(0o644);os.chown(path,0,0)
        return path
    except BaseException:
        path.unlink(missing_ok=True);raise


def replace_alias(source,expected,size,guard):
    temporary=stage_file(source,expected,size)
    try:
        if state(ALIAS)['sha256']!=guard:raise ValueError('Current alias changed during publication')
        os.replace(temporary,ALIAS);sync_directory(DOWNLOADS)
    finally:temporary.unlink(missing_ok=True)


@contextmanager
def publication_lock():
    import fcntl
    descriptor=os.open('/root/tio-launcher-publication.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB);yield
    finally:os.close(descriptor)


def reconcile_metadata(before,values):
    try:
        after=replace_metadata(before,values)
        if not matches_after(after['row'],before,values):raise RuntimeError('Unexpected postpublication metadata')
        return after
    except Exception:
        # A timeout may occur after COMMIT. Re-read before compensating the EXE.
        actual=read_row()
        if matches_after(actual['row'],before,values):return actual
        if actual['row']==before:raise RuntimeError('Metadata unchanged; guarded EXE rollback is allowed') from None
        raise RuntimeError('Metadata changed concurrently; preserve journal and binaries for review') from None


def publish(folder,candidate,expected,size):
    with publication_lock():
        folder,before=inspect(folder,candidate,expected,size)
        token=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
        snapshot=folder/('candidate-'+token+'.exe')
        with snapshot.open('xb') as output,Path(candidate).open('rb') as stream:
            os.chmod(snapshot,0o600);shutil.copyfileobj(stream,output,1024*1024);output.flush();os.fsync(output.fileno())
        if digest(snapshot)!=expected or snapshot.stat().st_size!=size:raise ValueError('Candidate changed during private snapshot')
        values={'launcherVersion':'0.1.4','launcherUrl':'/downloads/TIO-Launcher-0.1.4.exe','fileSizeBytes':size,
                'updatedAt':datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec='milliseconds')}
        journal={'kind':'launcher-0.1.4','backup':str(folder),'before':before,'candidate_sha256':expected,
                 'candidate_bytes':size,'candidate_snapshot':str(snapshot),'values':values}
        journal_path=folder/('launcher-publication-'+token+'.json')
        private_json(journal_path,journal)
        if not IMMUTABLE.exists():
            staged=stage_file(snapshot,expected,size)
            try:os.link(staged,IMMUTABLE);sync_directory(DOWNLOADS)
            finally:staged.unlink(missing_ok=True)
        # Link alias to the verified immutable inode through an exclusive temp.
        descriptor,temporary_name=tempfile.mkstemp(prefix='.tio-alias-',dir=DOWNLOADS);os.close(descriptor)
        temporary=Path(temporary_name);temporary.unlink()
        try:
            os.link(IMMUTABLE,temporary)
            validate_immutable(temporary,expected,size)
            if state(ALIAS)!=before['launcher']:raise ValueError('Current alias changed before atomic replace')
            os.replace(temporary,ALIAS);sync_directory(DOWNLOADS)
        finally:temporary.unlink(missing_ok=True)
        try:after=reconcile_metadata(before['metadata']['row'],values)
        except Exception:
            actual=read_row()['row']
            if actual==before['metadata']['row'] and state(ALIAS)['sha256']==expected:
                replace_alias(folder/'TIO-Launcher.exe',OLD_HASH,OLD_BYTES,expected)
            raise
        check_preserved(before)
        if state(ALIAS)['sha256']!=expected or state(IMMUTABLE)['sha256']!=expected:
            raise RuntimeError('Postpublication binary changed; private recovery journal retained')
        report={'operation':'publish','journal':str(journal_path),'backup':str(folder),'after':after,
                'launcher_sha256':expected,'launcher_bytes':size,'immutable_url':values['launcherUrl'],
                'account_writes':0,'database_restored':False,'service_restarts':0,'manifest_changed':False,
                'alias_and_version_same_inode':ALIAS.stat().st_ino==IMMUTABLE.stat().st_ino}
        private_json(folder/('launcher-published-'+token+'.json'),report)
        return report


def rollback(journal_path):
    journal_path=Path(journal_path)
    with publication_lock():
        folder,before=load_backup(journal_path.parent)
        if journal_path.is_symlink() or journal_path.stat().st_uid!=0:raise ValueError('Unexpected recovery journal')
        journal=json.loads(journal_path.read_text())
        if journal.get('kind')!='launcher-0.1.4' or journal.get('before')!=before or journal.get('backup')!=str(folder):
            raise ValueError('Recovery journal differs from private backup')
        check_preserved(before)
        actual=read_row()['row'];old=before['metadata']['row'];values=journal['values']
        alias=state(ALIAS)
        if alias['sha256']!=journal['candidate_sha256'] and alias!=before['launcher']:
            raise ValueError('Concurrent binary change; refusing recovery before metadata write')
        if matches_after(actual,old,values):reconcile_metadata(actual,{key:old[key] for key in FIELDS})
        elif actual!=old:raise ValueError('Concurrent metadata change; refusing recovery')
        alias=state(ALIAS)
        if alias['sha256']==journal['candidate_sha256']:
            replace_alias(folder/'TIO-Launcher.exe',OLD_HASH,OLD_BYTES,journal['candidate_sha256'])
        elif alias!=before['launcher']:raise ValueError('Concurrent binary change; refusing recovery')
        if read_row()['row']!=old or state(ALIAS)!=before['launcher']:raise RuntimeError('Guarded recovery did not reconcile')
        check_preserved(before)
        return {'operation':'rollback','account_writes':0,'database_restored':False,
                'service_restarts':0,'immutable_retained':True,'backup':str(folder)}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',type=Path);parser.add_argument('--candidate',type=Path)
    parser.add_argument('--sha256');parser.add_argument('--bytes',type=int)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--inspect',action='store_true');action.add_argument('--apply',action='store_true')
    action.add_argument('--rollback-journal',type=Path)
    args=parser.parse_args(argv)
    if not hasattr(os,'geteuid') or os.geteuid()!=0:raise PermissionError('Run only as root on the existing VPS')
    if args.rollback_journal:result=rollback(args.rollback_journal)
    else:
        if not all((args.backup,args.candidate,args.sha256,args.bytes)):parser.error('Backup and reviewed candidate/hash/bytes required')
        if args.apply:result=publish(args.backup,args.candidate,args.sha256,args.bytes)
        else:
            folder,before=inspect(args.backup,args.candidate,args.sha256,args.bytes)
            result={'operation':'inspect','backup':str(folder),'before':before,'candidate_sha256':args.sha256,
                    'candidate_bytes':args.bytes,'remote_mutations':0}
    print(json.dumps(result))


if __name__=='__main__':main()
