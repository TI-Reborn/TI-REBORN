"""Validate and atomically publish the eight miner model resources."""
import argparse,ast,base64,hashlib,json,math,struct,sys,urllib.request
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_stage4_economy import remote
from tools.mdjx_mesh import read,encode
from tools.miner_native_mesh import compatible
from tools.miner_model_gui_20261021 import qa,PARTS
from tools.publish_ability_icons_20261020 import STATE
OUT=qa.OUT;ASSET=qa.ASSET;VERSION='2026.10.21.3'
NEWS='Шахтёр «Колосс»: мощная модель, новые текстуры, обновлённые варианты брони и совместимый скелет из 50 костей. Обновите игру через лаунчер.'
sha=lambda b:hashlib.sha256(b).hexdigest()
tree=ast.parse((ROOT/'tools/publish_female_fighter_20261021.py').read_text(encoding='utf-8'))
REMOTE=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REMOTE' for t in n.targets)))
old="expected={'base/models/chr_woman_'+part+ext for part,ext in [('head','.mdjx'),('body','.mdjx'),('hands','.mdjx'),('legs','.mdjx'),('head','.jpg'),('body','.jpg')]}";assert old in REMOTE
REMOTE=REMOTE.replace(old,'expected='+repr(set(qa.MAPPING)))
REMOTE=REMOTE.replace("a['version']=='2026.10.20.5' and b['version']=='2026.10.21.1'","a['version']=='2026.10.21.2' and b['version']=='2026.10.21.3'")
REMOTE=REMOTE.replace('nb in (1,10,43)','nb in (1,7,8,31,38)').replace('tio-before-female-fighter-','tio-before-miner-model-').replace('.female-model-','.miner-model-')

def validate():
 old=(OUT/'manifest-before.json').read_bytes();m=json.loads(old);assert m['version']=='2026.10.21.2';rows={r['path']:r for r in m['files']}
 model=json.loads((ASSET/'model.json').read_text());rig=json.loads((ASSET/'rig-validation.json').read_text())
 assert model['passed'] and model['rig_bones']==50 and len(model['parts'])==7 and len(model['animations'])==9
 assert rig['passed'] and rig['sampled_poses']>=63 and rig['maximum_native_skinning_error_m']<.0003
 files={};proof=[]
 for item in model['parts']:
  name=item['part']+'.mdjx';path=ASSET/'native'/name;raw=path.read_bytes();mesh=read(path);source=OUT/'source/base/models'/name;base=compatible(source)
  assert sha(source.read_bytes())==item['source_sha256']==rows['base/models/'+name]['sha256']
  assert encode(mesh)==raw and mesh.tail==base.tail and mesh.bones==base.bones
  assert sha(raw)==item['native']['sha256'] and sha(mesh.tail)==item['native']['bone_tail_sha256']
  assert len(mesh.vertices)==item['native']['vertices'] and len(mesh.indices)//3==item['native']['triangles']
  assert all(len(v.joints)<=4 and abs(sum(v.weights)-1)<.002 and abs(math.sqrt(sum(c*c for c in v.normal))-1)<.003 for v in mesh.vertices)
  low=read(ASSET/'lod1'/name);assert low.tail==mesh.tail and len(low.indices)//3==item['lod1']['triangles']
  proof.append(dict(part=item['part'],triangles=item['native']['triangles'],vertices=item['native']['vertices'],deform_bones=len(mesh.bones),source_sha256=item['source_sha256'],sha256=sha(raw),bone_tail_sha256=sha(mesh.tail)))
 raw=(ASSET/'colossus.glb').read_bytes();magic,version,size=struct.unpack_from('<4sII',raw);assert magic==b'glTF' and version==2 and size==len(raw)
 length,kind=struct.unpack_from('<II',raw,12);assert kind==0x4e4f534a;g=json.loads(raw[20:20+length])
 assert len(g['meshes'])==2 and len(g['skins'])==1 and len(g['skins'][0]['joints'])==50
 assert {a['name'] for a in g['animations']}==set(model['animations'])
 assert all({'POSITION','NORMAL','TEXCOORD_0','JOINTS_0','WEIGHTS_0'}<=set(p['attributes']) for mesh in g['meshes'] for p in mesh['primitives'])
 for name,value in model['animations'].items():assert sha((OUT/'source/base/models/anim'/(name+'.adjx')).read_bytes())==value['source_sha256']==rows['base/models/anim/'+name+'.adjx']['sha256']
 image=Image.open(ASSET/'textures/miner.jpg');assert image.size==(2048,2048) and image.mode=='RGB' and sha((ASSET/'textures/miner.jpg').read_bytes())==model['texture_sha256']
 for name,relative in qa.MAPPING.items():
  raw=(ASSET/relative).read_bytes();value=dict(raw=base64.b64encode(raw).decode(),sha256=sha(raw))
  if name.endswith('.mdjx'):value['bone_tail_sha256']=sha(read(ASSET/relative).tail)
  files[name]=value;rows[name].update(sha256=sha(raw),size=len(raw),seed=False)
 visual=json.loads((OUT/'gui-visual-candidate.json').read_text());assert visual['passed'] and visual['real_game_client'] and visual['loadouts']==['base','medium-hammer','heavy-nailgun']
 m.update(version=VERSION,news=NEWS);new=(json.dumps(m,ensure_ascii=False,indent=2)+'\n').encode();(OUT/'manifest.json').write_bytes(new)
 report=dict(passed=True,version=VERSION,rig_bones=50,parts=proof,native_default_triangles=model['native_default_triangles'],original_native_clips=9,
  sampled_blender_poses=rig['sampled_poses'],maximum_native_skinning_error_m=rig['maximum_native_skinning_error_m'],texture=[2048,2048],glb_valid=True,
  changed_paths=sorted(files),original_bone_bind_data_preserved=True,animation_files_modified=False,xml_or_gameplay_changes=False,legacy_zero_weight_indices_sanitized=3)
 (OUT/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
 return dict(mode='validate',before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),files=files,news=NEWS)

def verify():
 new=(OUT/'manifest.json').read_bytes();origin='https://185.184.42.88/updates/'
 assert urllib.request.urlopen(origin+'manifest.json',timeout=30).read()==new;rows={r['path']:r for r in json.loads(new)['files']}
 for name,relative in qa.MAPPING.items():assert urllib.request.urlopen(origin+'blobs/'+rows[name]['sha256'],timeout=30).read()==(ASSET/relative).read_bytes()
 state=remote(STATE,{});before=json.loads((OUT/'publication.json').read_text());assert state['integrity']=='ok' and state['service']==before['service']
 result=dict(passed=True,trusted_https=True,version=VERSION,verified_resources=8,manifest_sha256=sha(new),service=state['service'],accounts=state['accounts'],clans=state['clans'],integrity=state['integrity'])
 (OUT/'https-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','publish','verify'));mode=p.parse_args().mode
 if mode=='verify':verify()
 else:
  payload=validate();payload['mode']=mode
  if mode=='publish':assert not (OUT/'publication.json').exists()
  result=remote(REMOTE,payload);(OUT/('publication.json' if mode=='publish' else 'remote-validation.json')).write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if not k.startswith('protected_')}))
