"""Publish the verified equipment DLL with fresh backups and HTTPS proof."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import urllib.request

from tools.deploy_gameplay_completion import ROOT
from tools.deploy_stage4_economy import remote
from deploy.client_equipment_batch import patch,patch_plan,BASE_SHA

READ=r'''
from pathlib import Path
import base64,json
print(json.dumps(dict(manifest=base64.b64encode(Path('/var/www/tio-client/updates/manifest.json').read_bytes()).decode())))
'''

PUBLISH=r'''
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import base64,fcntl,hashlib,json,os,shutil,sqlite3,subprocess,sys,tarfile,tempfile
p=json.load(sys.stdin);live=Path('/var/www/tio-client/updates');root=Path('/opt/tio-emulator')
lock=open('/root/.tio-gameplay-client.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def atomic(raw,target):
 fd,name=tempfile.mkstemp(prefix='.gameplay-',dir=target.parent);pending=Path(name)
 try:
  with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
  pending.chmod(0o644);pending.replace(target)
 finally:pending.unlink(missing_ok=True)
old=base64.b64decode(p['before_manifest'],validate=True);new=base64.b64decode(p['after_manifest'],validate=True)
if (live/'manifest.json').read_bytes()!=old:raise RuntimeError('Published client changed before release')
a,b=json.loads(old),json.loads(new)
if set(a)!=set(b) or any(a[k]!=b[k] for k in a if k not in ('version','files')):raise ValueError('Unexpected manifest metadata change')
if len(a['files'])!=len(b['files']) or [x['path'] for x in a['files']]!=[x['path'] for x in b['files']]:raise ValueError('Unexpected client file list')
changed=[y['path'] for x,y in zip(a['files'],b['files']) if x!=y]
if changed!=['silver.dll']:raise ValueError('Expected only equipment DLL change')
prior=next(x for x in a['files'] if x['path']=='silver.dll');record=next(x for x in b['files'] if x['path']=='silver.dll')
before=(live/'blobs'/prior['sha256']).read_bytes();raw=base64.b64decode(p['candidate'],validate=True)
if sha(before)!=p['base_sha256'] or sha(before)!=prior['sha256'] or len(before)!=prior['size']:raise RuntimeError('Published source blob changed')
if sha(raw)!=record['sha256'] or len(raw)!=record['size'] or record['seed']:raise ValueError('Candidate blob differs')
plan=p['plan']
if plan['previous_sha256']!=sha(before) or plan['updated_sha256']!=sha(raw) or not plan['all_other_published_bytes_preserved']:raise ValueError('Unverified bounded client plan')
allowed=set()
for change in plan['changes']:
 at=change['offset'];x=bytes.fromhex(change['before_hex']);y=bytes.fromhex(change['after_hex'])
 if type(at)is not int or at<0 or len(x)!=len(y) or at+len(x)>len(before) or before[at:at+len(x)]!=x or raw[at:at+len(y)]!=y:raise ValueError('Invalid bounded client edit')
 allowed.update(range(at,at+len(x)))
if len(plan['changes'])!=7 or any(x!=y and i not in allowed for i,(x,y) in enumerate(zip(before,raw))):raise ValueError('Unrelated published bytes changed')
if len(raw)-len(before)!=plan['appended_bytes']:raise ValueError('Unexpected extension size')
service=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True)
if 'ActiveState=active' not in service:raise RuntimeError('Hosted game service not active')
backup=Path(tempfile.mkdtemp(prefix='tio-before-equipment-client-',dir='/root'));backup.chmod(0o700)
(backup/'manifest.json').write_bytes(old);(backup/'silver.dll').write_bytes(before)
shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml')
shutil.copy2('/etc/systemd/system/tio-server.service',backup/'tio-server.service')
with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as archive:
 for directory,pattern in (('tio','*.py'),('server','*.py'),('tools','*.py'),('config','*.json')):
  for path in sorted((root/directory).rglob(pattern)):archive.add(path,arcname=path.relative_to(root).as_posix())
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
 src.backup(dst)
 if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Hosted save backup failed')
if (live/'manifest.json').read_bytes()!=old:raise RuntimeError('Client manifest changed during backup')
target=live/'blobs'/record['sha256']
if target.exists():
 if target.read_bytes()!=raw:raise RuntimeError('Existing immutable client blob differs')
else:atomic(raw,target)
atomic(new,live/'manifest.json')
if (live/'manifest.json').read_bytes()!=new or sha(target.read_bytes())!=record['sha256']:raise RuntimeError('Published client parity failed')
if subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True)!=service:raise RuntimeError('Game service changed during client publication')
report=dict(version=b['version'],backup=str(backup),source_sha256=sha(before),sha256=sha(raw),size=len(raw),changed=changed,
 timestamp_utc=datetime.now(timezone.utc).isoformat(),server_restarted=False,database_written=False,local_player_data_uploaded=False,
 other_published_bytes_preserved=True,service_unchanged=True,manifest_sha256=sha(new))
(backup/'publication.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--folder',required=True,type=Path)
    parser.add_argument('--version',required=True);parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args();folder=args.folder.resolve()
    if not folder.is_relative_to(ROOT/'reports/gameplay-completion'):raise ValueError('Expected gameplay report folder')
    if not re.fullmatch(r'\d{4}\.\d{2}\.\d{2}\.\d+',args.version):raise ValueError('Expected release version')
    if args.verify_only:
        report=json.loads((folder/'client/publication.json').read_text())
        if report['version']!=args.version:raise ValueError('Published version differs')
        verify_https(folder,args.version)
        print(json.dumps(dict(passed=True,version=args.version,trusted_https=True)))
        return
    if (folder/'client/publication.json').exists():raise ValueError('Preserve prior publication proof')
    qa=json.loads((folder/'hosted-equipment.json').read_text());validation=json.loads((folder/'validation.json').read_text())
    if not qa['passed'] or not validation['passed']:raise ValueError('Hosted and isolated server verification required')
    source=(folder/'client/source/silver.dll').read_bytes();candidate=(folder/'client/candidate/silver.dll').read_bytes()
    if hashlib.sha256(source).hexdigest()!=BASE_SHA or patch(source)!=candidate or patch(candidate)!=candidate:raise ValueError('Client candidate changed')
    plan=patch_plan(source,candidate)
    proof=json.loads((ROOT/'evidence/equipment_batch_client_native.json').read_text())
    if proof['candidate_sha256']!=hashlib.sha256(candidate).hexdigest():raise ValueError('Native proof candidate changed')
    old=base64.b64decode(remote(READ,{})['manifest'],validate=True);manifest=json.loads(old)
    if tuple(map(int,args.version.split('.')))<=tuple(map(int,manifest['version'].split('.'))):raise ValueError('Client version must increase')
    prior=next(x for x in manifest['files'] if x['path']=='silver.dll')
    if prior['sha256']!=BASE_SHA or prior['size']!=len(source):raise ValueError('Actual hosted client base changed')
    manifest['version']=args.version
    prior.update(sha256=hashlib.sha256(candidate).hexdigest(),size=len(candidate),seed=False)
    new=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    (folder/'client/previous-manifest.json').write_bytes(old);(folder/'client/manifest.json').write_bytes(new)
    report=remote(PUBLISH,dict(before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),
      candidate=base64.b64encode(candidate).decode(),base_sha256=BASE_SHA,plan=plan))
    with (folder/'client/publication.json').open('x',encoding='utf-8') as output:json.dump(report,output,indent=2)
    verify_https(folder,args.version)
    print(json.dumps(report))


def verify_https(folder,version):
    # The launcher's update origin is the documented IP virtual host. Its
    # certificate is checked normally, as in existing release verifiers.
    origin='https://185.184.42.88/updates/'
    new=(folder/'client/manifest.json').read_bytes()
    prior=next(r for r in json.loads(new)['files'] if r['path']=='silver.dll')
    with urllib.request.urlopen(origin+'manifest.json',timeout=30) as response:published=response.read()
    if published!=new:raise RuntimeError('HTTPS client manifest differs from published revision')
    with urllib.request.urlopen(origin+'blobs/'+prior['sha256'],timeout=60) as response:blob=response.read()
    if hashlib.sha256(blob).hexdigest()!=prior['sha256'] or len(blob)!=prior['size']:raise RuntimeError('HTTPS equipment blob differs')
    (folder/'client/https-verification.json').write_text(json.dumps(dict(passed=True,version=version,origin=origin,
       manifest_sha256=hashlib.sha256(published).hexdigest(),silver_sha256=prior['sha256'],trusted_https=True),indent=2)+'\n')


if __name__=='__main__':main()
