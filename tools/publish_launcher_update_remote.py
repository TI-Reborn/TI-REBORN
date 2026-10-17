"""Root-only launcher self-update publication from an explicitly pinned baseline.

Publishes one immutable EXE and the current alias, then updates only the public
DownloadVersion/main launcher fields. Publishes the self-update manifest last.
A durable journal supports guarded rollback. Run through reviewed SSH stdin;
do not install this tool as a service.
Rollback requires the same --baseline-version/--baseline-sha256/--baseline-bytes
as publication; journal data never silently chooses the caller's baseline.
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
SELF_MANIFEST=DOWNLOADS/'launcher-manifest.json'
MANIFEST=Path('/var/www/tio-client/updates/manifest.json')
OLD_VERSION='0.1.4'
OLD_HASH='61a0d5bc78cc5a74a0f29d42d7f9c2bf49ca33b378993221a45ff9ba2084aa5f'
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
    descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
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


def validate_identity(version,expected,size):
    if not isinstance(version,str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)',version):
        raise ValueError('Expected a three-part numeric launcher version')
    if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected) or type(size) is not int or not MIN_BYTES<=size<=MAX_BYTES:
        raise ValueError('Reviewed hash and bounded byte count are required')


def baseline_identity():
    return {'version':OLD_VERSION,'sha256':OLD_HASH,'size':OLD_BYTES}


def configure_baseline(args):
    global OLD_VERSION,OLD_HASH,OLD_BYTES
    validate_identity(args.baseline_version,args.baseline_sha256,args.baseline_bytes)
    OLD_VERSION,OLD_HASH,OLD_BYTES=args.baseline_version,args.baseline_sha256,args.baseline_bytes
    return baseline_identity()


def validate_release(version,expected,size):
    validate_identity(version,expected,size)
    if tuple(map(int,version.split('.'))) <= tuple(map(int,OLD_VERSION.split('.'))):
        raise ValueError('The new launcher must be newer than the reviewed baseline')
    return DOWNLOADS/('TIO-Launcher-'+version+'.exe')


def self_manifest_bytes(version,expected,size):
    validate_release(version,expected,size)
    return (json.dumps({'schema':1,'version':version,'sha256':expected,'size':size},indent=2)+'\n').encode('utf-8')


def optional_state(path):
    path=Path(path)
    if path.is_symlink():raise ValueError('Publication symlinks are forbidden')
    return state(path) if path.exists() else None


def prior_self_manifest():
    result=optional_state(SELF_MANIFEST)
    if result is None:return None
    if result['bytes']>4096 or result['mode']!=0o644 or result['uid']!=0 or result['gid']!=0:
        raise ValueError('Unexpected previous launcher manifest file')
    value=json.loads(SELF_MANIFEST.read_text(encoding='utf-8'))
    if value!={'schema':1,'version':OLD_VERSION,'sha256':OLD_HASH,'size':OLD_BYTES}:
        raise ValueError('Previous launcher manifest differs from the reviewed baseline')
    return result


def load_backup(folder):
    folder=Path(folder)
    if (folder.is_symlink() or folder.parent!=Path('/root') or not folder.name.startswith('tio-before-launcher-')
            or folder.stat().st_uid!=0 or folder.stat().st_mode&0o077):
        raise ValueError('Expected a private root launcher backup')
    for name in ('backup-manifest.json','publication-before.json'):
        details=state(folder/name)
        if details['uid']!=0 or details['mode']&0o077:raise ValueError('Expected private backup metadata')
    before=json.loads((folder/'publication-before.json').read_text())
    receipt=json.loads((folder/'backup-manifest.json').read_text())
    if receipt.get('sqlite_integrity')!='ok' or receipt.get('website_full_isolated_restore') is not True:
        raise ValueError('Consistent databases and a full isolated PostgreSQL restore are required')
    for name in ('reservation.sqlite3','website.dump','game-code.tar.gz','portal-code.tar.gz',
                 'operational-config.tar.gz','TIO-Launcher.exe','client-manifest.json','publication-before.json'):
        actual=state(folder/name);expected=receipt['files'][name]
        if (actual['sha256']!=expected['sha256'] or actual['bytes']!=expected['bytes']
                or actual['uid']!=0 or actual['mode']&0o077):
            raise ValueError('Private prepublication backup changed')
    launcher=before['launcher'];row=before['metadata']['row']
    if launcher!={'sha256':OLD_HASH,'bytes':OLD_BYTES,'mode':0o644,'uid':0,'gid':0}:
        raise ValueError('Launcher backup differs from the explicitly pinned baseline')
    if (row.get('launcherVersion')!=OLD_VERSION or row.get('launcherUrl')!='/downloads/TIO-Launcher-'+OLD_VERSION+'.exe'
            or row.get('fileSizeBytes')!=OLD_BYTES):
        raise ValueError('Public metadata backup differs from the explicitly pinned baseline')
    return folder,before


def check_preserved(before):
    current=preserved()
    if any(current[key]!=before[key] for key in current):
        raise ValueError('Client manifest, portal release, services or configuration changed')


def validate_public_file(path,expected,size):
    actual=state(path)
    if actual!={'sha256':expected,'bytes':size,'mode':0o644,'uid':0,'gid':0}:
        raise ValueError('Public file differs in content, ownership or permissions')
    return actual


def inspect(folder,candidate,version,expected,size):
    immutable=validate_release(version,expected,size)
    folder,before=load_backup(folder)
    candidate=Path(candidate)
    details=state(candidate)
    if candidate.parent!=Path('/root') or details['uid']!=0:
        raise ValueError('Candidate must be a direct root-owned /root file')
    if details['sha256']!=expected or details['bytes']!=size:raise ValueError('Reviewed candidate differs')
    if state(ALIAS)!=before['launcher'] or read_row()['row']!=before['metadata']['row']:
        raise ValueError('Current alias or public metadata differs from the fresh backup')
    check_preserved(before)
    previous_manifest=prior_self_manifest()
    if immutable.exists() or immutable.is_symlink():validate_public_file(immutable,expected,size)
    return folder,before,previous_manifest


def copy_private(source,target,expected):
    descriptor=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'wb') as output,Path(source).open('rb') as stream:
        shutil.copyfileobj(stream,output,1024*1024);output.flush();os.fsync(output.fileno())
    details=state(target)
    if details['sha256']!=expected['sha256'] or details['bytes']!=expected['bytes']:
        raise ValueError('Source changed while capturing the private snapshot')
    sync_directory(Path(target).parent)


def stage_file(source,expected,size):
    descriptor,name=tempfile.mkstemp(prefix='.tio-launcher-',dir=DOWNLOADS)
    path=Path(name)
    try:
        with os.fdopen(descriptor,'wb') as output,Path(source).open('rb') as stream:
            shutil.copyfileobj(stream,output,1024*1024);output.flush();os.fsync(output.fileno())
        if digest(path)!=expected or path.stat().st_size!=size:raise ValueError('Source changed while staging')
        path.chmod(0o644);os.chown(path,0,0)
        return path
    except BaseException:
        path.unlink(missing_ok=True);raise


def replace_alias(source,expected,size,guard):
    temporary=stage_file(source,expected,size)
    try:
        if state(ALIAS)!=guard:raise ValueError('Current alias changed during publication')
        os.replace(temporary,ALIAS);sync_directory(DOWNLOADS)
    finally:temporary.unlink(missing_ok=True)


def publish_immutable(snapshot,path,expected,size):
    if path.exists() or path.is_symlink():
        validate_public_file(path,expected,size);return
    temporary=stage_file(snapshot,expected,size)
    try:
        # A hard link refuses a concurrent creator; never replace a version URL.
        os.link(temporary,path);sync_directory(DOWNLOADS)
    finally:temporary.unlink(missing_ok=True)
    validate_public_file(path,expected,size)


def replace_self_manifest(raw,guard):
    descriptor,name=tempfile.mkstemp(prefix='.tio-launcher-manifest-',dir=DOWNLOADS)
    temporary=Path(name)
    try:
        with os.fdopen(descriptor,'wb') as output:
            output.write(raw);output.flush();os.fsync(output.fileno())
        temporary.chmod(0o644);os.chown(temporary,0,0)
        if optional_state(SELF_MANIFEST)!=guard:raise ValueError('Launcher manifest changed concurrently')
        os.replace(temporary,SELF_MANIFEST);sync_directory(DOWNLOADS)
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
        # PostgreSQL can commit before a transport timeout; reread before recovery.
        actual=read_row()
        if matches_after(actual['row'],before,values):return actual
        if actual['row']==before:raise RuntimeError('Metadata is unchanged; guarded recovery is available') from None
        raise RuntimeError('Metadata changed concurrently; preserve the private recovery journal') from None


def journal_manifest_state(journal):
    raw=self_manifest_bytes(journal['version'],journal['candidate_sha256'],journal['candidate_bytes'])
    return raw,{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'mode':0o644,'uid':0,'gid':0}


def rollback_locked(journal_path):
    journal_path=Path(journal_path)
    details=state(journal_path)
    if details['uid']!=0 or details['mode']&0o077:raise ValueError('Expected a private root recovery journal')
    journal=json.loads(journal_path.read_text())
    if journal.get('baseline')!=baseline_identity():
        raise ValueError('Recovery requires the explicitly pinned baseline recorded in the journal')
    folder,before=load_backup(journal_path.parent)
    if journal.get('kind')!='launcher-self-update' or journal.get('before')!=before or journal.get('backup')!=str(folder):
        raise ValueError('Recovery journal differs from the private backup')
    immutable=validate_release(journal['version'],journal['candidate_sha256'],journal['candidate_bytes'])
    if journal.get('immutable')!=str(immutable):raise ValueError('Unexpected immutable recovery path')
    raw,new_manifest=journal_manifest_state(journal)
    previous_manifest=journal['previous_self_manifest']
    previous_path=folder/journal['previous_self_manifest_file'] if previous_manifest is not None else None
    if previous_path is not None:
        if previous_path.parent!=folder or previous_path.name!='launcher-manifest-before-'+journal['token']+'.json':
            raise ValueError('Unexpected previous manifest backup path')
        details=state(previous_path)
        if (details['sha256']!=previous_manifest['sha256'] or details['bytes']!=previous_manifest['bytes']
                or details['uid']!=0 or details['mode']&0o077):
            raise ValueError('Previous launcher manifest backup changed')
    check_preserved(before)
    current_manifest=optional_state(SELF_MANIFEST)
    current_alias=state(ALIAS)
    new_alias={'sha256':journal['candidate_sha256'],'bytes':journal['candidate_bytes'],'mode':0o644,'uid':0,'gid':0}
    old_row=before['metadata']['row'];current_row=read_row()['row'];values=journal['values']
    expected_values={'launcherVersion':journal['version'],'launcherUrl':'/downloads/'+immutable.name,
                     'fileSizeBytes':journal['candidate_bytes'],'updatedAt':values.get('updatedAt')}
    if values!=expected_values:raise ValueError('Unexpected recovery metadata values')
    # Check all public guards before writing anything; preserve unrelated changes.
    if current_manifest!=previous_manifest and current_manifest!=new_manifest:
        raise ValueError('Concurrent launcher manifest change; refusing recovery')
    if current_alias!=before['launcher'] and current_alias!=new_alias:
        raise ValueError('Concurrent launcher binary change; refusing recovery')
    if current_row!=old_row and not matches_after(current_row,old_row,values):
        raise ValueError('Concurrent metadata change; refusing recovery')
    # Withdraw the update pointer first; retain immutable binaries for in-flight clients.
    if current_manifest==new_manifest:
        if previous_path is None:
            if optional_state(SELF_MANIFEST)!=new_manifest:raise ValueError('Launcher manifest changed during recovery')
            SELF_MANIFEST.unlink();sync_directory(DOWNLOADS)
        else:replace_self_manifest(previous_path.read_bytes(),new_manifest)
    if matches_after(current_row,old_row,values):
        reconcile_metadata(current_row,{key:old_row[key] for key in FIELDS})
    if current_alias==new_alias:
        replace_alias(folder/'TIO-Launcher.exe',OLD_HASH,OLD_BYTES,new_alias)
    if (optional_state(SELF_MANIFEST)!=previous_manifest or state(ALIAS)!=before['launcher']
            or not matches_after(read_row()['row'],old_row,{key:old_row[key] for key in FIELDS})):
        raise RuntimeError('Guarded recovery did not reconcile')
    check_preserved(before)
    return {'operation':'rollback','backup':str(folder),'journal':str(journal_path),
            'account_writes':0,'database_restored':False,'service_restarts':0,'immutable_retained':True}


def rollback(journal_path):
    with publication_lock():return rollback_locked(journal_path)


def publish(folder,candidate,version,expected,size):
    with publication_lock():
        folder,before,previous_manifest=inspect(folder,candidate,version,expected,size)
        immutable=validate_release(version,expected,size)
        token=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
        snapshot=folder/('candidate-'+token+'.exe')
        copy_private(candidate,snapshot,{'sha256':expected,'bytes':size})
        previous_filename=None
        if previous_manifest is not None:
            previous_filename='launcher-manifest-before-'+token+'.json'
            copy_private(SELF_MANIFEST,folder/previous_filename,previous_manifest)
        if optional_state(SELF_MANIFEST)!=previous_manifest:raise ValueError('Launcher manifest changed during backup')
        values={'launcherVersion':version,'launcherUrl':'/downloads/'+immutable.name,'fileSizeBytes':size,
                'updatedAt':datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec='milliseconds')}
        journal={'kind':'launcher-self-update','backup':str(folder),'before':before,'version':version,'token':token,
                 'baseline':baseline_identity(),
                 'candidate_sha256':expected,'candidate_bytes':size,'candidate_snapshot':str(snapshot),
                 'immutable':str(immutable),'values':values,'previous_self_manifest':previous_manifest,
                 'previous_self_manifest_file':previous_filename}
        journal_path=folder/('launcher-publication-'+token+'.json')
        private_json(journal_path,journal)
        raw,new_manifest=journal_manifest_state(journal)
        try:
            publish_immutable(snapshot,immutable,expected,size)
            check_preserved(before)
            if read_row()['row']!=before['metadata']['row']:raise ValueError('Public metadata changed before alias replacement')
            replace_alias(immutable,expected,size,before['launcher'])
            after=reconcile_metadata(before['metadata']['row'],values)
            check_preserved(before)
            validate_public_file(ALIAS,expected,size);validate_public_file(immutable,expected,size)
            # Discoverable self-update pointer is committed only after binary and metadata.
            replace_self_manifest(raw,previous_manifest)
            if optional_state(SELF_MANIFEST)!=new_manifest:raise RuntimeError('Published launcher manifest differs')
            if not matches_after(read_row()['row'],before['metadata']['row'],values):
                raise RuntimeError('Published launcher metadata changed')
            check_preserved(before)
        except BaseException:
            try:rollback_locked(journal_path)
            except Exception:
                raise RuntimeError('Publication failed; guarded recovery could not complete; journal: '+str(journal_path)) from None
            raise RuntimeError('Publication failed and public launcher state was restored; journal: '+str(journal_path)) from None
        report={'operation':'publish','version':version,'journal':str(journal_path),'backup':str(folder),'after':after,
                'baseline':baseline_identity(),
                'launcher_sha256':expected,'launcher_bytes':size,'immutable_url':values['launcherUrl'],
                'self_update_manifest_url':'/downloads/launcher-manifest.json','self_update_manifest':json.loads(raw),
                'self_update_manifest_sha256':new_manifest['sha256'],'previous_self_manifest_backed_up':previous_manifest is not None,
                'account_writes':0,'database_restored':False,'service_restarts':0,'client_manifest_changed':False}
        private_json(folder/('launcher-published-'+token+'.json'),report)
        return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',type=Path);parser.add_argument('--candidate',type=Path)
    parser.add_argument('--version',default='0.1.5');parser.add_argument('--sha256');parser.add_argument('--bytes',type=int)
    parser.add_argument('--baseline-version',default=OLD_VERSION)
    parser.add_argument('--baseline-sha256',default=OLD_HASH)
    parser.add_argument('--baseline-bytes',type=int,default=OLD_BYTES)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--inspect',action='store_true');action.add_argument('--apply',action='store_true')
    action.add_argument('--rollback-journal',type=Path)
    args=parser.parse_args(argv)
    if not hasattr(os,'geteuid') or os.geteuid()!=0:raise PermissionError('Run only as root on the existing VPS')
    configure_baseline(args)
    if args.rollback_journal:result=rollback(args.rollback_journal)
    else:
        if not all((args.backup,args.candidate,args.sha256,args.bytes)):
            parser.error('Fresh private backup and reviewed candidate/hash/bytes are required')
        if args.apply:result=publish(args.backup,args.candidate,args.version,args.sha256,args.bytes)
        else:
            folder,before,previous=inspect(args.backup,args.candidate,args.version,args.sha256,args.bytes)
            result={'operation':'inspect','backup':str(folder),'before':before,'version':args.version,
                    'baseline':baseline_identity(),
                    'candidate_sha256':args.sha256,'candidate_bytes':args.bytes,'previous_self_manifest':previous,
                    'self_update_manifest':json.loads(self_manifest_bytes(args.version,args.sha256,args.bytes)),
                    'remote_mutations':0}
    print(json.dumps(result))


if __name__=='__main__':main()


