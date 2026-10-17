"""Remove only the user-authorized public Unity namespace; preserve legacy data."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/user-agreement-20261012/unity-removal'

def digest(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda: f.read(1024 * 1024), b''):
            h.update(c)
    return h.hexdigest()

REMOTE = r'''
import hashlib,json,os,subprocess,sqlite3,tempfile,time
from pathlib import Path
request=REQUEST
root=Path('/var/www/tio-unity')
assert root.resolve(strict=True)==root and all(not p.is_symlink() for p in [root,*root.parents])
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1048576),b''):h.update(c)
 return h.hexdigest()
def files():
 out={}
 for p in sorted(root.rglob('*')):
  assert not p.is_symlink() and p.resolve().is_relative_to(root)
  if p.is_file():
   s=p.stat();assert s.st_uid==0
   out[str(p)]=(s.st_size,digest(p))
 return out
def account_state():
 db=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
 try:
  assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
  rows=db.execute('select * from accounts order by login').fetchall()
  return {'count':len(rows),'full_rows_sha256':hashlib.sha256(json.dumps(rows,default=str,separators=(',',':')).encode()).hexdigest()}
 finally:db.close()
def legacy():
 base=Path('/var/www/tio-client');out={}
 for p in sorted(base.rglob('*')):
  assert not p.is_symlink()
  if p.is_file():
   s=p.stat();out[str(p.relative_to(base))]=(s.st_size,s.st_mtime_ns,s.st_ino,s.st_mode)
 return {'file_metadata':out,'manifest_sha256':digest(base/'updates/manifest.json')}
def units():
 out={}
 for u in ('tio-server','tio-portal','tio-game-api','tio-bank-api','nginx'):
  s=subprocess.check_output(['systemctl','show',u,'-p','MainPID','-p','NRestarts','-p','ActiveState'],text=True)
  out[u]=dict(x.split('=',1) for x in s.strip().splitlines())
 return out
expected={x['path']:(x['size'],x['sha256']) for x in request['files']}
assert files()==expected and len(expected)==6
nginx=Path('/etc/nginx/snippets/tio-updates.conf')
old=nginx.read_bytes();assert digest(nginx)==request['nginx_sha256']
addon=request['addon'].encode();assert old.endswith(addon) and old.count(addon)==1
new=old[:-len(addon)]+b'location ^~ /unity/ {\n    add_header Cache-Control "no-store" always;\n    return 410;\n}\n'
accounts_before=account_state();assert accounts_before['count']>=208
legacy_before=legacy();services_before=units()
backup=Path(tempfile.mkdtemp(prefix='tio-before-unity-client-removal-',dir='/root'));backup.chmod(0o700)
(backup/'nginx-before.conf').write_bytes(old)
(backup/'unity-manifest-before.json').write_bytes((root/'manifest.json').read_bytes())
(backup/'removal-review.json').write_text(json.dumps(request,indent=2))
db=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
saved=sqlite3.connect(backup/'reservation.sqlite3')
try:
 db.backup(saved);assert saved.execute('pragma integrity_check').fetchone()[0]=='ok'
finally:saved.close();db.close()
subprocess.run(['tar','-czf',str(backup/'game-code-config.tar.gz'),'/opt/tio-emulator/server','/etc/tio-server/server.toml'],check=True,capture_output=True)
stat=nginx.stat();temp=nginx.with_name(nginx.name+'.unity-removal')
assert not temp.exists()
temp.write_bytes(new);os.chmod(temp,stat.st_mode&0o777);os.chown(temp,stat.st_uid,stat.st_gid);temp.replace(nginx)
try:
 subprocess.run(['nginx','-t'],check=True,capture_output=True)
 subprocess.run(['systemctl','reload','nginx'],check=True)
except BaseException:
 temp.write_bytes(old);os.chmod(temp,stat.st_mode&0o777);os.chown(temp,stat.st_uid,stat.st_gid);temp.replace(nginx)
 subprocess.run(['nginx','-t'],check=True,capture_output=True)
 subprocess.run(['systemctl','reload','nginx'],check=True)
 raise
assert files()==expected
# Exact inspected files only; no computed recursive deletion.
for name in expected:
 p=Path(name);assert p.parent==root or p.parent==root/'releases'
 assert p.resolve(strict=True).is_relative_to(root) and not p.is_symlink()
 assert (p.stat().st_size,digest(p))==expected[name]
 p.unlink()
(root/'releases').rmdir();root.rmdir()
assert not root.exists() and legacy()==legacy_before
accounts_after=account_state();assert accounts_after==accounts_before
v=os.statvfs('/')
out={'passed':True,'removed_namespace':str(root),'removed_files':list(expected),'backup':str(backup),'local_artifacts_preserved':request['local_artifacts'],'legacy_files_preserved':len(legacy_before['file_metadata']),'legacy_manifest_sha256':legacy_before['manifest_sha256'],'accounts_before':accounts_before,'accounts_after':accounts_after,'account_rows_preserved':True,'database_written':False,'local_player_data_uploaded':False,'manual_service_restarts':0,'nginx_reload':True,'nginx_before_sha256':hashlib.sha256(old).hexdigest(),'nginx_after_sha256':digest(nginx),'services_before':services_before,'services_after':units(),'available_bytes':v.f_bavail*v.f_frsize,'all_free_bytes':v.f_bfree*v.f_frsize}
(backup/'removal-result.json').write_text(json.dumps(out,indent=2))
print(json.dumps(out))
'''

def main():
    inspected = json.loads((REPORT / 'remote-inspect.json').read_bytes())
    candidates = {
        '2026.10.11.1.zip': ROOT / 'work/unity-full-client-20261011/release-package-build18/releases/2026.10.11.1.zip',
        '2026.10.11.2.zip': ROOT / 'work/unity-3d-maps-20261011/release-package-build21/releases/2026.10.11.2.zip',
        '2026.10.11.3.zip': ROOT / 'work/unity-ui-windows-20261011/package-ui-build29/releases/2026.10.11.3.zip',
        'manifest.json': ROOT / 'work/unity-ui-windows-20261011/package-ui-build29/manifest.json',
    }
    launcher = ROOT / 'work/unity-ui-windows-20261011/package-ui-build29/TIO-Reborn-Launcher.exe'
    local = []
    for item in inspected['files']:
        name = Path(item['path']).name
        p = candidates.get(name, launcher)
        assert p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(ROOT)
        assert (p.stat().st_size, digest(p)) == (item['size'], item['sha256']), str(p)
        local.append({'remote_path':item['path'],'preserved_local_path':str(p),'size':item['size'],'sha256':item['sha256']})
    addon = (ROOT / 'work/unity-ui-windows-20261011/publication-bundle/unity-publication-proposed.nginx').read_text()
    request = {'files':inspected['files'],'nginx_sha256':inspected['nginx']['state']['sha256'],'addon':addon,'local_artifacts':local,'authorization':'User: delete Unity client from hosting server; public namespace only.'}
    review_bytes=(json.dumps(request,indent=2)+'\n').encode()
    review_path=REPORT / 'review.json'
    if review_path.exists():
        assert review_path.read_bytes()==review_bytes
    else:
        with review_path.open('xb') as f:f.write(review_bytes)
    script = REMOTE.replace('REQUEST', repr(request), 1)
    r = subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@185.184.42.88','python3 -'], input=script,text=True,capture_output=True)
    if r.returncode:
        raise RuntimeError('Scoped Unity removal failed: '+r.stderr[-2500:])
    result=json.loads(r.stdout)
    with (REPORT / 'publication.json').open('xb') as f:f.write((json.dumps(result,indent=2)+'\n').encode())
    print(json.dumps({k:result[k] for k in ('passed','removed_namespace','backup','legacy_files_preserved','account_rows_preserved','available_bytes','services_after')}))

if __name__=='__main__':main()
