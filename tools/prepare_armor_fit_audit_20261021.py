"""Inventory all published armor/class bindings and fetch their exact resources."""
import concurrent.futures,hashlib,json,sys,urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_stage4_economy import remote
from tools.publish_ability_icons_20261020 import STATE
OUT=ROOT/'reports/armor-fit-20261021';OUT.mkdir(parents=True,exist_ok=True)
sha=lambda b:hashlib.sha256(b).hexdigest();origin='https://185.184.42.88/updates/'
raw=urllib.request.urlopen(origin+'manifest.json',timeout=30).read();baseline=OUT/'manifest-before.json'
if baseline.exists():assert baseline.read_bytes()==raw,'Published release changed'
else:baseline.write_bytes(raw)
m=json.loads(raw);rows={r['path']:r for r in m['files']}
def fetch(name):
 row=rows[name];target=OUT/'source'/name
 if target.exists():assert sha(target.read_bytes())==row['sha256'];return name
 raw=urllib.request.urlopen(origin+'blobs/'+row['sha256'],timeout=45).read();assert sha(raw)==row['sha256'] and len(raw)==row['size']
 target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);return name
xml='base/shared config/items.xml';fetch(xml);items=[];needed=set();cases=[]
BASES={
 1:[('chr_man_head','chr_man_head.jpg','head'),('chr_man_body','chr_man_body.jpg','chest'),('chr_man_hands','chr_man_body.jpg','hands'),('chr_man_legs','chr_man_body.jpg','legs')],
 2:[('chr_woman_head','chr_woman_head.jpg','head'),('chr_woman_body','chr_woman_body.jpg','chest'),('chr_woman_hands','chr_woman_body.jpg','hands'),('chr_woman_legs','chr_woman_body.jpg','legs')],
 3:[('dog_doberman','dog_doberman.jpg','dog')],4:[('dog_huski','dog_huski.jpg','dog')],5:[('dog_alsatian','dog_alsatian.jpg','dog')],
 6:[('freakminer_body','miner.jpg','chest'),('freakminer_legs','miner.jpg','legs')],
}
for resource,parts in BASES.items():
 for model,texture,_ in parts:needed.update(('base/models/'+model+'.mdjx','base/models/'+texture))
for item in ET.parse(OUT/'source'/xml).getroot().iter('item'):
 v={n.get('key'):n.get('val') for n in item.findall('value')};identity=int(item.get('id'));part=v.get('bodypart')
 if identity>=65400 or v.get('itype')!='armor' or part not in ('head','chest','legs','complexarmor'):continue
 if part=='complexarmor' and identity not in (254,256,263,264):continue
 resources=[3,4,5] if v.get('dogs_only')=='1' else [6] if v.get('freaks_only')=='1' else [2] if v.get('woman_only')=='1' else [1,2]
 covers=['head','chest','legs'] if identity in (254,256) else ['chest','legs'] if identity in (263,264) else [part]
 entry=dict(id=identity,name=item.get('name'),part=part,resources=resources,covers=covers,level=int(v.get('level_required','0')),values=v);items.append(entry)
 for resource in resources:
  prefix='w_' if resource==2 and v.get('w_model_1') else '';bindings=[]
  for i in range(1,5):
   model=v.get(prefix+'model_'+str(i));texture=v.get(prefix+'texture_'+str(i))
   if model and texture:
    needed.update(('base/models/'+model+'.mdjx','base/models/'+texture));bindings.append(dict(model=model,texture=texture))
  assert bindings,(identity,resource)
  cases.append(dict(id=identity,resource=resource,name=item.get('name'),part=part,covers=covers,bindings=bindings))
for n in rows:
 if n.startswith('base/models/') and n.endswith('_skeleton.mdjx') and any(k in n for k in ('man_','woman_','dog_','freakminer_')):needed.add(n)
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(fetch,sorted(needed)))
if not (OUT/'hosted-before.json').exists():
 state=remote(STATE,{});(OUT/'hosted-before.json').write_text(json.dumps(state,indent=2))
male={r['path']:r['sha256'] for r in m['files'] if r['path'].startswith('base/models/chr_man_')}
veteran=ROOT/'assets/fighter-model-v1';map_={'head':'head','body':'torso','hands':'hands','legs':'legs'}
status={part:male.get('base/models/chr_man_'+part+'.mdjx')==sha((veteran/'native'/('tio_vet_'+target+'.mdjx')).read_bytes()) for part,target in map_.items()}
report=dict(version=m['version'],armor_items=items,cases=cases,base_parts={str(k):v for k,v in BASES.items()},files=sorted(needed),male_veteran_published=status)
(OUT/'catalog.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(version=m['version'],armor_items=len(items),class_item_cases=len(cases),resources=len(needed),male_veteran_published=status,
 per_class={r:len([c for c in cases if c['resource']==r]) for r in BASES},skeletons=[n for n in needed if 'skeleton' in n]),indent=2))
