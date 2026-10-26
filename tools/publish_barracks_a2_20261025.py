"""Publish the scoped barracks/art release while preserving hosted saves."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.deploy_stage4_economy import remote

OUT = ROOT / 'reports/barracks-a2-20261025'
XML = 'base/shared config/items.xml'
REMOTE = r'''
from contextlib import closing
from pathlib import Path
import base64,fcntl,hashlib,json,os,shutil,sqlite3,subprocess,sys,tarfile,tempfile,time
from xml.etree import ElementTree as ET
p=json.load(sys.stdin);root=Path('/opt/tio-emulator');live=Path('/var/www/tio-client/updates')
dbpath=Path('/var/lib/tio-server/reservation.sqlite3');server=root/'evidence/items_diagnostic.xml'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def run(*args):return subprocess.check_output(args,text=True,cwd=root,timeout=60).strip()
if p['mode']=='stage':
 stage=Path(tempfile.mkdtemp(prefix='tio-barracks-a2-stage-',dir='/root'));stage.chmod(0o700)
 print(json.dumps(dict(folder=str(stage))));sys.exit(0)
lock=open('/root/.tio-gameplay-client.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
stage=Path(p['stage']['folder'])
assert stage.parent==Path('/root') and stage.name.startswith('tio-barracks-a2-stage-') and not stage.is_symlink()
archive=stage/'release.tar.gz';assert sha(archive.read_bytes())==p['stage']['sha256']
old=base64.b64decode(p['before_manifest'],validate=True);new=base64.b64decode(p['after_manifest'],validate=True)
assert (live/'manifest.json').read_bytes()==old,'Public release changed'
a=json.loads(old);b=json.loads(new);ar={r['path']:r for r in a['files']};br={r['path']:r for r in b['files']}
first=a['version']=='2026.10.24.2' and b['version']=='2026.10.25.1'
hotfix=a['version']=='2026.10.25.1' and b['version']=='2026.10.25.2'
assert first or hotfix
assert set(b)==set(a)-{'archive'}
assert all(a[k]==b[k] for k in b if k not in ('version','news','newsEn','files'))
assert len(ar)==len(a['files'])==(6658 if first else 6905) and len(br)==len(b['files'])==6905
assert [r['path'] for r in b['files'][:len(a['files'])]]==[r['path'] for r in a['files']]
assert all(ar[n]==br[n] for n in ar if n not in ('silver.dll','base/shared config/items.xml'))
ids=p['ids'];hd=p['hd_ids'];assert ids==sorted(set(ids)) and len(ids)==101 and len(hd)==len(set(hd))==146
pngs={f'base/items/tio_ii_{i}.png' for i in ids}|{f'base/items/hd/tio_ih_{i}_512.png' for i in hd}
assert set(br)-set(ar)==(pngs if first else set()) and set(p['resources'])==pngs|{'silver.dll','base/shared config/items.xml'}
if hotfix:assert ar['base/shared config/items.xml']==br['base/shared config/items.xml']
raws={}
with tarfile.open(archive,'r:gz') as tar:
 members=tar.getmembers();assert len(members)==len(p['resources'])
 expected={v['sha256'] for v in p['resources'].values()}
 assert {m.name for m in members}==expected and len(expected)==len(members)
 for m in members:
  assert m.isfile() and m.size<=16*1024**2
  with tar.extractfile(m) as f:raw=f.read()
  assert sha(raw)==m.name;raws[m.name]=raw
payload={}
for n,row in p['resources'].items():
 r=br[n];raw=raws[row['sha256']]
 assert sha(raw)==r['sha256']==row['sha256'] and len(raw)==r['size']==row['size'] and r['seed'] is False
 if n in pngs:
  import struct
  expected=(512,512) if '/hd/' in n else (64,32)
  assert raw[:8]==b'\x89PNG\r\n\x1a\n' and struct.unpack('!II',raw[16:24])==expected
 payload[n]=raw
def semantic(n,omit=()):
 return n.tag,tuple(sorted(n.attrib.items())),(n.text or '').strip(),tuple(semantic(c,omit) for c in n if not(c.tag=='value' and c.get('key') in omit))
def verify_xml(before,after,client=False):
 xroot=ET.fromstring(before);yroot=ET.fromstring(after)
 assert xroot.tag==yroot.tag=='items' and xroot.attrib==yroot.attrib
 x={int(n.get('id')):n for n in xroot};y={int(n.get('id')):n for n in yroot}
 assert len(x)==len(xroot)==len(y)==len(yroot)==164 and x.keys()==y.keys()
 for i in x:
  omit=('image',) if i in ids else ()
  if client and i in (17,18,19,30):omit+=('stackable',)
  assert semantic(x[i],omit)==semantic(y[i],omit),('Unrelated item metadata changed',i)
  if i in ids:assert [n.get('val') for n in y[i].findall("value[@key='image']")]==[f'tio_ii_{i}.png']
  if client and i in (17,18,19,30):assert [n.get('val') for n in y[i].findall("value[@key='stackable']")]==['1']
 return {i:y[i].get('name') for i in ids}
client_before=(live/'blobs'/ar['base/shared config/items.xml']['sha256']).read_bytes()
assert sha(client_before)==ar['base/shared config/items.xml']['sha256']
names=verify_xml(client_before,payload['base/shared config/items.xml'],True)
server_before=server.read_bytes();server_after=base64.b64decode(p['server_raw'],validate=True)
assert sha(server_before)==p['server_before_sha256'] and sha(server_after)==p['server_sha256']
assert verify_xml(server_before,server_after)==names
assert ar['silver.dll']['sha256']==('28f33ff6a920182eeb7a81b9d3c30853081f3f52c7d505da15b54de97c01b2ad' if first else 'f56a6267676a011ea9cfce7f17c266f1bb43b6d7a65969d3cf242fccf4b4e135')
assert payload['silver.dll'][:2]==b'MZ' and len(payload['silver.dll'])==8487424
for i in (17,18,19,30):
 assert ET.fromstring(server_before).find(f"item[@id='{i}']/value[@key='stackable']").get('val')=='1'
def fingerprint():
 with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
  db.execute('BEGIN');assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  tables=('accounts','characters','owned_pets','wallets','warehouse_items','clans','clan_members')
  return {t:dict(rows=db.execute('SELECT count(*) FROM '+t).fetchone()[0],sha256=sha(repr(sorted(map(repr,db.execute('SELECT * FROM '+t).fetchall()))).encode())) for t in tables}
def idle(rows_only=False):
 if not rows_only and run('ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'):
  raise RuntimeError('Active players; preserve connections')
 with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
  for table in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs'):
   if db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():raise RuntimeError('Retained battle state')
def atomic(raw,target):
 previous=target.stat() if target.exists() else None
 fd,name=tempfile.mkstemp(prefix='.barracks-a2-',dir=target.parent);pending=Path(name)
 try:
  with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  pending.chmod(previous.st_mode&0o777 if previous else 0o644)
  if previous:os.chown(pending,previous.st_uid,previous.st_gid)
  pending.replace(target)
 finally:pending.unlink(missing_ok=True)
assert os.statvfs('/').f_bavail*os.statvfs('/').f_frsize>4*1024**3+sum(map(len,payload.values()))
service=run('systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts');assert 'ActiveState=active' in service
if p['mode']=='validate':
 print(json.dumps(dict(passed=True,read_only=True,version=b['version'],resources=len(payload),service=service)));sys.exit(0)
assert p['mode']=='publish';idle();before=fingerprint();config=Path('/etc/tio-server/server.toml').read_bytes()
backup=Path(tempfile.mkdtemp(prefix='tio-before-barracks-a2-release-',dir='/root'));backup.chmod(0o700)
(backup/'manifest.json').write_bytes(old);(backup/'previous-client-items.xml').write_bytes(client_before)
(backup/'previous-server-items.xml').write_bytes(server_before)
silver_before=(live/'blobs'/ar['silver.dll']['sha256']).read_bytes();assert sha(silver_before)==ar['silver.dll']['sha256'];(backup/'silver.dll').write_bytes(silver_before)
for path in ('/etc/tio-server/server.toml','/etc/systemd/system/tio-server.service'):shutil.copy2(path,backup/Path(path).name)
with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as tar:
 for directory in ('tio','server','tools','deploy','config','evidence'):
  for path in sorted((root/directory).rglob('*')):
   if path.is_file() and path.suffix in ('.py','.xml','.json','.toml','.js'):tar.add(path,arcname=path.relative_to(root).as_posix())
with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
for name,raw in payload.items():
 target=live/'blobs'/br[name]['sha256']
 if target.exists():assert target.read_bytes()==raw
 else:atomic(raw,target)
# Reuse the adopted builder over verified hosted blobs. The ZIP is immutable;
# its descriptor is committed together with the resource manifest.
builder={'__name__':'barracks_archive_builder'}
exec(compile(p['archive_builder'],'launcher/build_archive.py','exec'),builder)
archive_path=stage/'client-full.zip'
descriptor=builder['build'](b,live/'blobs',archive_path)
assert os.statvfs('/').f_bavail*os.statvfs('/').f_frsize>4*1024**3
archive_target=live/'blobs'/descriptor['sha256']
if archive_target.exists():
 assert builder['digest'](archive_target)==descriptor['sha256'];archive_path.unlink()
else:
 archive_path.chmod(0o644);archive_path.replace(archive_target)
b['archive']=descriptor;new=(json.dumps(b,ensure_ascii=False,indent=2)+'\n').encode()
assert (live/'manifest.json').read_bytes()==old and server.read_bytes()==server_before
idle();run('systemctl','stop','tio-server');committed=False
try:
 idle(True);assert fingerprint()==before
 assert (live/'manifest.json').read_bytes()==old and server.read_bytes()==server_before
 committed=True;atomic(server_after,server);atomic(new,live/'manifest.json')
 assert fingerprint()==before and Path('/etc/tio-server/server.toml').read_bytes()==config
 preflight=run('runuser','-u','tio','--',str(root/'.venv/bin/python'),'-m','server','--config','/etc/tio-server/server.toml','--check')
 run('systemctl','start','tio-server');deadline=time.monotonic()+20
 while time.monotonic()<deadline:
  health=run('systemctl','is-active','tio-server');listeners=run('ss','-Hltn','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )')
  if health=='active' and all(':'+str(port) in listeners for port in (28512,28513,29512,29513)):break
  time.sleep(.2)
 else:raise RuntimeError('Service health failed')
 assert (live/'manifest.json').read_bytes()==new and server.read_bytes()==server_after
except BaseException:
 run('systemctl','stop','tio-server')
 if committed:atomic(server_before,server);atomic(old,live/'manifest.json')
 run('systemctl','start','tio-server');raise
result=dict(passed=True,version=b['version'],backup=str(backup),resources=len(payload),player_data_preserved=True,
 database_restored=False,local_player_data_uploaded=False,manifest_sha256=sha(new),server_xml_sha256=sha(server_after),
 service_before=service,service_after=run('systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'),protected_before=before,archive=descriptor)
(backup/'publication.json').write_text(json.dumps(result,indent=2)+'\n')
result['published_manifest']=base64.b64encode(new).decode();print(json.dumps(result))
'''


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stage() -> None:
    build = json.loads((OUT / 'build.json').read_bytes())
    target = OUT / 'release.tar.gz'
    with tarfile.open(target, 'w:gz') as tar:
        for name, row in build['resources'].items():
            raw = (OUT / 'client' / name).read_bytes()
            assert digest(raw) == row['sha256']
            info = tarfile.TarInfo(row['sha256'])
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
    receipt = remote(REMOTE, dict(mode='stage'))
    subprocess.run(['scp', '-i', str(Path.home()/'.ssh/tio_server'),
                    '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
                    str(target), 'root@185.184.42.88:'+receipt['folder']+'/release.tar.gz'],
                   check=True, timeout=180, capture_output=True)
    receipt['sha256'] = digest(target.read_bytes())
    (OUT / 'stage.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(dict(staged=True, bytes=target.stat().st_size)))


def payload(mode: str) -> dict:
    build = json.loads((OUT / 'build.json').read_bytes())
    return dict(mode=mode, stage=json.loads((OUT/'stage.json').read_bytes()),
                before_manifest=base64.b64encode((OUT/'published-20261025.1/manifest.json').read_bytes()).decode(),
                after_manifest=base64.b64encode((OUT/'manifest.json').read_bytes()).decode(),
                resources=build['resources'], ids=build['changed_item_ids'], hd_ids=build['hd_item_ids'],
                archive_builder=(ROOT/'launcher/build_archive.py').read_text(encoding='utf-8'),
                server_raw=base64.b64encode((OUT/'server-items.xml').read_bytes()).decode(),
                server_before_sha256=build['server_before_sha256'], server_sha256=build['server_sha256'])


def verify() -> None:
    manifest = (OUT/'manifest.json').read_bytes()
    assert urllib.request.urlopen('https://185.184.42.88/updates/manifest.json', timeout=30).read() == manifest
    build = json.loads((OUT/'build.json').read_bytes())
    for name, row in build['resources'].items():
        raw = urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+row['sha256'], timeout=30).read()
        assert digest(raw) == row['sha256'] and len(raw) == row['size'], name
    result = dict(passed=True, trusted_https=True, resources=len(build['resources']),
                  manifest_sha256=digest(manifest), version=build['version'])
    (OUT/'https-verification.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('stage', 'validate', 'publish', 'verify'))
    mode = parser.parse_args().mode
    if mode == 'stage':
        stage()
    elif mode == 'verify':
        verify()
    else:
        if mode == 'publish':
            if (OUT/'publication.json').exists():
                assert json.loads((OUT/'publication.json').read_bytes())['version'] != json.loads((OUT/'build.json').read_bytes())['version']
            assert not (OUT/'release-hold.json').exists(), 'Candidate superseded by the owner reference; rebuild and revalidate first'
            review = json.loads((OUT/'reference-review.json').read_bytes())
            build = json.loads((OUT/'build.json').read_bytes())
            assert review['silver_sha256'] == build['silver_sha256']
            assert review['thematic_tests'] == 29 and review['server_tests'] == 659
            assert review['full_hd_100_and_125_verified'] is True
        result = remote(REMOTE, payload(mode))
        if mode == 'publish':
            manifest = base64.b64decode(result.pop('published_manifest'), validate=True)
            assert digest(manifest) == result['manifest_sha256']
            (OUT/'manifest.json').write_bytes(manifest)
        (OUT/('publication.json' if mode == 'publish' else 'validation-remote.json')).write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps({key: value for key, value in result.items() if key != 'protected_before'}))
