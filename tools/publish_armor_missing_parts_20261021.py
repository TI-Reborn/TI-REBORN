"""Publish the validated visual catalog repair, preserving the live manifest."""
import argparse,ast,base64,hashlib,inspect,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.armor_missing_parts_20261021 import OUT,ASSET,edits,patch,validate
from tools.deploy_stage4_economy import remote
from tools.publish_ability_icons_20261020 import STATE
VERSION='2026.10.21.5';NAME='base/shared config/items.xml';NEWS='Исправлены лицо под Helmet 208 и отсутствующие кисти у Rags, женских Exo и других нагрудников. Параметры брони сохранены.'
sha=lambda b:hashlib.sha256(b).hexdigest()
tree=ast.parse((ROOT/'tools/publish_female_fighter_20261021.py').read_text(encoding='utf-8'));REMOTE=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REMOTE' for t in n.targets)))
old="expected={'base/models/chr_woman_'+part+ext for part,ext in [('head','.mdjx'),('body','.mdjx'),('hands','.mdjx'),('legs','.mdjx'),('head','.jpg'),('body','.jpg')]}";assert old in REMOTE
REMOTE=REMOTE.replace(old,'expected='+repr({NAME})+'\nfrom xml.etree import ElementTree as ET\n'+'\n'.join(inspect.getsource(f) for f in (edits,patch,validate)))
REMOTE=REMOTE.replace("a['version']=='2026.10.20.5' and b['version']=='2026.10.21.1'","a['version']=='2026.10.21.4' and b['version']=='2026.10.21.5'")
old="else:assert raw[:2]==b'\\xff\\xd8' and raw[-2:]==b'\\xff\\xd9'";assert old in REMOTE
REMOTE=REMOTE.replace(old,"""else:
  assert validate(before,raw)['passed']
  for values in edits(before).values():
   for key,value in values.items():
    if 'model' not in key and 'texture' not in key:continue
    dependency='base/models/'+value+('.mdjx' if 'model' in key else '')
    assert ar[dependency]==br[dependency]
    assert sha((live/'blobs'/ar[dependency]['sha256']).read_bytes())==ar[dependency]['sha256']
""")
REMOTE=REMOTE.replace('tio-before-female-fighter-','tio-before-armor-missing-parts-').replace('.female-model-','.missing-parts-')
REMOTE=REMOTE.replace("before_service=state();assert 'ActiveState=active' in before_service","assert sha((root/'evidence/items_diagnostic.xml').read_bytes())==p['hosted_catalog_sha256']\nbefore_service=state();assert 'ActiveState=active' in before_service")
def payload(require_visual=False):
 old=(OUT/'manifest-before.json').read_bytes();m=json.loads(old);assert m['version']=='2026.10.21.4';raw=(ASSET/'items.xml').read_bytes();validate((OUT/'items-before.xml').read_bytes(),raw)
 if require_visual:
  v=json.loads((OUT/'native-visual.json').read_text());assert v['passed'] and v['empty_hands'] and v['helmet_face_both_sexes'] and v['exo_both_variants']
 row=next(r for r in m['files'] if r['path']==NAME);assert row['sha256']==sha((OUT/'items-before.xml').read_bytes());row.update(sha256=sha(raw),size=len(raw),seed=False);m.update(version=VERSION,news=NEWS)
 new=(json.dumps(m,ensure_ascii=False,indent=2)+'\n').encode();(OUT/'manifest.json').write_bytes(new)
 return dict(before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),files={NAME:dict(raw=base64.b64encode(raw).decode(),sha256=sha(raw))},news=NEWS,hosted_catalog_sha256=sha((OUT/'hosted-items-fixed.xml').read_bytes()))
def verify():
 raw=urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=30).read();assert raw==(OUT/'manifest.json').read_bytes();m=json.loads(raw);row=next(r for r in m['files'] if r['path']==NAME)
 assert urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+row['sha256'],timeout=30).read()==(ASSET/'items.xml').read_bytes()
 state=remote(STATE,{});assert state['integrity']=='ok' and 'ActiveState=active' in state['service'];r=dict(passed=True,version=VERSION,manifest_sha256=sha(raw),service=state['service'],integrity=state['integrity']);(OUT/'https-verification.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','publish','verify'));mode=p.parse_args().mode
 if mode=='verify':verify()
 else:
  data=payload(mode=='publish');data['mode']=mode
  if mode=='publish':assert not (OUT/'publication.json').exists()
  result=remote(REMOTE,data);(OUT/('publication.json' if mode=='publish' else 'remote-validation.json')).write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if not k.startswith('protected_')}))
