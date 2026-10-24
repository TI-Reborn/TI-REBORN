"""Publish only the reviewed four-byte client fix, with online hosted backups."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/repair-warehouse-20261017'
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@185.184.42.88']
REMOTE=r'''
import fcntl,hashlib,json,os,shutil,sqlite3,subprocess,sys,tarfile,tempfile
from pathlib import Path
from contextlib import closing
from datetime import datetime,timezone
request=json.load(sys.stdin);os.umask(0o077)
live=Path('/var/www/tio-client/updates');game=Path('/opt/tio-emulator');dbpath=Path('/var/lib/tio-server/reservation.sqlite3')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(path):
 with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()
def service():return subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','NRestarts','-p','ActiveState'],text=True)
def guards():
 paths=[p for directory in ('tio','server','tools','config','evidence') for p in (game/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
 paths += [p for p in Path('/etc/tio-server').rglob('*') if p.is_file()]
 paths += list(Path('/var/www/tio-client/downloads').glob('TIO-Launcher*.exe'))
 return {str(p):digest(p) for p in sorted(paths)}
def atomic(raw,target):
 fd,name=tempfile.mkstemp(prefix='.repair-warehouse-',dir=target.parent)
 try:
  with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno());os.fchmod(out.fileno(),0o644)
  os.replace(name,target)
  fd=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY)
  try:os.fsync(fd)
  finally:os.close(fd)
 finally:
  if os.path.exists(name):os.unlink(name)
def identities():
 with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:return set(db.execute('SELECT login,salt,digest,iterations FROM accounts'))
locks=[]
try:
 for name in ('.tio-gameplay-client.lock','tio-client-archive-publication.lock'):
  fd=os.open('/root/'+name,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);locks.append(fd);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 old=(live/'manifest.json').read_bytes();manifest=json.loads(old)
 assert sha(old)==request['manifest_sha256'] and manifest['version']=='2026.10.15.2','Published client changed; re-review required'
 row=next(r for r in manifest['files'] if r['path']=='silver.dll')
 assert row['sha256']==request['source_sha256'] and row['size']==8163840 and not row.get('seed',False)
 source=(live/'blobs'/row['sha256']).read_bytes();candidate=Path(request['staged_candidate']).read_bytes()
 assert sha(source)==request['source_sha256'] and sha(candidate)==request['candidate_sha256'] and len(source)==len(candidate)==8163840
 differences=[i for i,(a,b) in enumerate(zip(source,candidate)) if a!=b]
 assert differences==[5328327,5328328,5334391,5334392]
 for at in (5328327,5334391):assert source[at:at+2]==b'\x33\xdb' and candidate[at:at+2]==b'\x90\x90'
 before=guards();status=service();accounts=identities()
 assert 'ActiveState=active' in status
 updated=json.loads(old);updated['version']='2026.10.17.1'
 for r in updated['files']:
  if r['path']=='silver.dll':r['sha256']=sha(candidate)
 assert [a['path'] for a,b in zip(manifest['files'],updated['files']) if a!=b]==['silver.dll']
 assert all(manifest[k]==updated[k] for k in manifest if k not in ('version','files'))
 new=json.dumps(updated,ensure_ascii=False,indent=2).encode()+b'\n'
 if not request['apply']:
  print(json.dumps(dict(passed=True,preparation_only=True,current_version=manifest['version'],next_version=updated['version'],changed_bytes=4,service_active=True)))
 else:
  backup=Path(tempfile.mkdtemp(prefix='tio-before-repair-warehouse-',dir='/root'));backup.chmod(0o700)
  with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
   db.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()==('ok',)
  (backup/'previous-manifest.json').write_bytes(old);(backup/'previous-silver.dll').write_bytes(source);(backup/'new-manifest.json').write_bytes(new)
  with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as archive:
   for directory in ('server','tio','tools','config','evidence'):
    archive.add(game/directory,arcname='code/'+directory,filter=lambda m:None if '__pycache__' in m.name.split('/') or m.name.endswith('.pyc') else m)
   archive.add('/etc/tio-server',arcname='etc/tio-server')
  (backup/'tio-server.service.txt').write_text(subprocess.check_output(['systemctl','cat','tio-server'],text=True))
  receipt=dict(created_utc=datetime.now(timezone.utc).isoformat(),sqlite_integrity='ok',database_sha256=digest(backup/'reservation.sqlite3'),code_config_sha256=digest(backup/'previous-code-config.tar.gz'),accounts_in_backup=len(accounts),runtime_before=before)
  (backup/'backup-manifest.json').write_text(json.dumps(receipt,indent=2))
  assert (live/'manifest.json').read_bytes()==old and guards()==before and service()==status
  target=live/'blobs'/sha(candidate)
  if target.exists():assert target.read_bytes()==candidate
  else:atomic(candidate,target)
  assert (live/'manifest.json').read_bytes()==old and guards()==before and service()==status
  committed=False
  try:
   atomic(new,live/'manifest.json');committed=True
   assert (live/'manifest.json').read_bytes()==new and digest(target)==sha(candidate)
   assert guards()==before and service()==status and accounts<=identities()
   with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
   report=dict(passed=True,version=updated['version'],backup=str(backup),changed=['silver.dll'],changed_bytes=4,
    manifest_sha256=sha(new),client_sha256=sha(candidate),service_restarted=False,server_code_config_preserved=True,
    existing_accounts_preserved=True,database_restored=False,local_player_data_uploaded=False,
    other_manifest_records_preserved=True,archive_descriptor_preserved=manifest.get('archive')==updated.get('archive'),timestamp_utc=datetime.now(timezone.utc).isoformat())
   (backup/'publication.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
  except BaseException:
   if committed and (live/'manifest.json').read_bytes()==new:atomic(old,live/'manifest.json')
   raise
finally:
 for fd in reversed(locks):os.close(fd)
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    prepared=json.loads((REPORT/'client/prepared.json').read_text())
    for name in ('native-filter-verification.json','native-wire-verification.json','server-contract-tests.json'):
        assert json.loads((REPORT/name).read_text())['passed']
    candidate=REPORT/'client/candidate/silver.dll'
    assert hashlib.sha256(candidate.read_bytes()).hexdigest()==prepared['candidate_sha256']
    staged='/root/tio-repair-warehouse-'+prepared['candidate_sha256']+'.dll'
    subprocess.run(['scp',*SSH[1:-1],str(candidate),'root@185.184.42.88:'+staged],check=True,capture_output=True,timeout=45)
    payload=dict(manifest_sha256=prepared['baseline_manifest_sha256'],source_sha256=prepared['source_sha256'],candidate_sha256=prepared['candidate_sha256'],staged_candidate=staged,apply=args.apply)
    result=subprocess.run(SSH+['python3 -c '+shlex.quote(REMOTE)],input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=180)
    if result.returncode:
        (REPORT/'publication-error.log').write_text(result.stdout+result.stderr,encoding='utf-8');raise RuntimeError('Publication failed; inspect local diagnostic')
    data=json.loads(result.stdout);(REPORT/('publication.json' if args.apply else 'publication-preflight.json')).write_text(json.dumps(data,indent=2));print(json.dumps(data))


if __name__=='__main__':main()
