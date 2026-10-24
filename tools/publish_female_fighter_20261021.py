"""Validate and publish six female resources, preserving every hosted save."""
import argparse,base64,hashlib,json,math,struct,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_stage4_economy import remote
from tools.mdjx_mesh import read,encode
from tools.female_fighter_gui_20261021 import qa
from tools.publish_ability_icons_20261020 import STATE
OUT=qa.OUT;ASSET=qa.ASSET;VERSION='2026.10.21.1'
sha=lambda b:hashlib.sha256(b).hexdigest()
NEWS='Женская модель «Разведчица»: новые текстуры, геометрия и совместимый скелет. Обновите игру через лаунчер.'

REMOTE=r'''
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import base64,fcntl,hashlib,json,math,os,shutil,sqlite3,struct,subprocess,sys,tarfile,tempfile
p=json.load(sys.stdin);live=Path('/var/www/tio-client/updates');root=Path('/opt/tio-emulator')
lock=open('/root/.tio-gameplay-client.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
sha=lambda b:hashlib.sha256(b).hexdigest()
expected={'base/models/chr_woman_'+part+ext for part,ext in [('head','.mdjx'),('body','.mdjx'),('hands','.mdjx'),('legs','.mdjx'),('head','.jpg'),('body','.jpg')]}
def atomic(raw,target):
 fd,name=tempfile.mkstemp(prefix='.female-model-',dir=target.parent);pending=Path(name)
 try:
  with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
  pending.chmod(0o644);pending.replace(target)
 finally:pending.unlink(missing_ok=True)
def state():return subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True)
def protected():
 with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
  db.execute('BEGIN');assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  return {t:sha(repr(sorted(map(repr,db.execute('SELECT * FROM '+t).fetchall()))).encode()) for t in ('accounts','characters','owned_pets','wallets','warehouse_items','clans','clan_members')}
old=base64.b64decode(p['before_manifest'],validate=True);new=base64.b64decode(p['after_manifest'],validate=True)
assert (live/'manifest.json').read_bytes()==old,'Actual hosted client release changed'
a,b=json.loads(old),json.loads(new)
assert a['version']=='2026.10.20.5' and b['version']=='2026.10.21.1'
assert set(a)==set(b) and all(a[k]==b[k] for k in a if k not in ('version','files','news'))
assert b['news']==p['news']
assert len(a['files'])==len(b['files']) and [r['path'] for r in a['files']]==[r['path'] for r in b['files']]
ar={r['path']:r for r in a['files']};br={r['path']:r for r in b['files']}
assert len(ar)==len(a['files']) and {n for n in ar if ar[n]!=br[n]}==expected==set(p['files'])
payload={};prior={}
for name,value in p['files'].items():
 raw=base64.b64decode(value['raw'],validate=True);row=br[name]
 assert sha(raw)==row['sha256']==value['sha256'] and len(raw)==row['size'] and row['seed'] is False
 before=(live/'blobs'/ar[name]['sha256']).read_bytes()
 assert sha(before)==ar[name]['sha256'] and len(before)==ar[name]['size']
 if name.endswith('.mdjx'):
  nv,ni,nb,flag=struct.unpack_from('<4I',raw);assert 0<nv<20000 and ni%3==0 and 0<ni<100000 and nb in (1,10,43) and flag==1
  offset=16
  for _ in range(nv):
   count=struct.unpack_from('<I',raw,offset)[0];assert 0<count<=4
   values=struct.unpack_from('<8f',raw,offset+4);assert all(math.isfinite(v) for v in values)
   joints=struct.unpack_from('<'+str(count)+'I',raw,offset+40);assert max(joints)<nb
   weights=struct.unpack_from('<'+str(count)+'f',raw,offset+40+count*4)
   assert all(0<=w<=1.001 for w in weights) and abs(sum(weights)-1)<.002
   offset+=40+8*count
  indices=struct.unpack_from('<'+str(ni)+'I',raw,offset);assert max(indices)<nv
  assert sha(raw[offset+ni*4:])==value['bone_tail_sha256']
 else:assert raw[:2]==b'\xff\xd8' and raw[-2:]==b'\xff\xd9'
 payload[name]=raw;prior[name]=before
before_service=state();assert 'ActiveState=active' in before_service
before_protected=protected();config=Path('/etc/tio-server/server.toml').read_bytes()
if p['mode']=='validate':
 print(json.dumps(dict(passed=True,read_only=True,version=b['version'],changed=sorted(expected),service=before_service)))
 sys.exit(0)
assert p['mode']=='publish'
backup=Path(tempfile.mkdtemp(prefix='tio-before-female-fighter-',dir='/root'));backup.chmod(0o700)
(backup/'manifest.json').write_bytes(old)
for name,raw in prior.items():
 target=backup/'client'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml');shutil.copy2('/etc/systemd/system/tio-server.service',backup/'tio-server.service')
with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as archive:
 for directory,pattern in (('tio','*.py'),('server','*.py'),('tools','*.py'),('config','*.json'),('evidence','*.xml')):
  for path in sorted((root/directory).rglob(pattern)):archive.add(path,arcname=path.relative_to(root).as_posix())
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert (live/'manifest.json').read_bytes()==old and state()==before_service and protected()==before_protected
for name,raw in payload.items():
 target=live/'blobs'/br[name]['sha256']
 if target.exists():assert target.read_bytes()==raw
 else:atomic(raw,target)
assert (live/'manifest.json').read_bytes()==old
atomic(new,live/'manifest.json')
assert (live/'manifest.json').read_bytes()==new and state()==before_service
assert Path('/etc/tio-server/server.toml').read_bytes()==config
after_protected=protected();assert after_protected==before_protected,'External player activity detected; do not restore database'
r=dict(passed=True,version=b['version'],backup=str(backup),changed=sorted(expected),manifest_sha256=sha(new),
 service_unchanged=True,service=before_service,server_restarted=False,database_written=False,local_player_data_uploaded=False,
 protected_before=before_protected,protected_after=after_protected,unrelated_client_files_preserved=True,timestamp_utc=datetime.now(timezone.utc).isoformat())
(backup/'publication.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
'''

def validate():
 old=(OUT/'manifest-before.json').read_bytes();m=json.loads(old);rows={r['path']:r for r in m['files']}
 model=json.loads((ASSET/'model.json').read_text());rig=json.loads((ASSET/'rig-validation.json').read_text())
 assert model['passed'] and model['rig_bones']==51 and rig['passed'] and len(rig['sampled_deformations'])==18
 files={};parts=[]
 for item in model['parts']:
  path=ASSET/item['file'];raw=path.read_bytes();mesh=read(path);source=OUT/'source/base/models'/item['source'];base=read(source)
  assert sha(source.read_bytes())==rows['base/models/'+item['source']]['sha256']
  assert encode(mesh)==raw and mesh.tail==base.tail and mesh.bones==base.bones
  assert len(mesh.vertices)==item['vertices'] and len(mesh.indices)//3==item['triangles']
  assert all(len(v.joints)<=4 and abs(sum(v.weights)-1)<.002 and abs(math.sqrt(sum(c*c for c in v.normal))-1)<.003 for v in mesh.vertices)
  low=read(ASSET/'lod1'/path.name);assert low.tail==mesh.tail and len(low.indices)//3==item['lod1_triangles']
  parts.append(dict(file=item['file'],sha256=sha(raw),source_sha256=sha(source.read_bytes()),bone_tail_sha256=sha(mesh.tail),triangles=item['triangles']))
 raw=(ASSET/'scout.glb').read_bytes();magic,version,size=struct.unpack_from('<4sII',raw);assert magic==b'glTF' and version==2 and size==len(raw)
 length,kind=struct.unpack_from('<II',raw,12);assert kind==0x4e4f534a
 g=json.loads(raw[20:20+length]);assert len(g['meshes'])==5 and len(g['skins'])==1 and len(g['skins'][0]['joints'])==51
 assert {a['name'] for a in g['animations']}=={'Scout_Preview_Idle','Scout_Preview_Walk'}
 assert all({'POSITION','NORMAL','TEXCOORD_0','JOINTS_0','WEIGHTS_0'}<=set(p['attributes']) for mesh in g['meshes'] for p in mesh['primitives'])
 for name,relative in qa.MAPPING.items():
  raw=(ASSET/relative).read_bytes();value=dict(raw=base64.b64encode(raw).decode(),sha256=sha(raw))
  if name.endswith('.mdjx'):value['bone_tail_sha256']=sha(read(ASSET/relative).tail)
  files[name]=value;rows[name].update(sha256=sha(raw),size=len(raw),seed=False)
 m.update(version=VERSION,news=NEWS);new=(json.dumps(m,ensure_ascii=False,indent=2)+'\n').encode();(OUT/'manifest.json').write_bytes(new)
 visual=json.loads((OUT/'gui-visual-candidate.json').read_text());assert visual['passed'] and visual['real_game_client']
 result=dict(passed=True,rig_bones=51,blender_sampled_poses=18,glb_valid=True,parts=parts,native_default_triangles=sum(x['triangles'] for x in model['parts'] if x['part']!='hair'),native_default_parts=4,texture_count=2,preview_texture_count=3,
  optional_hair_in_blender_only=True,native_pistol_idle_verified=True,complete_battle_animation_regression=False,changed_paths=sorted(files))
 (OUT/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
 return dict(mode='validate',before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),files=files,news=NEWS)

def verify():
 new=(OUT/'manifest.json').read_bytes();origin='https://185.184.42.88/updates/'
 assert urllib.request.urlopen(origin+'manifest.json',timeout=30).read()==new
 rows={r['path']:r for r in json.loads(new)['files']}
 for name,relative in qa.MAPPING.items():assert urllib.request.urlopen(origin+'blobs/'+rows[name]['sha256'],timeout=30).read()==(ASSET/relative).read_bytes()
 state=remote(STATE,{});before=json.loads((OUT/'publication.json').read_text());assert state['integrity']=='ok' and state['service']==before['service']
 result=dict(passed=True,trusted_https=True,version=VERSION,verified_resources=6,manifest_sha256=sha(new),service=state['service'],accounts=state['accounts'],clans=state['clans'],integrity=state['integrity'])
 (OUT/'https-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','publish','verify','inspect'));mode=p.parse_args().mode
 if mode=='inspect':
  result=remote(STATE,{});(OUT/'hosted-before.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='protected'}))
 elif mode=='verify':verify()
 else:
  payload=validate();payload['mode']=mode
  if mode=='publish':assert not (OUT/'publication.json').exists()
  result=remote(REMOTE,payload);(OUT/('publication.json' if mode=='publish' else 'remote-validation.json')).write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if not k.startswith('protected_')}))
