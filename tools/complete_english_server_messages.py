"""Complete typed status/concatenated messages after the resource publication."""
from pathlib import Path
import base64,json,subprocess
ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/english-localization'
REMOTE=r'''
from pathlib import Path
from contextlib import closing
import base64,hashlib,json,os,sqlite3,subprocess,tarfile,tempfile
backup=Path(request['backup']);game=Path('/opt/tio-emulator')
if backup.parent!=Path('/root') or not backup.name.startswith('tio-before-launcher-') or backup.is_symlink():raise ValueError('Unexpected verified backup')
receipt=json.loads((backup/'backup-manifest.json').read_bytes())
if receipt['sqlite_integrity']!='ok' or receipt.get('website_full_isolated_restore') is not True:raise ValueError('Verified online backup required')
archive=backup/'game-code.tar.gz'
if hashlib.sha256(archive.read_bytes()).hexdigest()!=receipt['files']['game-code.tar.gz']['sha256']:raise ValueError('Backup archive identity changed')
if json.loads(Path('/var/www/tio-client/updates/manifest.json').read_bytes())['version']!='2026.10.13.1':raise ValueError('Expected resource release required')
prior={};candidate={}
with tarfile.open(archive) as tar:
 for name in ('tio/localization.py','config/english_translations.json'):
  previous=tar.extractfile(name).read();path=game/name
  if path.is_symlink() or path.read_bytes()!=previous:raise ValueError('Code changed after verified backup: '+name)
  raw=base64.b64decode(request['files'][name]);prior[path]=previous;candidate[path]=raw
  if name.endswith('.py'):compile(raw,name,'exec')
  else:
   data=json.loads(raw)
   if not isinstance(data.get('__template_fields__'),dict):raise ValueError('Typed status fields missing')
def ids():
 with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
  assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
  return {r[0] for r in db.execute('SELECT login FROM accounts')}
def atomic(path,raw):
 fd,name=tempfile.mkstemp(prefix='.english-completion-',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
  os.chmod(name,0o644);os.replace(name,path)
 finally:
  if os.path.exists(name):os.unlink(name)
before=ids()
try:
 subprocess.run(['systemctl','stop','tio-server'],check=True,timeout=60)
 for path,raw in candidate.items():
  if path.read_bytes()!=prior[path]:raise ValueError('Source changed before completion')
  atomic(path,raw)
 subprocess.run(['systemctl','start','tio-server'],check=True,timeout=60)
 import time;time.sleep(2)
 if subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()!='active':raise ValueError('Updated service failed')
 after=ids();assert before<=after
 result=dict(passed=True,accounts_before=len(before),accounts_after=len(after),backup=str(backup),changed=sorted(str(p.relative_to(game)) for p in candidate),typed_status_fields=3)
 atomic(backup/'english-message-completion.json',json.dumps(result).encode())
 print(json.dumps(result))
except Exception:
 subprocess.run(['systemctl','stop','tio-server'],check=True,timeout=60)
 for path,raw in prior.items():atomic(path,raw)
 subprocess.run(['systemctl','start','tio-server'],check=True,timeout=60)
 raise
'''
def main():
    backup=json.loads((REPORT/'before-launcher-backup.json').read_bytes())['backup']
    request=dict(backup=backup,files={n:base64.b64encode((ROOT/n).read_bytes()).decode() for n in ('tio/localization.py','config/english_translations.json')})
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@185.184.42.88','python3 -'],input='request='+repr(request)+'\n'+REMOTE,encoding='utf-8',capture_output=True)
    if result.returncode:raise RuntimeError(result.stderr.strip().splitlines()[-1])
    data=json.loads(result.stdout);(REPORT/'message-completion-deployment.json').write_text(json.dumps(data,indent=2),encoding='utf-8');print(json.dumps(data))
if __name__=='__main__':main()
