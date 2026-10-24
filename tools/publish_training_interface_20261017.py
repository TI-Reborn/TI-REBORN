"""Publish four reviewed training catalogue type changes; no service restart."""
import hashlib,json,shlex,subprocess
from pathlib import Path
from check_training_interface_20261017 import prepare

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/training-status-20261017'
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@185.184.42.88']
REMOTE=r'''
import json,hashlib,fcntl,os,sqlite3,tempfile,tarfile,subprocess
from pathlib import Path
from contextlib import closing
request=json.load(__import__('sys').stdin);os.umask(0o077)
sha=lambda b:hashlib.sha256(b).hexdigest()
live=Path('/var/www/tio-client/updates');game=Path('/opt/tio-emulator')
fds=[]
for name in ('.tio-gameplay-client.lock','tio-client-archive-publication.lock'):
 fd=os.open('/root/'+name,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);fds.append(fd)
old=(live/'manifest.json').read_bytes();assert sha(old)==request['manifest_sha256']
manifest=json.loads(old);assert manifest['version']=='2026.10.17.1'
row=next(r for r in manifest['files'] if r['path']=='base/shared config/zones.xml')
client=(live/'blobs'/row['sha256']).read_bytes();server_path=game/'evidence/zones_diagnostic.xml';server=server_path.read_bytes()
assert client.decode()==request['client_before'] and server.decode()==request['server_before']
newclient=request['client_after'].encode();newserver=request['server_after'].encode()
from xml.etree import ElementTree as ET
def validate(before,after):
 a,b=ET.fromstring(before),ET.fromstring(after);assert len(a)==len(b)==22
 changed=[]
 for x,y in zip(a,b):
  assert x.attrib==y.attrib
  if ET.tostring(x)!=ET.tostring(y):
   i=int(x.get('id'));assert i in (19,20,21,22);changed.append(i)
   xp=next(v for v in x if v.get('key')=='type');yp=next(v for v in y if v.get('key')=='type')
   assert xp.get('val')=='base' and yp.get('val')=='base4';xp.set('val','base4');assert ET.tostring(x)==ET.tostring(y)
 assert changed==[19,20,21,22]
validate(client,newclient);validate(server,newserver)
status=lambda:subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True)
before_status=status();assert 'ActiveState=active' in before_status
backup=Path(tempfile.mkdtemp(prefix='tio-before-training-interface-',dir='/root'));backup.chmod(0o700)
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()==('ok',)
with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as archive:
 for directory in ('server','tio','tools','config','evidence'):
  archive.add(game/directory,arcname='code/'+directory,filter=lambda m:None if '__pycache__' in m.name.split('/') or m.name.endswith('.pyc') else m)
 archive.add('/etc/tio-server',arcname='etc/tio-server')
(backup/'previous-manifest.json').write_bytes(old);(backup/'previous-client-zones.xml').write_bytes(client);(backup/'previous-server-zones.xml').write_bytes(server)
(backup/'tio-server.service.txt').write_text(subprocess.check_output(['systemctl','cat','tio-server'],text=True))
updated=json.loads(old);updated['version']='2026.10.17.2'
newrow=next(r for r in updated['files'] if r['path']==row['path']);newrow['sha256']=sha(newclient);newrow['size']=len(newclient)
assert [a['path'] for a,b in zip(manifest['files'],updated['files']) if a!=b]==[row['path']]
newmanifest=json.dumps(updated,ensure_ascii=False,indent=2).encode()+b'\n'
def atomic(raw,target):
 fd,name=tempfile.mkstemp(prefix='.training-interface-',dir=target.parent)
 try:
  with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno());os.fchmod(out.fileno(),0o644)
  os.replace(name,target)
 finally:
  if os.path.exists(name):os.unlink(name)
assert (live/'manifest.json').read_bytes()==old and server_path.read_bytes()==server and status()==before_status
try:
 atomic(newclient,live/'blobs'/sha(newclient));atomic(newserver,server_path);atomic(newmanifest,live/'manifest.json')
 assert server_path.read_bytes()==newserver and status()==before_status
 assert (live/'manifest.json').read_bytes()==newmanifest
except BaseException:
 atomic(server,server_path);atomic(old,live/'manifest.json');raise
result=dict(passed=True,version=updated['version'],backup=str(backup),changed_towns=[19,20,21,22],service_restarted=False,database_restored=False,client_sha256=sha(newclient),server_sha256=sha(newserver),manifest_sha256=sha(newmanifest))
(backup/'publication.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
'''

def main():
 baseline=json.loads((OUT/'publication-baseline.json').read_text(encoding='utf-8'))
 proof=json.loads((OUT/'training-interface-proof.json').read_text(encoding='utf-8'));assert proof['passed']
 payload=dict(manifest_sha256=baseline['manifest_sha256'])
 for side in ('client','server'):
  raw=baseline[side+'_xml'].encode();new=prepare(raw)
  payload[side+'_before']=raw.decode();payload[side+'_after']=new.decode()
  (OUT/(side+'-zones-base4.xml')).write_bytes(new)
 if '--apply' not in __import__('sys').argv:
  print('Prepared exact hosted catalogue candidates; use --apply after native verification');return
 native=json.loads((OUT/'hosted-candidate-native.json').read_text(encoding='utf-8'))
 assert native['passed'] and native['candidate_xml_sha256']==hashlib.sha256(payload['client_after'].encode()).hexdigest()
 result=subprocess.run(SSH+['python3 -c '+shlex.quote(REMOTE)],input=json.dumps(payload),capture_output=True,encoding='utf-8',timeout=150)
 if result.returncode:raise RuntimeError(result.stderr[-1500:])
 (OUT/'publication.json').write_text(result.stdout,encoding='utf-8');print(result.stdout)

if __name__=='__main__':main()
