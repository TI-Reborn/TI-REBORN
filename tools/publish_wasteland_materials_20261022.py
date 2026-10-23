"""Guarded art-only publication with remote SQLite/code/config backup.

Candidate images are locally decoded and checked against exact published
originals. A private ZIP carries only the explicitly reviewed image paths;
no code, configuration, local databases or player saves are uploaded.
"""
import argparse,base64,collections,concurrent.futures,hashlib,json,subprocess,sys,urllib.request,zipfile
from pathlib import Path
from PIL import Image,ImageStat,ImageChops
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_stage4_economy import remote
from tools.build_visual_asset_catalog import decode
from tools.publish_ability_icons_20261020 import STATE
OUT=ROOT/'reports/remaining-textures-20261021';ASSET=ROOT/'assets/wasteland-materials-v1';ORIGINAL=ROOT/'work/remaining-textures-20261021/original'
VERSION='2026.10.22.1';PACKAGE=OUT/'wasteland-materials-client.zip'
REMOTE_PACKAGE='/root/tio-wasteland-materials-20261022.zip'
sha=lambda b:hashlib.sha256(b).hexdigest()

REMOTE=r'''
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path,PurePosixPath
import base64,fcntl,hashlib,json,os,shutil,sqlite3,subprocess,sys,tarfile,tempfile,zipfile
p=json.load(sys.stdin);live=Path('/var/www/tio-client/updates');root=Path('/opt/tio-emulator');package=Path('/root/tio-wasteland-materials-20261022.zip')
os.umask(0o077)
lock=open('/root/.tio-gameplay-client.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
sha=lambda b:hashlib.sha256(b).hexdigest()
old=base64.b64decode(p['before_manifest'],validate=True);new=base64.b64decode(p['after_manifest'],validate=True)
assert (live/'manifest.json').read_bytes()==old,'Hosted manifest changed; preserve other releases'
a,b=json.loads(old),json.loads(new);assert b['version']=='2026.10.22.1' and a['version']=='2026.10.21.8'
assert set(a)==set(b) and all(a[k]==b[k] for k in a if k not in ('version','files','news'))
assert len(a['files'])==len(b['files']) and [r['path'] for r in a['files']]==[r['path'] for r in b['files']]
ar={r['path']:r for r in a['files']};br={r['path']:r for r in b['files']};proof={r['path']:r for r in p['proof']};expected=set(proof)
assert len(ar)==len(a['files']) and len(expected)==328 and {n for n in ar if ar[n]!=br[n]}==expected
assert {g:sum(n.startswith('base/'+g+'/') for n in expected) for g in ('items','models','setting')}=={'items':8,'models':6,'setting':314}
assert sha(package.read_bytes())==p['package_sha256']
payload={};prior={}
with zipfile.ZipFile(package) as z:
 assert len(z.namelist())==328 and set(z.namelist())==expected
 for name in sorted(expected):
  q=PurePosixPath(name);assert not q.is_absolute() and '..' not in q.parts and q.suffix.lower() in ('.jpg','.png','.tga','.bmp')
  raw=z.read(name);record=proof[name]
  assert sha(raw)==record['sha256']==br[name]['sha256'] and len(raw)==record['size']==br[name]['size'] and br[name]['seed'] is False
  assert set(ar[name])==set(br[name]) and all(ar[name][k]==br[name][k] for k in ar[name] if k not in ('sha256','size','seed'))
  before=(live/'blobs'/ar[name]['sha256']).read_bytes();assert sha(before)==ar[name]['sha256']==record['source_sha256'] and len(before)==ar[name]['size']
  assert raw!=before and min(record['native_size'])>0 and max(record['native_size'])<=2048
  if name.startswith('base/models/'):
   assert raw[:2]==b'\xff\xd8' and raw[-2:]==b'\xff\xd9' and record['native_resolution_increased']
  else:assert record['native_size']==record['source_size'] and (record['original_alpha_exact'] or record.get('entirely_new_blender_geometry'))
  payload[name]=raw;prior[name]=before

def service():return subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True)
def protected():
 with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
  db.execute('BEGIN');assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  return {t:dict(rows=db.execute('SELECT count(*) FROM '+t).fetchone()[0],sha256=sha(repr(sorted(map(repr,db.execute('SELECT * FROM '+t).fetchall()))).encode())) for t in ('accounts','characters','owned_pets','wallets','warehouse_items','clans','clan_members')}
def atomic(raw,target):
 fd,name=tempfile.mkstemp(prefix='.wasteland-',dir=target.parent);pending=Path(name)
 try:
  with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
  pending.chmod(0o644);pending.replace(target)
 finally:pending.unlink(missing_ok=True)
before_service=service();assert 'ActiveState=active' in before_service;before_protected=protected()
config=Path('/etc/tio-server/server.toml').read_bytes()
if p['mode']=='validate':
 print(json.dumps(dict(passed=True,read_only=True,files=328,version=b['version'],service=before_service,protected=before_protected)));sys.exit(0)
assert p['mode']=='publish' and p['visual']['passed'] and p['visual']['real_game_client']
backup=Path(tempfile.mkdtemp(prefix='tio-before-wasteland-materials-',dir='/root'));backup.chmod(0o700)
(backup/'manifest.json').write_bytes(old);(backup/'candidate-manifest.json').write_bytes(new)
shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml');shutil.copy2('/etc/systemd/system/tio-server.service',backup/'tio-server.service')
with tarfile.open(backup/'previous-client-resources.tar.gz','w:gz') as archive:
 for name in sorted(expected):archive.add(live/'blobs'/ar[name]['sha256'],arcname=name)
with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as archive:
 for directory,pattern in (('tio','*.py'),('server','*.py'),('tools','*.py'),('config','*.json'),('evidence','*.xml')):
  for path in sorted((root/directory).rglob(pattern)):archive.add(path,arcname=path.relative_to(root).as_posix())
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert (live/'manifest.json').read_bytes()==old and service()==before_service
committed=False
try:
 for name,raw in payload.items():
  target=live/'blobs'/br[name]['sha256']
  if target.exists():assert target.read_bytes()==raw
  else:atomic(raw,target)
 assert (live/'manifest.json').read_bytes()==old
 atomic(new,live/'manifest.json');committed=True
 assert (live/'manifest.json').read_bytes()==new and service()==before_service and Path('/etc/tio-server/server.toml').read_bytes()==config
 after_protected=protected()
 r=dict(passed=True,version=b['version'],files=328,backup=str(backup),manifest_sha256=sha(new),service=before_service,
  server_restarted=False,database_written=False,local_player_data_uploaded=False,unrelated_client_files_preserved=True,
  protected_before=before_protected,protected_after=after_protected,protected_unchanged=before_protected==after_protected,
  timestamp_utc=datetime.now(timezone.utc).isoformat())
 (backup/'publication.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
except BaseException:
 if committed and (live/'manifest.json').read_bytes()==new:atomic(old,live/'manifest.json')
 raise
'''

def prepare():
    old=(OUT/'manifest-before.json').read_bytes();m=json.loads(old);assert m['version']=='2026.10.21.8'
    rows={r['path']:r for r in m['files']};proof=json.loads((OUT/'texture-proof.json').read_text(encoding='utf-8'));active={r['path'] for r in json.loads((OUT/'active-materials.json').read_text(encoding='utf-8'))}
    assert len(proof)==328 and {r['path'] for r in proof}==active
    evidence=[]
    for t in proof:
        name=t['path'];raw=(ASSET/'native'/name).read_bytes();before=(ORIGINAL/name).read_bytes()
        assert sha(before)==t['source_sha256']==rows[name]['sha256'] and sha(raw)==t['sha256'] and len(raw)==t['size'] and raw!=before
        old_im,_=decode(before);im,codec=decode(raw);assert list(im.size)==t['native_size']
        if t.get('entirely_new_blender_geometry'):
            assert name.startswith('base/items/') and im.size==old_im.size and im.getchannel('A').getextrema()==(0,255)
        elif t['native_resolution_increased']:
            assert name.startswith('base/models/') and old_im.getchannel('A').getextrema()==im.getchannel('A').getextrema()==(255,255)
            assert im.width/old_im.width==im.height/old_im.height and max(im.size)<=1024 and 1<im.width/old_im.width<=4
        else:assert im.size==old_im.size and im.getchannel('A').tobytes()==old_im.getchannel('A').tobytes()
        assert '_mask' not in name and not rows[name].get('seed')
        delta=ImageStat.Stat(ImageChops.difference(old_im.convert('RGB').resize(im.size,Image.Resampling.NEAREST),im.convert('RGB'))).mean
        evidence.append(dict(path=name,codec=codec,source=list(old_im.size),output=list(im.size),mean_rgb_change=delta,alpha_policy='new Blender prop' if t.get('entirely_new_blender_geometry') else 'opaque model UV' if t['native_resolution_increased'] else 'exact original'))
        rows[name].update(sha256=sha(raw),size=len(raw),seed=False)
    m.update(version=VERSION,news='Обновлены материалы окружения, грунта и оставшиеся текстуры моделей. Восемь новых иконок устройств построены в Blender. Обновите клиент через лаунчер.')
    new=(json.dumps(m,ensure_ascii=False,indent=2)+'\n').encode();(OUT/'manifest.json').write_bytes(new)
    with zipfile.ZipFile(PACKAGE,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for t in proof:z.write(ASSET/'native'/t['path'],t['path'])
    report=dict(passed=True,version=VERSION,files=328,groups=dict(collections.Counter(t['path'].split('/')[1] for t in proof)),
        newly_modelled_icons=8,new_terrain_surfaces=7,exact_alpha_sprites=314,opaque_model_atlases=6,manifest_sha256=sha(new),package_sha256=sha(PACKAGE.read_bytes()),package_size=PACKAGE.stat().st_size,
        art_method='Registered Blender material refinishing for existing sprites; separately modelled devices and new soil; painted Sick Miner UV atlas baked through Blender',
        every_resource_new_geometry=False,evidence=evidence)
    (OUT/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='evidence'}))

def payload(mode):
    report=json.loads((OUT/'validation.json').read_text(encoding='utf-8'));assert report['passed']
    assert sha(PACKAGE.read_bytes())==report['package_sha256']
    value=dict(mode=mode,before_manifest=base64.b64encode((OUT/'manifest-before.json').read_bytes()).decode(),after_manifest=base64.b64encode((OUT/'manifest.json').read_bytes()).decode(),
        package_sha256=report['package_sha256'],proof=json.loads((OUT/'texture-proof.json').read_text(encoding='utf-8')))
    if mode=='publish':value['visual']=json.loads((OUT/'gui-visual-candidate.json').read_text())
    return value

def upload():
    # This creates only the private root-owned staging ZIP; no hosted data is
    # downloaded into it and it contains no local accounts/configuration.
    r=subprocess.run(['scp','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=15',str(PACKAGE),'root@185.184.42.88:'+REMOTE_PACKAGE],capture_output=True,text=True,timeout=120)
    if r.returncode:raise RuntimeError('Private art package upload failed: '+r.stderr)
    remote("import os,json;from pathlib import Path;p=Path('/root/tio-wasteland-materials-20261022.zip');p.chmod(0o600);print(json.dumps(dict(private_art_package=True,size=p.stat().st_size)))",{})
    print(json.dumps(dict(uploaded_private_art_package=True,bytes=PACKAGE.stat().st_size)))

def verify():
    raw=urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=30).read();assert raw==(OUT/'manifest.json').read_bytes();rows={r['path']:r for r in json.loads(raw)['files']};proof=json.loads((OUT/'texture-proof.json').read_text(encoding='utf-8'))
    def one(t):
        b=urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+rows[t['path']]['sha256'],timeout=40).read();assert sha(b)==t['sha256'] and b==(ASSET/'native'/t['path']).read_bytes();return len(b)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:total=sum(pool.map(one,proof))
    state=remote(STATE,{});published=json.loads((OUT/'publication.json').read_text());assert state['integrity']=='ok' and state['service']==published['service']
    result=dict(passed=True,version=VERSION,trusted_https=True,verified_resources=len(proof),verified_bytes=total,manifest_sha256=sha(raw),service=state['service'],integrity=state['integrity'],accounts=state['accounts'],clans=state['clans'])
    (OUT/'https-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('prepare','upload','validate','publish','verify'));mode=p.parse_args().mode
    if mode=='prepare':prepare()
    elif mode=='upload':upload()
    elif mode=='verify':verify()
    else:
        if mode=='publish':assert not (OUT/'publication.json').exists()
        r=remote(REMOTE,payload(mode));(OUT/('publication.json' if mode=='publish' else 'remote-validation.json')).write_text(json.dumps(r,indent=2));print(json.dumps({k:v for k,v in r.items() if not k.startswith('protected')}))
