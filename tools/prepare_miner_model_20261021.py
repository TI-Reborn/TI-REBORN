"""Fetch actual published miner assets and preserve the release/state baseline."""
import hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.mdjx_mesh import read
from tools.miner_native_mesh import compatible
from tools.dog_native_animation import skeleton,animation
from tools.deploy_stage4_economy import remote
from tools.publish_ability_icons_20261020 import STATE
OUT=ROOT/'reports/miner-model-20261021';ASSET=ROOT/'assets/miner-colossus-v1';OUT.mkdir(parents=True,exist_ok=True);ASSET.mkdir(parents=True,exist_ok=True)
origin='https://185.184.42.88/updates/';raw=urllib.request.urlopen(origin+'manifest.json',timeout=30).read();target=OUT/'manifest-before.json'
if target.exists():assert target.read_bytes()==raw
else:target.write_bytes(raw)
m=json.loads(raw);rows={r['path']:r for r in m['files']}
names=['base/models/'+n for n in ('freakminer_body.mdjx','freakminer_legs.mdjx','freakminer_skeleton.mdjx','freakminer_medium_body.mdjx','freakminer_medium_legs.mdjx','freakminer_heavy_body.mdjx','freakminer_heavy_legs.mdjx','freakminer_heavy_helmet.mdjx','miner.jpg','miner_mask.png','miner_new_body.mdjx','miner_new_legs.mdjx','miner_new.jpg','freakminer_armor_wolf_helmet.mdjx','freakminer_armor_ssh40.mdjx','freakminer_armor_budenovka.mdjx','freakminer_armor_beret.mdjx')]
names+=sorted(n for n in rows if n.startswith('base/models/anim/freakminer_') and n.endswith('.adjx'))
for name in names:
 row=rows[name];raw=urllib.request.urlopen(origin+'blobs/'+row['sha256'],timeout=40).read();assert hashlib.sha256(raw).hexdigest()==row['sha256'] and len(raw)==row['size']
 target=OUT/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
summary=[]
for name in names:
 if name.endswith('.mdjx'):
  if 'skeleton' in name:
   bones=skeleton(OUT/'source'/name);summary.append(dict(name=name,bones=len(bones),bone_names=[b['name'] for b in bones]));continue
  mesh=compatible(OUT/'source'/name)
  summary.append(dict(name=name,vertices=len(mesh.vertices),triangles=len(mesh.indices)//3,bones=len(mesh.bones),bone_names=[b['name'] for b in mesh.bones],
   bounds=[(min(v.position[i] for v in mesh.vertices),max(v.position[i] for v in mesh.vertices)) for i in range(3)],uv_bounds=[(min(v.uv[i] for v in mesh.vertices),max(v.uv[i] for v in mesh.vertices)) for i in range(2)]))
clips=[]
for name in names:
 if name.endswith('.adjx'):
  raw=(OUT/'source'/name).read_bytes()
  try:a=animation(OUT/'source'/name);clips.append(dict(name=name,bones=len(a['names']),frames=a['frames'],version=1))
  except AssertionError:clips.append(dict(name=name,version=int.from_bytes(raw[5:9],'little'),parser_supported=False))
(OUT/'source-summary.json').write_text(json.dumps(dict(meshes=summary,animations=clips),indent=2))
state=remote(STATE,{});(OUT/'hosted-before.json').write_text(json.dumps(state,indent=2))
print(json.dumps(dict(version=m['version'],meshes=[{k:v for k,v in s.items() if k!='bone_names'} for s in summary],clips=clips,service=state['service'],accounts=state['accounts'],clans=state['clans']),indent=2))
