"""Fetch verified published canine source assets and actual hosted state."""
import hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.mdjx_mesh import read
from tools.deploy_stage4_economy import remote
from tools.publish_ability_icons_20261020 import STATE
OUT=ROOT/'reports/dog-models-20261021';ASSET=ROOT/'assets/dog-mercenaries-v1'
OUT.mkdir(parents=True,exist_ok=True);ASSET.mkdir(parents=True,exist_ok=True)
origin='https://185.184.42.88/updates/'
raw=urllib.request.urlopen(origin+'manifest.json',timeout=30).read()
target=OUT/'manifest-before.json'
if target.exists():assert target.read_bytes()==raw,'Preserve first release baseline'
else:target.write_bytes(raw)
m=json.loads(raw);rows={r['path']:r for r in m['files']}
names=['base/models/'+n for n in ('dog_doberman.mdjx','dog_doberman.jpg','dog_huski.mdjx','dog_huski.jpg','dog_alsatian.mdjx','dog_alsatian.jpg','dog_mask.png','dog_skeleton.mdjx','dog_armor_v01.mdjx','dog_items_v01.jpg','dog_solid_armor.mdjx','dog_solid_armor.jpg','dog_az_armor.mdjx')]
names+=sorted(n for n in rows if n.startswith('base/models/anim/dog_') and n.endswith('.adjx'))
for name in names:
 row=rows[name];raw=urllib.request.urlopen(origin+'blobs/'+row['sha256'],timeout=40).read();assert hashlib.sha256(raw).hexdigest()==row['sha256'] and len(raw)==row['size']
 target=OUT/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
summary=[]
for breed in ('doberman','huski','alsatian'):
 name='dog_'+breed;mesh=read(OUT/'source/base/models'/(name+'.mdjx'))
 summary.append(dict(breed=breed,vertices=len(mesh.vertices),triangles=len(mesh.indices)//3,bones=mesh.bones,
  bounds=[(min(v.position[i] for v in mesh.vertices),max(v.position[i] for v in mesh.vertices)) for i in range(3)],
  uv_bounds=[(min(v.uv[i] for v in mesh.vertices),max(v.uv[i] for v in mesh.vertices)) for i in range(2)]))
(OUT/'source-summary.json').write_text(json.dumps(summary,indent=2))
state=remote(STATE,{});(OUT/'hosted-before.json').write_text(json.dumps(state,indent=2))
print(json.dumps(dict(version=m['version'],files=names,breeds=[{k:v for k,v in s.items() if k!='bones'}|dict(bones=len(s['bones'])) for s in summary],service=state['service'],accounts=state['accounts'],clans=state['clans']),indent=2))
