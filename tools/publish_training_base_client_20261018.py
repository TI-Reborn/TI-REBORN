"""Publish only reviewed Training Base DLL/localization, retaining current assets."""
import argparse,base64,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
OUT=ROOT/'reports/training-base-20261018'
REMOTE=r'''
import base64,fcntl,hashlib,json,os,shutil,sqlite3,subprocess,tarfile,tempfile
from pathlib import Path
from contextlib import closing
os.umask(0o077);live=Path('/var/www/tio-client/updates');manifest_path=live/'manifest.json'
sha=lambda b:hashlib.sha256(b).hexdigest()
raw=manifest_path.read_bytes();old=json.loads(raw)
status=lambda:subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True)
before=status();assert 'ActiveState=active' in before
def atomic(raw,path):
 fd,name=tempfile.mkstemp(prefix='.training-',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno());os.fchmod(out.fileno(),0o644)
  os.replace(name,path)
 finally:
  if os.path.exists(name):os.unlink(name)
if request['action']=='prepare':
 assert sha(raw)=='d85d854996b3f031d3c75e1a4619e294c7f4be8418492c5db2599fdce8eb5509' and old['version']=='2026.10.17.2'
 folder=Path(tempfile.mkdtemp(prefix='tio-training-client-',dir='/root'))
 (folder/'before-manifest.json').write_bytes(raw)
 updated=json.loads(raw);updated['version']='2026.10.18.1'
 allowed={'silver.dll','base/russian.lng','base/english.lng'};assert set(request['assets'])==allowed
 changed=[]
 for row in updated['files']:
  if row['path'] not in allowed:continue
  previous=(live/'blobs'/row['sha256']).read_bytes();assert sha(previous)==row['sha256']
  candidate=base64.b64decode(request['assets'][row['path']])
  if row['path']=='silver.dll':
   assert sha(previous)==request['proof']['before_sha256'] and sha(candidate)==request['proof']['after_sha256']
  else:
   key=b'\r\ntb02t=';assert key not in previous
   assert candidate.startswith(previous.rstrip(b'\r\n')+key)
   assert candidate.endswith(b'\r\n') and candidate.count(key)==1
  target=live/'blobs'/sha(candidate)
  if target.exists():assert target.read_bytes()==candidate
  else:atomic(candidate,target)
  row.update(size=len(candidate),sha256=sha(candidate));changed.append(row['path'])
 assert set(changed)==allowed
 updated['archive']=builder['build'](updated,live/'blobs',folder/'client.zip')
 new=json.dumps(updated,ensure_ascii=False,indent=2).encode()+b'\n';(folder/'manifest.json').write_bytes(new)
 result=dict(prepared=True,folder=str(folder),before_sha256=sha(raw),after_sha256=sha(new),changed=changed,version=updated['version'],archive=updated['archive'])
 (folder/'receipt.json').write_text(json.dumps(result,indent=2));assert status()==before
else:
 receipt=request['prepared'];folder=Path(receipt['folder'])
 assert folder.parent==Path('/root') and folder.name.startswith('tio-training-client-') and not folder.is_symlink()
 assert json.loads((folder/'receipt.json').read_text())==receipt and sha(raw)==receipt['before_sha256']
 new=(folder/'manifest.json').read_bytes();assert sha(new)==receipt['after_sha256']
 updated=json.loads(new);assert builder['files_digest'](updated)==receipt['archive']['filesSha256']
 assert next(r for r in updated['files'] if r['path']=='silver.dll')['sha256']==request['client_sha256']
 archive=folder/'client.zip';assert builder['digest'](archive)==receipt['archive']['sha256']
 # Current manifest is guarded again under both existing publication locks.
 fds=[]
 for name in ('.tio-gameplay-client.lock','tio-client-archive-publication.lock'):
  fd=os.open('/root/'+name,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);fds.append(fd)
 assert manifest_path.read_bytes()==raw
 backup=Path(tempfile.mkdtemp(prefix='tio-before-training-client-',dir='/root'))
 (backup/'manifest.json').write_bytes(raw)
 with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
  src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()==('ok',)
 with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as tar:
  for name in ('server','tio','config','evidence'):tar.add('/opt/tio-emulator/'+name,arcname='code/'+name,filter=lambda m:None if '__pycache__' in m.name.split('/') else m)
  tar.add('/etc/tio-server',arcname='etc/tio-server')
 for row in old['files']:
  if row['path'] in receipt['changed']:
   dest=backup/'client'/row['path'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(live/'blobs'/row['sha256'],dest)
 target=live/'blobs'/receipt['archive']['sha256']
 if target.exists():assert builder['digest'](target)==receipt['archive']['sha256']
 else:
  # Immutable archive is installed before committing the manifest pointer.
  fd,name=tempfile.mkstemp(prefix='.training-archive-',dir=target.parent);os.close(fd)
  try:shutil.copyfile(archive,name);os.chmod(name,0o644);os.replace(name,target)
  finally:
   if os.path.exists(name):os.unlink(name)
 assert status()==before and manifest_path.read_bytes()==raw
 atomic(new,manifest_path)
 assert manifest_path.read_bytes()==new and status()==before
 result=dict(published=True,version=updated['version'],backup=str(backup),manifest_sha256=sha(new),changed=receipt['changed'],service_restarted=False,database_written=False,archive_verified=True)
 (backup/'receipt.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
'''
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=('prepare','publish'));args=p.parse_args()
    request=dict(action=args.action)
    if args.action=='prepare':
        assert json.loads((OUT/'client/native-execution.json').read_text())['passed']
        request['assets']={n:base64.b64encode((OUT/'client'/n).read_bytes()).decode() for n in ('silver.dll','base/russian.lng','base/english.lng')}
        request['proof']=json.loads((OUT/'client/native-review.json').read_text())
    else:
        gui=json.loads((OUT/'gui-verification.json').read_text(encoding='utf-8'));assert gui['create_room_visible']
        request['client_sha256']=gui['client_sha256']
        request['prepared']=json.loads((OUT/'client-prepared.json').read_text())
    code='request='+repr(request)+"\nbuilder={'__name__':'training_archive_builder'}\nexec(compile("+repr((ROOT/'launcher/build_archive.py').read_text())+",'archive-builder','exec'),builder)\n"+REMOTE
    r=subprocess.run(SSH+['python3 -'],input=code,capture_output=True,encoding='utf-8',timeout=900)
    if r.returncode:raise RuntimeError(r.stderr[-2000:])
    value=json.loads(r.stdout);(OUT/('client-prepared.json' if args.action=='prepare' else 'client-publication.json')).write_text(json.dumps(value,indent=2));print(json.dumps(value))
if __name__=='__main__':main()
