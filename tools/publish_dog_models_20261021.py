"""Publish only the three verified canine meshes and corresponding textures."""
import argparse,ast,base64,hashlib,json,math,struct,sys,urllib.request
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_stage4_economy import remote
from tools.mdjx_mesh import read,encode
from tools.dog_models_gui_20261021 import qa
from tools.publish_ability_icons_20261020 import STATE
OUT=qa.OUT;ASSET=qa.ASSET;VERSION='2026.10.21.2'
NEWS='Новые модели собак: доберман, хаски и немецкая овчарка. Новые текстуры и совместимые скелеты. Обновите игру через лаунчер.'
sha=lambda b:hashlib.sha256(b).hexdigest()
# Reuse the audited art-only release transaction without importing female QA globals.
tree=ast.parse((ROOT/'tools/publish_female_fighter_20261021.py').read_text(encoding='utf-8'))
REMOTE=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REMOTE' for t in n.targets)))
old="expected={'base/models/chr_woman_'+part+ext for part,ext in [('head','.mdjx'),('body','.mdjx'),('hands','.mdjx'),('legs','.mdjx'),('head','.jpg'),('body','.jpg')]}"
assert old in REMOTE
REMOTE=REMOTE.replace(old,"expected={'base/models/dog_'+breed+ext for breed in ('doberman','huski','alsatian') for ext in ('.mdjx','.jpg')}")
REMOTE=REMOTE.replace("a['version']=='2026.10.20.5' and b['version']=='2026.10.21.1'","a['version']=='2026.10.21.1' and b['version']=='2026.10.21.2'")
REMOTE=REMOTE.replace('nb in (1,10,43)','nb==26').replace('tio-before-female-fighter-','tio-before-dog-models-').replace('.female-model-','.dog-models-')

def validate():
 old=(OUT/'manifest-before.json').read_bytes();m=json.loads(old);assert m['version']=='2026.10.21.1'
 rows={r['path']:r for r in m['files']};files={};proof=[]
 for breed in ('doberman','huski','alsatian'):
  folder=ASSET/breed;model=json.loads((folder/'model.json').read_text(encoding='utf-8'));rig=json.loads((folder/'rig-validation.json').read_text())
  assert model['passed'] and model['rig_bones']==31 and model['deform_bones']==26 and not model['animation_source_files_modified']
  assert rig['passed'] and rig['sampled_poses']>=42 and rig['maximum_native_skinning_error_m']<.0003
  raw=(folder/'native'/f'dog_{breed}.mdjx').read_bytes();mesh=read(folder/'native'/f'dog_{breed}.mdjx');source=OUT/'source/base/models'/f'dog_{breed}.mdjx';base=read(source)
  assert sha(source.read_bytes())==model['source_sha256']==rows['base/models/'+source.name]['sha256']
  assert encode(mesh)==raw and mesh.tail==base.tail and mesh.bones==base.bones and len(mesh.bones)==26
  assert sha(raw)==model['native']['sha256'] and sha(mesh.tail)==model['native']['bone_tail_sha256']
  assert len(mesh.vertices)==model['native']['vertices'] and len(mesh.indices)//3==model['native']['triangles']
  assert all(len(v.joints)<=4 and abs(sum(v.weights)-1)<.002 and abs(math.sqrt(sum(c*c for c in v.normal))-1)<.003 for v in mesh.vertices)
  low=read(folder/'lod1'/source.name);assert low.tail==mesh.tail and len(low.indices)//3==model['lod1']['triangles']
  image=Image.open(folder/'textures'/f'dog_{breed}.jpg');assert image.size==(2048,2048) and image.mode=='RGB'
  assert sha((folder/'textures'/f'dog_{breed}.jpg').read_bytes())==model['texture_sha256']
  raw=(folder/(breed+'.glb')).read_bytes();magic,version,size=struct.unpack_from('<4sII',raw);assert magic==b'glTF' and version==2 and size==len(raw)
  length,kind=struct.unpack_from('<II',raw,12);assert kind==0x4e4f534a;g=json.loads(raw[20:20+length])
  assert len(g['meshes'])==1 and len(g['skins'])==1 and len(g['skins'][0]['joints'])==31
  assert {a['name'] for a in g['animations']}==set(model['animations']) and len(g['animations'])==6
  assert all({'POSITION','NORMAL','TEXCOORD_0','JOINTS_0','WEIGHTS_0'}<=set(p['attributes']) for mesh_ in g['meshes'] for p in mesh_['primitives'])
  for name,value in model['animations'].items():assert sha((OUT/'source/base/models/anim'/(name+'.adjx')).read_bytes())==value['source_sha256']==rows['base/models/anim/'+name+'.adjx']['sha256']
  proof.append(dict(breed=breed,rig_bones=31,deform_bones=26,triangles=model['native']['triangles'],vertices=model['native']['vertices'],sampled_poses=rig['sampled_poses'],native_skinning_error_m=rig['maximum_native_skinning_error_m'],texture=[2048,2048],glb_valid=True))
 for name,relative in qa.MAPPING.items():
  raw=(ASSET/relative).read_bytes();value=dict(raw=base64.b64encode(raw).decode(),sha256=sha(raw))
  if name.endswith('.mdjx'):value['bone_tail_sha256']=sha(read(ASSET/relative).tail)
  files[name]=value;rows[name].update(sha256=sha(raw),size=len(raw),seed=False)
 visual=json.loads((OUT/'gui-visual-candidate.json').read_text());assert visual['passed'] and visual['real_game_client'] and set(visual['breeds'])=={'doberman','huski','alsatian'}
 m.update(version=VERSION,news=NEWS);new=(json.dumps(m,ensure_ascii=False,indent=2)+'\n').encode();(OUT/'manifest.json').write_bytes(new)
 report=dict(passed=True,version=VERSION,breeds=proof,changed_paths=sorted(files),original_bone_bind_data_preserved=True,animation_files_modified=False,xml_or_gameplay_changes=False)
 (OUT/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
 return dict(mode='validate',before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),files=files,news=NEWS)

def verify():
 new=(OUT/'manifest.json').read_bytes();origin='https://185.184.42.88/updates/'
 assert urllib.request.urlopen(origin+'manifest.json',timeout=30).read()==new;rows={r['path']:r for r in json.loads(new)['files']}
 for name,relative in qa.MAPPING.items():assert urllib.request.urlopen(origin+'blobs/'+rows[name]['sha256'],timeout=30).read()==(ASSET/relative).read_bytes()
 state=remote(STATE,{});before=json.loads((OUT/'publication.json').read_text());assert state['integrity']=='ok' and state['service']==before['service']
 result=dict(passed=True,trusted_https=True,version=VERSION,verified_resources=6,manifest_sha256=sha(new),service=state['service'],accounts=state['accounts'],clans=state['clans'],integrity=state['integrity'])
 (OUT/'https-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','publish','verify'));mode=p.parse_args().mode
 if mode=='verify':verify()
 else:
  payload=validate();payload['mode']=mode
  if mode=='publish':assert not (OUT/'publication.json').exists()
  result=remote(REMOTE,payload);(OUT/('publication.json' if mode=='publish' else 'remote-validation.json')).write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if not k.startswith('protected_')}))
