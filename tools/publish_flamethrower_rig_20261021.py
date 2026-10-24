"""Publish exactly one skinned weapon model using the existing asset transaction."""
import argparse,ast,base64,hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.fix_flamethrower_rig_20261021 import OUT,SOURCE,NAME,build
from tools.mdjx_mesh import read,encode
from tools.deploy_stage4_economy import remote
from tools.publish_ability_icons_20261020 import STATE
VERSION='2026.10.21.7'
NEWS='Исправлено крепление огнемёта: баллоны за спиной, ствол в руках бойца. Обновите клиент через лаунчер.'
sha=lambda b:hashlib.sha256(b).hexdigest()
tree=ast.parse((ROOT/'tools/publish_female_fighter_20261021.py').read_text(encoding='utf-8'))
REMOTE=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REMOTE' for t in n.targets)))
start=REMOTE.index('expected=');end=REMOTE.index('\ndef atomic',start)
REMOTE=REMOTE[:start]+'expected='+repr({NAME})+'\n'+REMOTE[end:]
REMOTE=REMOTE.replace("a['version']=='2026.10.20.5' and b['version']=='2026.10.21.1'","a['version']=='2026.10.21.6' and b['version']=='2026.10.21.7'")
REMOTE=REMOTE.replace('nb in (1,10,43)','nb == 2')
REMOTE=REMOTE.replace('tio-before-female-fighter-','tio-before-flamethrower-rig-').replace('.female-model-','.flame-rig-')
REMOTE=REMOTE.replace("assert p['mode']=='publish'","assert p['mode']=='publish'\nassert shutil.disk_usage('/').free > 768*1024*1024, 'Insufficient free disk for safe backup and publication'")
# The old source itself is pinned, not just a model filename or user-supplied plan.
REMOTE=REMOTE.replace("payload[name]=raw;prior[name]=before", "assert sha(before)=='b1156141d32cb77a8ce09a236cd133a026b3ea403a5af0ab1a9b798c98af97a2'\n assert sha(raw)=='d579984b022543ea2826dcf0c568d78fcc2821192f6de6f0248a243dd533b735'\n payload[name]=raw;prior[name]=before")

def payload():
 build();old=(OUT/'manifest-before.json').read_bytes();m=json.loads(old);assert m['version']=='2026.10.21.6'
 raw=(OUT/'candidate'/NAME).read_bytes();mesh=read(OUT/'candidate'/NAME);assert encode(mesh)==raw
 assert json.loads((OUT/'rig-validation.json').read_text())['passed']
 proof=json.loads((OUT/'native-visual.json').read_text());assert proof['passed'] and proof['native_battle_standing']
 row=next(r for r in m['files'] if r['path']==NAME);assert row['sha256']==sha((SOURCE/NAME).read_bytes())
 row.update(size=len(raw),sha256=sha(raw),seed=False);m.update(version=VERSION,news=NEWS)
 new=(json.dumps(m,ensure_ascii=False,indent=2)+'\n').encode();(OUT/'manifest.json').write_bytes(new)
 return dict(before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),news=NEWS,
  files={NAME:dict(raw=base64.b64encode(raw).decode(),sha256=sha(raw),bone_tail_sha256=sha(mesh.tail))})

def verify():
 new=(OUT/'manifest.json').read_bytes();url='https://185.184.42.88/updates/'
 assert urllib.request.urlopen(url+'manifest.json',timeout=30).read()==new
 row=next(r for r in json.loads(new)['files'] if r['path']==NAME)
 assert urllib.request.urlopen(url+'blobs/'+row['sha256'],timeout=30).read()==(OUT/'candidate'/NAME).read_bytes()
 state=remote(STATE,{});before=json.loads((OUT/'publication.json').read_text());assert state['integrity']=='ok' and state['service']==before['service']
 result=dict(passed=True,version=VERSION,trusted_https=True,changed_paths=[NAME],sha256=row['sha256'],service=state['service'],integrity=state['integrity'])
 (OUT/'https-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','publish','verify'));mode=p.parse_args().mode
 if mode=='verify':verify()
 else:
  data=payload();data['mode']=mode
  if mode=='publish':assert not (OUT/'publication.json').exists()
  result=remote(REMOTE,data);(OUT/('publication.json' if mode=='publish' else 'remote-validation.json')).write_text(json.dumps(result,indent=2))
  print(json.dumps({k:v for k,v in result.items() if not k.startswith('protected_')}))
