"""Add only the Blender flame atlas using the reviewed asset transaction."""
import argparse,ast,base64,hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_stage4_economy import remote
OUT=ROOT/'reports/flame-blender-20261021';ASSET=ROOT/'assets/flame-jet-v1/tio-flame-jet.png'
NAME='base/gfx/tio-effects/tio-flame-jet.png';VERSION='2026.10.21.8'
NEWS='Новый плотный направленный факел огнемёта из Blender. Требуется лаунчер 0.1.28.'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
tree=ast.parse((ROOT/'tools/publish_female_fighter_20261021.py').read_text(encoding='utf-8'))
REMOTE=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REMOTE' for t in n.targets)))
start=REMOTE.index('expected=');end=REMOTE.index('\ndef atomic',start)
REMOTE=REMOTE[:start]+'expected='+repr({NAME})+'\n'+REMOTE[end:]
REMOTE=REMOTE.replace("a['version']=='2026.10.20.5' and b['version']=='2026.10.21.1'","a['version']=='2026.10.21.7' and b['version']=='2026.10.21.8'")
REMOTE=REMOTE.replace("assert len(a['files'])==len(b['files']) and [r['path'] for r in a['files']]==[r['path'] for r in b['files']]","assert len(b['files'])==len(a['files'])+1 and b['files'][:-1]==a['files']")
REMOTE=REMOTE.replace("assert len(ar)==len(a['files']) and {n for n in ar if ar[n]!=br[n]}==expected==set(p['files'])","assert len(ar)==len(a['files']) and set(br)-set(ar)==expected==set(p['files'])\nassert all(ar[n]==br[n] for n in ar)")
REMOTE=REMOTE.replace(" before=(live/'blobs'/ar[name]['sha256']).read_bytes()\n assert sha(before)==ar[name]['sha256'] and len(before)==ar[name]['size']"," assert name not in ar")
REMOTE=REMOTE.replace("else:assert raw[:2]==b'\\xff\\xd8' and raw[-2:]==b'\\xff\\xd9'","else:assert raw[:8]==b'\\x89PNG\\r\\n\\x1a\\n' and struct.unpack_from('>II',raw,16)==(512,512)")
REMOTE=REMOTE.replace('payload[name]=raw;prior[name]=before','payload[name]=raw')
REMOTE=REMOTE.replace('tio-before-female-fighter-','tio-before-flame-jet-').replace('.female-model-','.flame-jet-')
REMOTE=REMOTE.replace("assert p['mode']=='publish'","assert p['mode']=='publish'\nassert shutil.disk_usage('/').free>768*1024*1024")

def payload():
 from PIL import Image
 raw=ASSET.read_bytes();image=Image.open(ASSET);assert image.mode=='RGBA' and image.size==(512,512)
 assert json.loads((ROOT/'assets/flame-jet-v1/build.json').read_text())['passed']
 assert json.loads((OUT/'native-unit.json').read_text())['passed']
 proof=json.loads((OUT/'visual-validation.json').read_text());assert proof['passed'] and proof['real_native_client']
 old=(OUT/'manifest-before.json').read_bytes();m=json.loads(old);assert m['version']=='2026.10.21.7'
 assert all(r['path']!=NAME for r in m['files'])
 m['files'].append(dict(path=NAME,sha256=sha(raw),size=len(raw),seed=False));m.update(version=VERSION,news=NEWS)
 new=(json.dumps(m,ensure_ascii=False,indent=2)+'\n').encode();(OUT/'manifest.json').write_bytes(new)
 return dict(before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),news=NEWS,files={NAME:dict(raw=base64.b64encode(raw).decode(),sha256=sha(raw))})

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','publish','verify'));a=p.parse_args()
 if a.mode=='verify':
  base='https://185.184.42.88/updates/';raw=(OUT/'manifest.json').read_bytes()
  assert urllib.request.urlopen(base+'manifest.json',timeout=30).read()==raw
  assert urllib.request.urlopen(base+'blobs/'+sha(ASSET.read_bytes()),timeout=30).read()==ASSET.read_bytes()
  r=dict(passed=True,trusted_https=True,version=VERSION,sha256=sha(ASSET.read_bytes()))
 else:
  data=payload();data['mode']=a.mode
  if a.mode=='publish':assert not (OUT/'asset-publish.json').exists()
  r=remote(REMOTE,data)
 (OUT/('asset-'+a.mode+'.json')).write_text(json.dumps(r,indent=2))
 print(json.dumps({k:v for k,v in r.items() if not k.startswith('protected_')}))
