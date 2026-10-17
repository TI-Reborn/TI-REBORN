"""Published source inventory and isolated Reservation material replacements."""
from pathlib import Path
import copy,hashlib,io,json,re,shlex,struct,subprocess,urllib.request,zlib,xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/reservation-textures';ASSETS=ROOT/'assets/reservation-textures-v2'
BASE=Path(r'C:/Program Files (x86)/TIOnline/base')
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@185.184.42.88']
SERVER_FILES=('tio/map_generation.py','config/reservation_visuals.json')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def remote(code,data=None):
 p=subprocess.run(SSH+['python3 -c '+shlex.quote(code)],input=json.dumps(data),capture_output=True,text=True,encoding='utf-8')
 if p.returncode:raise RuntimeError(p.stderr)
 return json.loads(p.stdout)
def fetch(name):
 records={r['path']:r for r in json.loads((OUT/'previous-client-manifest.json').read_bytes())['files']};record=records[name]
 path=OUT/'source'/name
 if not path.exists():
  with urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+record['sha256'],timeout=30) as response:raw=response.read()
  assert sha(raw)==record['sha256'] and len(raw)==record['size'],name
  path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
 assert sha(path.read_bytes())==record['sha256'] and path.stat().st_size==record['size']
 return path
def inspect():
 OUT.mkdir(exist_ok=True);ASSETS.mkdir(exist_ok=True)
 code="""import pathlib,sqlite3,hashlib,json,sys,subprocess
r=pathlib.Path('/opt/tio-emulator');d=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
print(json.dumps(dict(service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),integrity=d.execute('PRAGMA integrity_check').fetchone()[0],accounts=d.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],checkpoints=d.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0],pending=d.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0],files={n:(dict(sha=hashlib.sha256((r/n).read_bytes()).hexdigest(),source=(r/n).read_text()) if (r/n).exists() else None) for n in json.load(sys.stdin)},client=pathlib.Path('/var/www/tio-client/updates/manifest.json').read_text())))"""
 data=remote(code,(*SERVER_FILES,'config/battle_map_profiles.json','config/arena_fragments.json'));files=data.pop('files');client=data.pop('client')
 (OUT/'inspection.json').write_text(json.dumps(data,indent=2));(OUT/'previous-client-manifest.json').write_text(client,encoding='utf-8')
 before={}
 for n,record in files.items():
  before[n]=record['sha'] if record else None
  if record:
   assert sha((ROOT/n).read_bytes())==record['sha'],n
   p=OUT/'remote-before'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(record['source'],encoding='utf-8',newline='')
 (OUT/'before-hashes.json').write_text(json.dumps(before,indent=2));print(json.dumps(data))
def inputs():
 from tools.build_visual_asset_catalog import decode
 p=json.loads((OUT/'remote-before/config/battle_map_profiles.json').read_text())['profiles']['reservation']
 fragments=json.loads((OUT/'remote-before/config/arena_fragments.json').read_text());records=json.loads((OUT/'previous-client-manifest.json').read_bytes())['files']
 setting={}
 for r in records:
  if r['path'].startswith('base/setting/'):setting.setdefault(Path(r['path']).name.lower(),[]).append(r)
 models={};paths=[];names=sorted({n for pool in p['pools'].values() for n in pool})
 for n in names:paths.append('base/maps/'+n)
 for m in sorted({m for n in names for m in fragments[n]['models']}):
  digest=next(fragments[n]['door_models_sha256'][m] for n in names if m in fragments[n].get('door_models_sha256',{}))
  candidates=[r for r in setting[m.lower()] if r['sha256']==digest];assert candidates,m
  models[m.lower()]=candidates[0]['path'];paths.append(candidates[0]['path'])
 ground=ET.parse(fetch('base/ground.xml')).getroot();grounds={}
 for identity in ('0','1'):
  grounds[identity]=[]
  for b in ground.find(f"ground[@id='{identity}']"):
   n='base/setting/'+b.get('filename').replace('\\','/').lstrip('/');assert n in {r['path'] for r in records},n
   grounds[identity].append(dict(path=n,layer=b.get('layer')));models.setdefault(Path(n).name.lower(),n);paths.append(n)
 with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(fetch,sorted(set(paths))))
 textures={}
 for m,path in models.items():
  raw=fetch(path).read_bytes().lower()
  for name in sorted(setting):
   if Path(name).suffix not in ('.png','.jpg','.tga','.dds','.bmp'):continue
   if name.encode() not in raw:continue
   candidates=setting[name]
   assert len({r['sha256'] for r in candidates})==1,(name,'conflicting native basename')
   textures[name]=candidates[0]['path']
 with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(fetch,textures.values()))
 inventory=dict(fragments=names,models=models,grounds=grounds,textures=textures)
 (OUT/'inventory.json').write_text(json.dumps(inventory,indent=2));(ASSETS/'inputs').mkdir(exist_ok=True)
 tasks=[]
 for name,path in textures.items():
  im,_=decode(fetch(path).read_bytes());im.save(ASSETS/'inputs'/(Path(name).stem+'.png'))
  box=im.getchannel('A').getbbox();pixels=im.convert('RGB');ext=pixels.getextrema()
  shadow=not box or all(high<=12 for low,high in ext)
  tasks.append(dict(id=name,path=path,width=im.width,height=im.height,shadow=shadow,transparent=im.getchannel('A').getextrema()[0]<255,input=str(ASSETS/'inputs'/(Path(name).stem+'.png'))))
 (ASSETS/'tasks.json').write_text(json.dumps(tasks,indent=2));print(json.dumps(dict(fragments=len(names),models=len(models),textures=len(textures),shadows=sum(t['shadow'] for t in tasks),source_version=json.loads((OUT/'previous-client-manifest.json').read_bytes())['version'])))
def names():
 inventory=json.loads((OUT/'inventory.json').read_text());published=json.loads((OUT/'previous-client-manifest.json').read_bytes())['files']
 used={Path(r['path']).name.lower() for r in published};result={}
 for n in sorted(set(inventory['models'])|set(inventory['textures'])|{Path(n).name.lower() for n in inventory['fragments']}):
  stem,suffix=Path(n).stem,Path(n).suffix;candidate='rv'+stem[2:]+suffix
  for attempt in range(256):
   if candidate.lower() not in used:break
   digest=hashlib.sha256((n+str(attempt)).encode()).hexdigest();candidate='r'+digest[:min(3,len(stem)-1)]+stem[4:]+suffix
  else:raise ValueError('Cannot allocate isolated basename')
  assert len(candidate)==len(n),(n,candidate)
  used.add(candidate.lower());result[n]=candidate
 (OUT/'names.json').write_text(json.dumps(result,indent=2));return result
def renamed(raw,mapping):
 # Every native filename keeps its byte length, including ShortString fields.
 for old,new in sorted(mapping.items(),key=lambda p:-len(p[0])):
  raw=re.sub(rb'(?<![a-zA-Z0-9_])'+re.escape(old.encode())+rb'(?![a-zA-Z0-9_])',new.encode(),raw,flags=re.I)
 return raw
def resources():
 inventory=json.loads((OUT/'inventory.json').read_text());mapping=names();client=OUT/'client/base';target=client/'setting/reservation_v2';target.mkdir(parents=True,exist_ok=True)
 bindings={};proof=[]
 for n,path in inventory['models'].items():
  raw=fetch(path).read_bytes();new=renamed(raw,{k:v for k,v in mapping.items() if k in inventory['textures']});assert len(new)==len(raw)
  (target/mapping[n]).write_bytes(new);proof.append(dict(kind='model',source=path,target='base/setting/reservation_v2/'+mapping[n],source_sha=sha(raw),sha=sha(new)))
 for n in inventory['fragments']:
  raw=fetch('base/maps/'+n).read_bytes();original=zlib.decompress(raw[16:]) if raw[:4]==b'\x03ZIP' else raw
  new=renamed(original,{k:v for k,v in mapping.items() if k in inventory['models']});assert len(new)==len(original)
  destination=client/'maps'/mapping[Path(n).name.lower()];destination.parent.mkdir(exist_ok=True);destination.write_bytes(new)
  bindings[Path(n).stem]=destination.stem
  proof.append(dict(kind='fragment',source='base/maps/'+n,target='base/maps/'+destination.name,source_sha=sha(raw),sha=sha(new)))
 ground=ET.parse(fetch('base/ground.xml')).getroot();ids={}
 for old,new in (('0',10),('1',11)):
  assert ground.find(f"ground[@id='{new}']") is None
  node=ET.SubElement(ground,'ground',name='reservation_v2_'+old,id=str(new));ids[old]=new
  for b in inventory['grounds'][old]:ET.SubElement(node,'brush',filename='reservation_v2\\'+mapping[Path(b['path']).name.lower()],layer=b['layer'])
 ET.indent(ground);(client/'ground.xml').write_bytes(ET.tostring(ground,encoding='utf-8',xml_declaration=True))
 (ROOT/'config/reservation_visuals.json').write_text(json.dumps(dict(version=1,ground_ids=ids,entries=bindings),indent=2)+'\n')
 (OUT/'resource-proof.json').write_text(json.dumps(proof,indent=2));print(json.dumps(dict(isolated_models=len(inventory['models']),isolated_fragments=len(bindings),ground_ids=ids)))
if __name__=='__main__':
 import sys
 sys.path.insert(0,str(ROOT));{'inspect':inspect,'inputs':inputs,'resources':resources}[sys.argv[1]]()
