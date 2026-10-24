"""Publish one visual-only item binding fix using the established asset transaction."""
import argparse,ast,base64,hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.armor_fit_fix_20261021 import OUT,ASSET,validate as validate_xml,FIELDS
from tools.deploy_stage4_economy import remote
from tools.publish_ability_icons_20261020 import STATE
VERSION='2026.10.21.4';NAME='base/shared config/items.xml'
NEWS='Проверена совместимость брони с моделями бойцов. Исправлено исчезновение ног при надевании Pantsu kudasai; характеристики предметов сохранены.'
sha=lambda b:hashlib.sha256(b).hexdigest()
tree=ast.parse((ROOT/'tools/publish_female_fighter_20261021.py').read_text(encoding='utf-8'))
REMOTE=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REMOTE' for t in n.targets)))
old="expected={'base/models/chr_woman_'+part+ext for part,ext in [('head','.mdjx'),('body','.mdjx'),('hands','.mdjx'),('legs','.mdjx'),('head','.jpg'),('body','.jpg')]}";assert old in REMOTE
REMOTE=REMOTE.replace(old,'expected='+repr({NAME}))
REMOTE=REMOTE.replace("a['version']=='2026.10.20.5' and b['version']=='2026.10.21.1'","a['version']=='2026.10.21.3' and b['version']=='2026.10.21.4'")
check="else:assert raw[:2]==b'\\xff\\xd8' and raw[-2:]==b'\\xff\\xd9'";assert check in REMOTE
REMOTE=REMOTE.replace(check,"""else:
  from xml.etree import ElementTree as ET
  fields={'model_2':'chr_man_legs','texture_2':'chr_man_body.jpg','w_model_2':'chr_woman_legs','w_texture_2':'chr_woman_body.jpg'}
  start=before.index(b'<item id="206" ');end=before.index(b'</item>',start);block=before[start:end]
  newline=b'\\r\\n' if b'\\r\\n' in block else b'\\n';marker=b'    <for>'
  assert all(('key="'+k+'"').encode() not in block for k in fields) and block.count(marker)==1
  addition=b''.join(('    <value key="'+k+'" val="'+v+'" />').encode()+newline for k,v in fields.items())
  assert raw==before[:start]+block.replace(marker,addition+marker)+before[end:]
  parsed=ET.fromstring(raw);item=next(i for i in parsed.iter('item') if i.get('id')=='206')
  values={v.get('key'):v.get('val') for v in item.findall('value')};assert values['bodypart']=='legs'
  assert values['p_def']=='5' and values['durability']=='300'
  for field,value in fields.items():
   dependency='base/models/'+value+('.mdjx' if 'model' in field else '')
   assert ar[dependency]==br[dependency]
   dependency_raw=(live/'blobs'/ar[dependency]['sha256']).read_bytes();assert sha(dependency_raw)==ar[dependency]['sha256']
""")
REMOTE=REMOTE.replace('tio-before-female-fighter-','tio-before-armor-fit-').replace('.female-model-','.armor-fit-')
REMOTE=REMOTE.replace("before_service=state();assert 'ActiveState=active' in before_service", "assert sha((root/'evidence/items_diagnostic.xml').read_bytes())==p['hosted_catalog_sha256']\nbefore_service=state();assert 'ActiveState=active' in before_service")
def payload(require_visual=False):
 old=(OUT/'manifest-before.json').read_bytes();m=json.loads(old);assert m['version']=='2026.10.21.3';raw=(ASSET/'items.xml').read_bytes()
 validation=validate_xml((OUT/'source'/NAME).read_bytes(),raw);assert validation['passed']
 row=next(r for r in m['files'] if r['path']==NAME);assert row['sha256']==sha((OUT/'source'/NAME).read_bytes())
 row.update(sha256=sha(raw),size=len(raw),seed=False);m.update(version=VERSION,news=NEWS)
 new=(json.dumps(m,ensure_ascii=False,indent=2)+'\n').encode();(OUT/'manifest.json').write_bytes(new)
 if require_visual:
  proof=json.loads((OUT/'gui-visual-candidate.json').read_text());assert proof['passed'] and proof['real_game_client'] and proof['female_206_legs_visible']
 return dict(mode='validate',before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),files={NAME:dict(raw=base64.b64encode(raw).decode(),sha256=sha(raw))},news=NEWS,hosted_catalog_sha256=sha((OUT/'hosted-items-fixed.xml').read_bytes()))
def verify():
 new=(OUT/'manifest.json').read_bytes();origin='https://185.184.42.88/updates/'
 assert urllib.request.urlopen(origin+'manifest.json',timeout=30).read()==new
 row=next(r for r in json.loads(new)['files'] if r['path']==NAME)
 assert urllib.request.urlopen(origin+'blobs/'+row['sha256'],timeout=30).read()==(ASSET/'items.xml').read_bytes()
 state=remote(STATE,{});assert state['integrity']=='ok' and 'ActiveState=active' in state['service']
 result=dict(passed=True,version=VERSION,verified_xml_sha256=row['sha256'],service=state['service'],integrity=state['integrity'])
 (OUT/'https-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('validate','publish','verify'));mode=parser.parse_args().mode
 if mode=='verify':verify()
 else:
  data=payload(require_visual=mode=='publish');data['mode']=mode
  if mode=='publish':assert not (OUT/'publication.json').exists()
  result=remote(REMOTE,data);(OUT/('publication.json' if mode=='publish' else 'remote-validation.json')).write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if not k.startswith('protected_')}))
