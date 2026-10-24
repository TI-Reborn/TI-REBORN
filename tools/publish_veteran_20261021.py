"""Publish the approved Veteran as six separate resources and four XML bindings.

Existing shared male textures/armor/hands stay byte-identical. Publish immutable
files and manifest before the authoritative B9 catalog references the new names.
Never copy local saves or write the hosted database.
"""
import argparse,base64,hashlib,inspect,json,math,sys,urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_stage4_economy import remote
from tools.mdjx_mesh import read,encode
from tools.dog_native_animation import animation
from tools.publish_ability_icons_20261020 import STATE
OUT=ROOT/'reports/veteran-release-20261021';ASSET=ROOT/'assets/fighter-model-v1'
VERSION='2026.10.21.6';XML='base/shared config/items.xml';ORIGIN='https://185.184.42.88/updates/'
MAPPING={**{'base/models/tio_vet_'+p+'.mdjx':'native/tio_vet_'+p+'.mdjx' for p in ('head','torso','legs','hands')},
         **{'base/models/tio_vet_'+p+'.jpg':'textures/tio_vet_'+p+'.jpg' for p in ('head','body')}}
NEWS='Мужская модель «Ветеран»: новое лицо, полевая рубашка, брюки и ботинки. Совместимость с бронёй и прежняя окраска Pantsu kudasai сохранены. Обновите игру через лаунчер.'
sha=lambda raw:hashlib.sha256(raw).hexdigest()


def changes():
    return {65500:{'model_1':'tio_vet_head','texture_1':'tio_vet_head.jpg'},
            65501:{'model_1':'tio_vet_torso','texture_1':'tio_vet_body.jpg','model_2':'tio_vet_hands','texture_2':'tio_vet_body.jpg'},
            65502:{'model_1':'tio_vet_legs','texture_1':'tio_vet_body.jpg'},
            206:{'model_2':'tio_vet_legs','texture_2':'tio_vet_body.jpg'}}


def patch(raw):
    for identity,fields in changes().items():
        start=raw.index(('<item id="'+str(identity)+'" ').encode());end=raw.index(b'</item>',start)
        block=raw[start:end]
        for key,value in fields.items():
            lines=[line for line in block.splitlines(keepends=True) if ('key="'+key+'"').encode() in line]
            assert len(lines)==1,(identity,key)
            line=lines[0];at=line.index(b'val="')+5;stop=line.index(b'"',at)
            assert line[at:stop]!=value.encode(),'Already patched catalog'
            block=block.replace(line,line[:at]+value.encode()+line[stop:],1)
        raw=raw[:start]+block+raw[end:]
    return raw


def validate_catalog(before,after):
    from xml.etree import ElementTree as ET
    def structure(node):return (node.tag,dict(node.attrib),tuple(structure(c) for c in node))
    a={int(i.get('id')):i for i in ET.fromstring(before).iter('item')}
    b={int(i.get('id')):i for i in ET.fromstring(after).iter('item')}
    assert a.keys()==b.keys() and patch(before)==after
    changed=[]
    for identity,old in a.items():
        new=b[identity];fields=changes().get(identity,{})
        av={n.get('key'):n.get('val') for n in old.findall('value')}
        bv={n.get('key'):n.get('val') for n in new.findall('value')}
        assert bv=={**av,**fields},identity
        for n in old.findall('value'):
            if n.get('key') in fields:n.set('val',fields[n.get('key')])
        assert structure(old)==structure(new),identity
        if av!=bv:changed.append(identity)
    assert set(changed)==set(changes())
    v=lambda i:{n.get('key'):n.get('val') for n in b[i].findall('value')}
    assert v(208)['showface']=='1'
    assert v(223)['model_2']=='chr_man_hands' and v(223)['w_model_2']=='chr_woman_hands'
    assert all(v(i)['w_model_2']=='chr_woman_hands' for i in (263,264))
    assert v(206)['texture_1']==v(206)['w_texture_1']=='chr_man_body.jpg'
    assert v(206)['w_model_2']=='chr_woman_legs'
    return {'passed':True,'changed_items':sorted(changed),'all_stats_slots_restrictions_unchanged':True,
            'existing_armor_hands_preserved':True,'pantsu_original_hat_colors_preserved':True}


REMOTE=r'''
import base64,fcntl,hashlib,json,math,os,shutil,sqlite3,struct,subprocess,sys,tarfile,tempfile
from pathlib import Path
from contextlib import closing
p=json.load(sys.stdin);live=Path('/var/www/tio-client/updates');root=Path('/opt/tio-emulator')
catalog=root/'evidence/items_diagnostic.xml'
lock=open('/root/.tio-gameplay-client.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
sha=lambda b:hashlib.sha256(b).hexdigest()
def atomic(raw,target):
 fd,name=tempfile.mkstemp(prefix='.veteran-',dir=target.parent)
 try:
  with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  os.chmod(name,0o644);os.replace(name,target)
 finally:
  if os.path.exists(name):os.unlink(name)
def state():return subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','NRestarts','-p','ActiveState'],text=True)
def protected():
 with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
  db.execute('BEGIN');assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  return {t:sha(repr(sorted(map(repr,db.execute('SELECT * FROM '+t).fetchall()))).encode()) for t in ('accounts','characters','owned_pets','wallets','warehouse_items','clans','clan_members')}
old=base64.b64decode(p['before_manifest']);new=base64.b64decode(p['after_manifest'])
old_server=base64.b64decode(p['server_before']);new_server=base64.b64decode(p['server_after'])
assert (live/'manifest.json').read_bytes()==old and catalog.read_bytes()==old_server
a,b=json.loads(old),json.loads(new);assert a['version']=='2026.10.21.5' and b['version']=='2026.10.21.6'
assert set(a)==set(b) and all(a[k]==b[k] for k in a if k not in ('version','news','files'))
names={'base/models/tio_vet_'+part+'.mdjx' for part in ('head','torso','legs','hands')}|{'base/models/tio_vet_'+part+'.jpg' for part in ('head','body')}
xml='base/shared config/items.xml';ar={r['path']:r for r in a['files']};br={r['path']:r for r in b['files']}
assert not names&ar.keys() and br.keys()==ar.keys()|names
assert len(br)==len(b['files']) and [r['path'] for r in b['files'][:len(a['files'])]]==[r['path'] for r in a['files']]
assert {n for n in ar if ar[n]!=br[n]}=={xml} and set(p['files'])==names|{xml}
before_xml=(live/'blobs'/ar[xml]['sha256']).read_bytes();assert sha(before_xml)==ar[xml]['sha256']
payload={}
for name,value in p['files'].items():
 raw=base64.b64decode(value['raw'],validate=True);row=br[name]
 assert sha(raw)==row['sha256']==value['sha256'] and len(raw)==row['size'] and row['seed'] is False
 if name.endswith('.mdjx'):
  nv,ni,nb,flag=struct.unpack_from('<4I',raw);assert 0<nv<20000 and ni%3==0 and 0<ni<100000 and nb in (1,11,43) and flag==1
  offset=16
  for _ in range(nv):
   count=struct.unpack_from('<I',raw,offset)[0];assert 0<count<=4
   assert all(math.isfinite(v) for v in struct.unpack_from('<8f',raw,offset+4))
   joints=struct.unpack_from('<'+str(count)+'I',raw,offset+40);assert max(joints)<nb
   weights=struct.unpack_from('<'+str(count)+'f',raw,offset+40+count*4)
   assert all(0<=w<=1.001 for w in weights) and abs(sum(weights)-1)<.002
   offset+=40+8*count
  ids=struct.unpack_from('<'+str(ni)+'I',raw,offset);assert max(ids)<nv
  assert sha(raw[offset+ni*4:])==value['bone_tail_sha256']
 elif name==xml:assert validate_catalog(before_xml,raw)['passed']
 else:assert raw[:2]==b'\xff\xd8' and raw[-2:]==b'\xff\xd9'
 payload[name]=raw
assert validate_catalog(old_server,new_server)['passed']
service=state();assert 'ActiveState=active' in service;prior=protected()
cfg=Path('/etc/tio-server/server.toml').read_bytes()
if p['mode']=='validate':
 print(json.dumps(dict(passed=True,read_only=True,version=b['version'],new_paths=sorted(names),service=service)));sys.exit(0)
assert p['mode']=='publish'
backup=Path(tempfile.mkdtemp(prefix='tio-before-veteran-',dir='/root'));backup.chmod(0o700)
(backup/'manifest.json').write_bytes(old);(backup/'public-items.xml').write_bytes(before_xml);(backup/'server-items.xml').write_bytes(old_server)
shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml');shutil.copy2('/etc/systemd/system/tio-server.service',backup/'tio-server.service')
with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as tar:
 for directory,pattern in (('tio','*.py'),('server','*.py'),('tools','*.py'),('config','*.json'),('evidence','*.xml')):
  for f in sorted((root/directory).rglob(pattern)):tar.add(f,arcname=f.relative_to(root).as_posix())
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert (live/'manifest.json').read_bytes()==old and catalog.read_bytes()==old_server and protected()==prior and state()==service
try:
 for name,raw in payload.items():
  target=live/'blobs'/br[name]['sha256']
  if target.exists():assert target.read_bytes()==raw
  else:atomic(raw,target)
 atomic(new,live/'manifest.json')
 atomic(new_server,catalog)
 assert (live/'manifest.json').read_bytes()==new and catalog.read_bytes()==new_server
 assert state()==service and Path('/etc/tio-server/server.toml').read_bytes()==cfg
except Exception:
 if catalog.read_bytes()==new_server:atomic(old_server,catalog)
 if (live/'manifest.json').read_bytes()==new:atomic(old,live/'manifest.json')
 raise
after=protected()
result=dict(passed=True,version=b['version'],backup=str(backup),new_paths=sorted(names),changed_paths=[xml],
 manifest_sha256=sha(new),server_catalog_sha256=sha(new_server),service=service,service_unchanged=True,
 database_written=False,local_player_data_uploaded=False,original_models_textures_preserved=True,
 protected_before=prior,protected_after=after,protected_unchanged=after==prior)
(backup/'publication.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
'''
REMOTE=REMOTE.replace("p=json.load(sys.stdin);live=",'\n'.join(inspect.getsource(f) for f in (changes,patch,validate_catalog))+"\np=json.load(sys.stdin);live=")


def prepare():
    old=(OUT/'manifest-before.json').read_bytes();m=json.loads(old);assert m['version']=='2026.10.21.5'
    rows={r['path']:r for r in m['files']};raw=(OUT/'public-items-before.xml').read_bytes()
    assert sha(raw)==rows[XML]['sha256'];candidate=patch(raw);checks=validate_catalog(raw,candidate)
    (OUT/'public-items-after.xml').write_bytes(candidate)
    server=(OUT/'server-items-before.xml').read_bytes();new_server=patch(server);validate_catalog(server,new_server)
    (OUT/'server-items-after.xml').write_bytes(new_server)
    model=json.loads((ASSET/'model.json').read_text());rig=json.loads((ASSET/'rig-validation.json').read_text())
    assert model['passed'] and model['total_triangles']==13562 and rig['passed'] and rig['rig_bones']==52
    files={};proof=[]
    for name,relative in MAPPING.items():
        assert name not in rows
        source=ASSET/relative;data=source.read_bytes();value={'raw':base64.b64encode(data).decode(),'sha256':sha(data)}
        if name.endswith('.mdjx'):
            mesh=read(source);part=next(p for p in model['parts'] if p['file']==relative)
            original=read(ROOT/'reports/fighter-model-20261020/source/base/models'/part['source'])
            assert encode(mesh)==data and sha(data)==part['sha256'] and mesh.tail==original.tail and mesh.bones==original.bones
            assert all(len(v.joints)<=4 and abs(sum(v.weights)-1)<.002 for v in mesh.vertices)
            assert all(abs(math.sqrt(sum(c*c for c in v.normal))-1)<.003 for v in mesh.vertices)
            value['bone_tail_sha256']=sha(mesh.tail)
            proof.append({'name':name,'triangles':len(mesh.indices)//3,'vertices':len(mesh.vertices),'original_bind_data_preserved':True})
        else:
            from PIL import Image
            image=Image.open(source);assert image.mode=='RGB' and image.size==((1024,1024) if 'head' in name else (2048,1024))
        m['files'].append({'path':name,'size':len(data),'sha256':sha(data),'seed':False});files[name]=value
    files[XML]={'raw':base64.b64encode(candidate).decode(),'sha256':sha(candidate)}
    rows[XML].update(size=len(candidate),sha256=sha(candidate),seed=False)
    m.update(version=VERSION,news=NEWS)
    new=(json.dumps(m,ensure_ascii=False,indent=2)+'\n').encode();(OUT/'manifest.json').write_bytes(new)
    (OUT/'validation.json').write_text(json.dumps({'passed':True,'rig_bones':52,'catalog':checks,'parts':proof,'native_default_triangles':13562,
       'new_resources':sorted(MAPPING),'base_models_rebound_only':True,'animation_files_modified':False,'armored_hands_original_resources_preserved':True},indent=2))
    return {'before_manifest':base64.b64encode(old).decode(),'after_manifest':base64.b64encode(new).decode(),
            'server_before':base64.b64encode(server).decode(),'server_after':base64.b64encode(new_server).decode(),'files':files}


def verify():
    raw=urllib.request.urlopen(ORIGIN+'manifest.json',timeout=30).read();assert raw==(OUT/'manifest.json').read_bytes()
    rows={r['path']:r for r in json.loads(raw)['files']}
    for name,source in {**MAPPING,XML:None}.items():
        data=urllib.request.urlopen(ORIGIN+'blobs/'+rows[name]['sha256'],timeout=30).read()
        assert data==((ASSET/source).read_bytes() if source else (OUT/'public-items-after.xml').read_bytes())
    hosted=remote("import sys,json,hashlib;from pathlib import Path;p=json.load(sys.stdin);print(json.dumps(dict(sha256=hashlib.sha256(Path('/opt/tio-emulator/evidence/items_diagnostic.xml').read_bytes()).hexdigest())))",{})
    assert hosted['sha256']==sha((OUT/'server-items-after.xml').read_bytes())
    state=remote(STATE,{});publication=json.loads((OUT/'publication.json').read_text());assert state['integrity']=='ok' and state['service']==publication['service']
    result={'passed':True,'version':VERSION,'trusted_https':True,'verified_resources':7,'server_catalog_matches':True,'service':state['service'],
            'accounts':state['accounts'],'clans':state['clans'],'integrity':state['integrity']}
    (OUT/'https-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','publish','verify'));mode=p.parse_args().mode
    if mode=='verify':verify()
    else:
        data=prepare();data['mode']=mode
        if mode=='publish':assert not (OUT/'publication.json').exists()
        r=remote(REMOTE,data);(OUT/('publication.json' if mode=='publish' else 'remote-validation.json')).write_text(json.dumps(r,indent=2))
        print(json.dumps({k:v for k,v in r.items() if not k.startswith('protected_')}))
