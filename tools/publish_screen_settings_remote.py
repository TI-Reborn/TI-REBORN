"""Inspect or publish the reviewed silver.dll screen-settings client update.

Only --apply mutates hosting. It makes a fresh online backup of the hosted save,
previous game code/config, manifest and silver.dll, then publishes one immutable
blob and atomically replaces the manifest. The launcher and services stay alive.
Candidate hash/size must be supplied explicitly after native review. An existing
report is never overwritten. After an uncertain apply result, use --verify-only;
repeating --apply refuses a changed baseline instead of silently replacing it.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import ssl
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / 'reports/screen-settings'
BASELINE = ROOT / 'reports/gameplay-completion/stage17-city-weight-refresh-client/client/manifest.json'
PREVIOUS_VERSION = '2026.10.09.10'
VERSION = '2026.10.09.11'
MANIFEST_SHA = 'c49d005ded4accda151637e75b3076f28c3d2b927b24f27607ef9c2274f94fae'
SOURCE_SHA = 'bd0ce7a29d4cfdb4689330da8086052c287146fe7a383ed50710493a7ba0b0ac'
SOURCE_BYTES = 7774720
ORIGIN = 'https://185.184.42.88/updates/'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def make_payload(candidate, expected_sha, expected_size, action, baseline=BASELINE):
    """Create a one-file transition from the exact hosted baseline."""
    candidate = Path(candidate).resolve()
    if not candidate.is_relative_to(REPORT_ROOT) or candidate.name != 'silver.dll' or candidate.is_symlink():
        raise ValueError('Candidate must be a reviewed reports/screen-settings silver.dll')
    if not re.fullmatch('[a-f0-9]{64}', expected_sha or ''):
        raise ValueError('Exact reviewed candidate SHA256 is required')
    if type(expected_size) is not int or not SOURCE_BYTES <= expected_size <= SOURCE_BYTES + 1024*1024:
        raise ValueError('Candidate size exceeds the bounded native patch allowance')
    raw = candidate.read_bytes()
    if sha(raw) != expected_sha or len(raw) != expected_size or raw[:2] != b'MZ' or expected_sha == SOURCE_SHA:
        raise ValueError('Candidate differs from the reviewed hash/size or unchanged source')
    old = Path(baseline).read_bytes()
    if sha(old) != MANIFEST_SHA:
        raise ValueError('Exact current hosted manifest baseline is required')
    manifest = json.loads(old)
    if manifest.get('schema') != 1 or manifest.get('version') != PREVIOUS_VERSION:
        raise ValueError('Unexpected client baseline version')
    records = [row for row in manifest['files'] if row['path'] == 'silver.dll']
    if len(records) != 1 or (records[0]['sha256'], records[0]['size'], records[0].get('seed', False)) != (SOURCE_SHA, SOURCE_BYTES, False):
        raise ValueError('Unexpected published silver.dll baseline')
    manifest['version'] = VERSION
    records[0].update(sha256=expected_sha, size=expected_size)
    new = (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    return {'action': action, 'candidate': base64.b64encode(raw).decode('ascii'),
            'candidate_sha256': expected_sha, 'candidate_bytes': expected_size,
            'before_manifest': base64.b64encode(old).decode('ascii'),
            'after_manifest': base64.b64encode(new).decode('ascii'),
            'after_manifest_sha256': sha(new)}


# These exact stdlib functions can also be exercised in a temporary test tree.
REMOTE = r'''
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import base64,fcntl,hashlib,json,os,re,shutil,sqlite3,subprocess,sys,tarfile,tempfile
LIVE=Path('/var/www/tio-client/updates');DOWNLOADS=Path('/var/www/tio-client/downloads')
GAME=Path('/opt/tio-emulator');PRIVATE=Path('/root');DB=Path('/var/lib/tio-server/reservation.sqlite3')
MANIFEST_SHA='c49d005ded4accda151637e75b3076f28c3d2b927b24f27607ef9c2274f94fae'
SOURCE_SHA='bd0ce7a29d4cfdb4689330da8086052c287146fe7a383ed50710493a7ba0b0ac';SOURCE_BYTES=7774720
LAUNCHER_SHA='61a0d5bc78cc5a74a0f29d42d7f9c2bf49ca33b378993221a45ff9ba2084aa5f';LAUNCHER_BYTES=118679712
PREVIOUS='2026.10.09.10';VERSION='2026.10.09.11'
CONFIGS=(Path('/etc/tio-server/server.toml'),Path('/etc/systemd/system/tio-server.service'),
         Path('/etc/nginx/snippets/tio-updates.conf'),Path('/etc/tio-portal/portal.env'))

def sha(raw):return hashlib.sha256(raw).hexdigest()

def regular(path):
 if path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.is_file():raise ValueError('Expected regular file without symlink parents')
 return path

def state(path):
 regular(path);value=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
 info=path.stat()
 return dict(sha256=value.hexdigest(),size=info.st_size,uid=info.st_uid,gid=info.st_gid,mode=info.st_mode&0o777)

def directory(path):
 if path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.is_dir():raise ValueError('Expected regular publication directory')

def sync(path):
 fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
 try:os.fsync(fd)
 finally:os.close(fd)

def private_json(path,value):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w',encoding='utf-8') as out:
  out.write(json.dumps(value,indent=2)+'\n');out.flush();os.fsync(out.fileno())
 sync(path.parent)

def atomic(raw,target,expected_current=None):
 directory(target.parent)
 fd,name=tempfile.mkstemp(prefix='.screen-settings-',dir=target.parent);pending=Path(name)
 try:
  with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
  pending.chmod(0o644);os.chown(pending,0,0)
  if expected_current is not None and regular(target).read_bytes()!=expected_current:raise RuntimeError('Publication target changed before atomic replace')
  os.replace(pending,target);sync(target.parent)
 finally:pending.unlink(missing_ok=True)

def immutable(raw,target):
 if target.exists() or target.is_symlink():
  actual=state(target)
  if actual!=dict(sha256=sha(raw),size=len(raw),uid=0,gid=0,mode=0o644):raise RuntimeError('Existing immutable blob differs')
  return
 directory(target.parent)
 fd,name=tempfile.mkstemp(prefix='.screen-settings-blob-',dir=target.parent);pending=Path(name)
 try:
  with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
  pending.chmod(0o644);os.chown(pending,0,0)
  os.link(pending,target);sync(target.parent)
 finally:pending.unlink(missing_ok=True)

def services():
 result={}
 for name in ('tio-server','tio-game-api','tio-portal','nginx'):
  out=subprocess.check_output(['systemctl','show',name,'-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True,timeout=30)
  result[name]=dict(line.split('=',1) for line in out.splitlines() if '=' in line)
  if result[name].get('ActiveState')!='active' or result[name].get('MainPID') in (None,'0'):raise RuntimeError('Hosted services must be active')
 return result

def code_states():
 result={}
 for name in ('server','tio','tools','config','deploy','registration'):
  folder=GAME/name
  if not folder.exists():continue
  directory(folder)
  for path in sorted(folder.rglob('*')):
   if '__pycache__' in path.parts or path.suffix=='.pyc':continue
   if path.is_file() or path.is_symlink():result[path.relative_to(GAME).as_posix()]=state(path)
 for name in ('requirements.txt','pyproject.toml'):
  if (GAME/name).exists():result[name]=state(GAME/name)
 return result

def guards():
 launchers={name:state(DOWNLOADS/name) for name in ('TIO-Launcher.exe','TIO-Launcher-0.1.4.exe')}
 for value in launchers.values():
  if value!=dict(sha256=LAUNCHER_SHA,size=LAUNCHER_BYTES,uid=0,gid=0,mode=0o644):raise RuntimeError('Expected published 0.1.4 launchers')
 return dict(services=services(),launchers=launchers,configuration={str(path):state(path) for path in CONFIGS},game_code=code_states())

def accounts():
 regular(DB)
 with closing(sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True,timeout=15)) as db:
  db.execute('BEGIN')
  if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('Hosted SQLite integrity failed')
  ids={row[0] for row in db.execute('SELECT login FROM accounts')}
  return ids,dict(integrity='ok',accounts=len(ids),checkpoints=db.execute('SELECT count(*) FROM battle_checkpoints').fetchone()[0],settlement_jobs=db.execute('SELECT count(*) FROM battle_settlement_jobs').fetchone()[0])

def transition(p):
 if set(p)!={'action','candidate','candidate_sha256','candidate_bytes','before_manifest','after_manifest','after_manifest_sha256'} or p['action'] not in ('inspect','apply'):raise ValueError('Unexpected publication request')
 if not re.fullmatch('[a-f0-9]{64}',p['candidate_sha256']) or type(p['candidate_bytes'])is not int or not SOURCE_BYTES<=p['candidate_bytes']<=SOURCE_BYTES+1024*1024:raise ValueError('Invalid reviewed candidate identity')
 old=base64.b64decode(p['before_manifest'],validate=True);new=base64.b64decode(p['after_manifest'],validate=True);raw=base64.b64decode(p['candidate'],validate=True)
 if sha(old)!=MANIFEST_SHA or sha(new)!=p['after_manifest_sha256'] or sha(raw)!=p['candidate_sha256'] or len(raw)!=p['candidate_bytes'] or raw[:2]!=b'MZ' or sha(raw)==SOURCE_SHA:raise ValueError('Reviewed candidate or manifest identity differs')
 a,b=json.loads(old),json.loads(new)
 if a.get('schema')!=1 or a.get('version')!=PREVIOUS or b.get('version')!=VERSION or set(a)!=set(b) or any(a[k]!=b[k] for k in a if k not in ('version','files')):raise ValueError('Unexpected manifest metadata change')
 if len(a['files'])!=6330 or len(b['files'])!=6330 or [r['path'] for r in a['files']]!=[r['path'] for r in b['files']]:raise ValueError('Published file list must remain exact')
 changed=[y['path'] for x,y in zip(a['files'],b['files']) if x!=y]
 prior=next(r for r in a['files'] if r['path']=='silver.dll');record=next(r for r in b['files'] if r['path']=='silver.dll')
 if changed!=['silver.dll'] or (prior['sha256'],prior['size'],prior.get('seed',False))!=(SOURCE_SHA,SOURCE_BYTES,False) or record!=dict(prior,sha256=sha(raw),size=len(raw)):raise ValueError('Only reviewed silver.dll may change')
 directory(LIVE);directory(LIVE/'blobs')
 if regular(LIVE/'manifest.json').read_bytes()!=old:raise RuntimeError('Actual hosted manifest changed; refusing stale release')
 source=regular(LIVE/'blobs'/SOURCE_SHA).read_bytes()
 if sha(source)!=SOURCE_SHA or len(source)!=SOURCE_BYTES:raise RuntimeError('Actual published silver.dll source differs')
 changed_bytes=sum(x!=y for x,y in zip(source,raw))
 if changed_bytes>65536:raise ValueError('Candidate exceeds the bounded changed-byte allowance')
 return old,new,source,raw,dict(changed_existing_bytes=changed_bytes,appended_bytes=len(raw)-len(source),preserved_records=6329)

def filtered(member):
 return None if '__pycache__' in member.name.split('/') or member.name.endswith('.pyc') else member

def backup(old,source,before):
 directory(PRIVATE)
 folder=Path(tempfile.mkdtemp(prefix='tio-before-screen-settings-',dir=PRIVATE));folder.chmod(0o700)
 with closing(sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True,timeout=15)) as src,closing(sqlite3.connect(folder/'reservation.sqlite3')) as dst:
  src.backup(dst)
  if dst.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('Hosted save backup integrity failed')
  saved_accounts=dst.execute('SELECT count(*) FROM accounts').fetchone()[0]
 (folder/'reservation.sqlite3').chmod(0o600)
 (folder/'previous-manifest.json').write_bytes(old);(folder/'silver.dll').write_bytes(source)
 with tarfile.open(folder/'previous-code.tar.gz','w:gz') as archive:
  for name in ('server','tio','tools','config','deploy','registration','requirements.txt','pyproject.toml'):
   if (GAME/name).exists():archive.add(GAME/name,arcname=name,filter=filtered)
 with tarfile.open(folder/'previous-config.tar.gz','w:gz') as archive:
  for name in ('/etc/tio-server','/etc/tio-portal','/etc/nginx/snippets/tio-updates.conf','/etc/systemd/system/tio-server.service'):
   path=Path(name)
   if path.exists():archive.add(path,arcname=name.lstrip('/'),filter=filtered)
 private_json(folder/'before.json',before)
 receipt=dict(created_utc=datetime.now(timezone.utc).isoformat(),sqlite_integrity='ok',accounts_in_backup=saved_accounts,
              files={path.name:state(path) for path in sorted(folder.iterdir()) if path.is_file()})
 private_json(folder/'backup-manifest.json',receipt)
 return folder,receipt

def execute(p):
 old,new,source,raw,delta=transition(p)
 before=guards();ids,health=accounts()
 if len(ids)<202:raise RuntimeError('Hosted account count fell below inspected baseline')
 if p['action']=='inspect':return dict(passed=True,operation='inspect',remote_mutations=0,client_version=PREVIOUS,
       candidate_sha256=sha(raw),candidate_bytes=len(raw),manifest_sha256=sha(old),health=health,guards=before,patch_scope=delta)
 os.umask(0o077)
 fd=os.open(PRIVATE/'.tio-gameplay-client.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:raise RuntimeError('Hosted publication baseline changed before backup')
  folder,receipt=backup(old,source,before)
  if regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:raise RuntimeError('Hosted publication baseline changed during backup')
  private_json(folder/'publication-journal.json',dict(version=VERSION,candidate_sha256=sha(raw),candidate_bytes=len(raw),
       before_manifest_sha256=sha(old),after_manifest_sha256=sha(new),backup=str(folder),patch_scope=delta))
  target=LIVE/'blobs'/sha(raw)
  try:
   immutable(raw,target)
   if guards()!=before:raise RuntimeError('Services, launchers, code or configuration changed before publication')
   atomic(new,LIVE/'manifest.json',old)
   if regular(LIVE/'manifest.json').read_bytes()!=new or regular(target).read_bytes()!=raw or guards()!=before:raise RuntimeError('Postpublication parity failed')
   after_ids,after_health=accounts()
   if not ids<=after_ids:raise RuntimeError('Hosted account identity disappeared during publication')
  except BaseException:
   # Restore only this manifest if our exact result is still current. Never
   # restore hosted player data or overwrite a concurrent client publication.
   if regular(LIVE/'manifest.json').read_bytes()==new:atomic(old,LIVE/'manifest.json',new)
   raise
  report=dict(passed=True,operation='publish',version=VERSION,backup=str(folder),candidate_sha256=sha(raw),candidate_bytes=len(raw),
       source_sha256=sha(source),manifest_sha256=sha(new),timestamp_utc=datetime.now(timezone.utc).isoformat(),
       changed=['silver.dll'],patch_scope=delta,accounts_before=len(ids),accounts_in_backup=receipt['accounts_in_backup'],accounts_after=len(after_ids),
       hosted_accounts_preserved=True,health=after_health,services_unchanged=True,launchers_preserved=True,code_and_config_preserved=True,
       server_restarted=False,database_written=False,local_player_data_uploaded=False,other_client_files_preserved=True,seed_records_preserved=True,
       guards=before)
  private_json(folder/'publication.json',report)
  return report
 finally:os.close(fd)

if __name__=='__main__':
 if os.geteuid()!=0:raise PermissionError('Run only as root on the existing hosting server')
 print(json.dumps(execute(json.load(sys.stdin))))
'''


def invoke(payload):
    result = subprocess.run(['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes',
                             '-o', 'ConnectTimeout=15', 'root@185.184.42.88',
                             '/usr/bin/python3 -c '+shlex.quote(REMOTE)],
                            input=json.dumps(payload), text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError('Scoped screen-settings remote operation failed; private subprocess output suppressed')
    return json.loads(result.stdout)


def fetch(path, maximum):
    context = ssl.create_default_context()
    context.keylog_filename = None
    url = ORIGIN+path
    request = urllib.request.Request(url, headers={'Cache-Control': 'no-cache', 'Pragma': 'no-cache'})
    with urllib.request.urlopen(request, context=context, timeout=60) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('Trusted HTTPS endpoint changed')
        raw = response.read(maximum+1)
    if len(raw) > maximum:
        raise ValueError('Trusted HTTPS response exceeds bound')
    return raw


def verify_https(payload):
    new = base64.b64decode(payload['after_manifest'], validate=True)
    actual = fetch('manifest.json', 4*1024*1024)
    if actual != new:
        raise ValueError('Public HTTPS manifest differs from the reviewed candidate')
    candidate = fetch('blobs/'+payload['candidate_sha256'], payload['candidate_bytes'])
    if sha(candidate) != payload['candidate_sha256'] or len(candidate) != payload['candidate_bytes']:
        raise ValueError('Public HTTPS silver.dll differs from the reviewed candidate')
    return dict(passed=True, version=VERSION, trusted_https=True, origin=ORIGIN,
                manifest_sha256=sha(actual), silver_sha256=sha(candidate), silver_bytes=len(candidate),
                verified_utc=datetime.now(timezone.utc).isoformat(), graphical_validation=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--bytes', type=int, required=True)
    parser.add_argument('--report', type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--inspect', action='store_true')
    action.add_argument('--apply', action='store_true')
    action.add_argument('--verify-only', action='store_true')
    args = parser.parse_args(argv)
    report_path = args.report.resolve()
    if not report_path.is_relative_to(REPORT_ROOT) or report_path.exists() or report_path.is_symlink():
        raise ValueError('Use a new reports/screen-settings evidence file')
    payload = make_payload(args.candidate, args.sha256, args.bytes, 'apply' if args.apply else 'inspect')
    if args.verify_only:
        report = verify_https(payload)
    else:
        report = invoke(payload)
        # Save the durable remote receipt before the independent HTTPS check.
        # A failed check can then be retried with --verify-only under a new name.
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open('x', encoding='utf-8') as output:
            json.dump(report, output, indent=2)
            output.write('\n')
        if args.apply:
            https = verify_https(payload)
            https_path = report_path.with_name(report_path.stem+'-https.json')
            with https_path.open('x', encoding='utf-8') as output:
                json.dump(https, output, indent=2)
                output.write('\n')
        print(json.dumps({'passed': True, 'report': str(report_path), 'operation': report['operation'],
                          'backup': report.get('backup'), 'candidate_sha256': args.sha256,
                          'remote_mutations': 0 if args.inspect else 1}))
        return
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
        output.write('\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
