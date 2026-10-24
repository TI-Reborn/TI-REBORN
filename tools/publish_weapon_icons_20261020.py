"""Publish only weapon PNGs and image fields, preserving hosted accounts/saves."""
import argparse,base64,hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_stage4_economy import remote
OUT=ROOT/'reports/weapon-icons-20261020'
XML='base/shared config/items.xml'
SERVER='evidence/items_diagnostic.xml'
IDS=list(range(300,342))+[5001,5013,65489]
sha=lambda b:hashlib.sha256(b).hexdigest()

REMOTE=r'''
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import base64,fcntl,hashlib,json,os,re,shutil,sqlite3,struct,subprocess,sys,tarfile,tempfile,time
from xml.etree import ElementTree as ET
p=json.load(sys.stdin);root=Path('/opt/tio-emulator');live=Path('/var/www/tio-client/updates')
dbpath=Path('/var/lib/tio-server/reservation.sqlite3');server=root/'evidence/items_diagnostic.xml'
IDS=list(range(300,342))+[5001,5013,65489];XML='base/shared config/items.xml'
lock=open('/root/.tio-gameplay-client.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
sha=lambda b:hashlib.sha256(b).hexdigest()
def run(*args):return subprocess.check_output(args,text=True,cwd=root,timeout=60).strip()
def protected():
 with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
  db.execute('BEGIN');assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  return {t:sha(repr(sorted(map(repr,db.execute('SELECT * FROM '+t).fetchall()))).encode()) for t in ('accounts','characters','owned_pets','wallets','warehouse_items','clans','clan_members')}
def idle(rows_only=False):
 if not rows_only and run('ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'):raise RuntimeError('Active players; preserve connections and retry later')
 with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
  for t in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs'):
   if db.execute('SELECT 1 FROM '+t+' LIMIT 1').fetchone():raise RuntimeError('Retained battle state; no release applied')
def atomic(raw,target):
 fd,name=tempfile.mkstemp(prefix='.weapon-icons-',dir=target.parent);pending=Path(name)
 try:
  with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
  pending.chmod(0o644);pending.replace(target)
 finally:pending.unlink(missing_ok=True)
def semantic(n,omit=False):
 return n.tag,tuple(sorted(n.attrib.items())),(n.text or '').strip(),tuple(semantic(c,omit) for c in n if not(omit and c.tag=='value' and c.get('key')=='image'))
def verify_xml(before,after):
 a=ET.fromstring(before);b=ET.fromstring(after)
 assert a.tag==b.tag=='items' and a.attrib==b.attrib
 x={int(n.get('id')):n for n in a};y={int(n.get('id')):n for n in b}
 assert len(x)==len(a)==len(y)==len(b)==164 and set(x)==set(y)
 assert sorted(i for i in x if semantic(x[i])!=semantic(y[i]))==IDS
 assert all(semantic(x[i],True)==semantic(y[i],True) for i in x),'Gameplay metadata changed'
 for i in IDS:
  names=[n.get('val') for n in y[i].findall('value') if n.get('key')=='image']
  assert names==[f'tio_wi_{i}.png']
 return {i:y[i].get('name') for i in IDS}
old=base64.b64decode(p['before_manifest'],validate=True);new=base64.b64decode(p['after_manifest'],validate=True)
assert (live/'manifest.json').read_bytes()==old,'Client release changed'
a=json.loads(old);b=json.loads(new)
assert a['version']=='2026.10.20.4' and b['version']=='2026.10.20.5'
assert set(a)==set(b) and all(a[k]==b[k] for k in a if k not in ('version','files'))
ar={r['path']:r for r in a['files']};br={r['path']:r for r in b['files']}
pngs={f'base/items/tio_wi_{i}.png' for i in IDS}
assert set(br)==set(ar)|pngs and not(set(ar)&pngs)
assert len(br)==len(b['files'])==len(a['files'])+45
assert [r['path'] for r in b['files'][:len(a['files'])]]==[r['path'] for r in a['files']]
assert all(ar[n]==br[n] for n in ar if n!=XML),'Existing unrelated client record changed'
assert set(p['files'])==pngs|{XML}
payload={}
for n,row in p['files'].items():
 raw=base64.b64decode(row['raw'],validate=True);r=br[n]
 assert sha(raw)==r['sha256']==row['sha256'] and len(raw)==r['size'] and r['seed'] is False
 if n in pngs:
  assert raw[:8]==b'\x89PNG\r\n\x1a\n' and struct.unpack('!II',raw[16:24])==(64,32)
 payload[n]=raw
client_before=(live/'blobs'/ar[XML]['sha256']).read_bytes()
assert sha(client_before)==ar[XML]['sha256'];client_names=verify_xml(client_before,payload[XML])
server_before=server.read_bytes();server_after=base64.b64decode(p['server_raw'],validate=True)
assert sha(server_before)==p['server_before_sha256'] and sha(server_after)==p['server_sha256']
assert verify_xml(server_before,server_after)==client_names
service=run('systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts')
assert 'ActiveState=active' in service
idle();before=protected();config=Path('/etc/tio-server/server.toml').read_bytes()
if p['mode']=='validate':
 print(json.dumps(dict(passed=True,read_only=True,items=45,new_files=45,version=b['version'],only_image_fields_changed=True,executable_changes=False,active_players=False,retained_battles=False,service=service)))
 sys.exit(0)
assert p['mode']=='publish'
backup=Path(tempfile.mkdtemp(prefix='tio-before-weapon-icons-',dir='/root'));backup.chmod(0o700)
(backup/'manifest.json').write_bytes(old);(backup/'previous-client-items.xml').write_bytes(client_before)
(backup/'previous-server-items.xml').write_bytes(server_before)
shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml')
shutil.copy2('/etc/systemd/system/tio-server.service',backup/'tio-server.service')
with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as archive:
 for directory,pattern in (('tio','*.py'),('server','*.py'),('tools','*.py'),('config','*.json'),('evidence','*.xml')):
  for path in sorted((root/directory).rglob(pattern)):archive.add(path,arcname=path.relative_to(root).as_posix())
with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert (live/'manifest.json').read_bytes()==old and server.read_bytes()==server_before
for name,raw in payload.items():
 target=live/'blobs'/br[name]['sha256']
 if target.exists():assert target.read_bytes()==raw
 else:atomic(raw,target)
# Stop only after a second idle guard. This also refreshes the cached rules
# digest which includes the full item XML, even though only artwork changed.
idle();run('systemctl','stop','tio-server')
committed=False
try:
 idle(True);assert protected()==before
 assert (live/'manifest.json').read_bytes()==old and server.read_bytes()==server_before
 committed=True;atomic(server_after,server);atomic(new,live/'manifest.json')
 assert protected()==before,'Player data changed while stopped'
 assert Path('/etc/tio-server/server.toml').read_bytes()==config
 preflight=run('runuser','-u','tio','--',str(root/'.venv/bin/python'),'-m','server','--config','/etc/tio-server/server.toml','--check')
 assert protected()==before
 run('systemctl','start','tio-server')
 deadline=time.monotonic()+20
 while time.monotonic()<deadline:
  health=run('systemctl','is-active','tio-server')
  listeners=run('ss','-Hltn','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )')
  if health=='active' and all(':'+str(port) in listeners for port in (28512,28513,29512,29513)):break
  time.sleep(.2)
 else:raise RuntimeError('Updated service failed health check')
 assert (live/'manifest.json').read_bytes()==new and server.read_bytes()==server_after
except BaseException:
 run('systemctl','stop','tio-server')
 if committed:atomic(server_before,server);atomic(old,live/'manifest.json')
 run('systemctl','start','tio-server')
 raise
r=dict(passed=True,version=b['version'],backup=str(backup),items=45,new_client_files=45,
 modified_client_files=[XML],modified_server_files=['evidence/items_diagnostic.xml'],
 only_item_image_fields_changed=True,server_restarted=True,reason='Refresh the cached item-XML rules digest while no players/battles are active',
 player_data_preserved=True,database_restored=False,local_player_data_uploaded=False,executable_changes=False,
 service_before=service,service_after=run('systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'),
 config_sha256=sha(config),manifest_sha256=sha(new),server_xml_sha256=sha(server_after),
 timestamp_utc=datetime.now(timezone.utc).isoformat(),protected_before=before)
(backup/'publication.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
'''


def payload(mode):
    build=json.loads((OUT/'build.json').read_text(encoding='utf-8'))
    assert build['passed'] and build['changed_item_ids']==IDS
    files={}
    manifest=json.loads((OUT/'manifest.json').read_bytes())
    for n in [XML]+[x['path'] for x in build['new_files']]:
        raw=(OUT/'client'/n).read_bytes();r=next(r for r in manifest['files'] if r['path']==n)
        assert sha(raw)==r['sha256'] and len(raw)==r['size']
        files[n]=dict(raw=base64.b64encode(raw).decode(),sha256=sha(raw))
    return dict(mode=mode,before_manifest=base64.b64encode((OUT/'manifest-before.json').read_bytes()).decode(),
                after_manifest=base64.b64encode((OUT/'manifest.json').read_bytes()).decode(),files=files,
                server_raw=base64.b64encode((OUT/'server'/SERVER).read_bytes()).decode(),
                server_before_sha256=build['server_before_sha256'],server_sha256=build['server_sha256'])


def verify():
    origin='https://185.184.42.88/updates/'
    new=(OUT/'manifest.json').read_bytes();assert urllib.request.urlopen(origin+'manifest.json',timeout=20).read()==new
    p=payload('validate')
    for name,entry in p['files'].items():
        raw=urllib.request.urlopen(origin+'blobs/'+entry['sha256'],timeout=30).read()
        assert raw==base64.b64decode(entry['raw']),name
    r=remote("from pathlib import Path\nimport json,hashlib,subprocess,sqlite3\nr=dict(service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),server_xml_sha256=hashlib.sha256(Path('/opt/tio-emulator/evidence/items_diagnostic.xml').read_bytes()).hexdigest())\nwith sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:r.update(integrity=db.execute('pragma integrity_check').fetchone()[0],accounts=db.execute('select count(*) from accounts').fetchone()[0],clans=db.execute('select count(*) from clans').fetchone()[0])\nprint(json.dumps(r))",{})
    assert r['service']=='active' and r['integrity']=='ok' and r['server_xml_sha256']==p['server_sha256']
    r.update(passed=True,trusted_https=True,version='2026.10.20.5',verified_resources=46,manifest_sha256=sha(new))
    (OUT/'https-verification.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('mode',choices=('validate','publish','verify'));mode=a.parse_args().mode
    if mode=='verify':verify()
    else:
        if mode=='publish':assert not (OUT/'publication.json').exists()
        result=remote(REMOTE,payload(mode));(OUT/(mode+'.json' if mode!='publish' else 'publication.json')).write_text(json.dumps(result,indent=2))
        print(json.dumps({k:v for k,v in result.items() if k!='protected_before'}))
