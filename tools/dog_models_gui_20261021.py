"""Three canine recruits on exact-owned, ranking-excluded hosted QA fixtures."""
import argparse,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import fighter_model_gui_20261021 as qa
qa.OUT=ROOT/'reports/dog-models-20261021';qa.ASSET=ROOT/'assets/dog-mercenaries-v1'
qa.fixture.OUT=qa.OUT;qa.fixture.PRIVATE=ROOT/'.secrets/dog-models-20261021.json'
qa.MAPPING={f'base/models/dog_{breed}{ext}':f'{breed}/{folder}/dog_{breed}{ext}' for breed in ('doberman','huski','alsatian') for folder,ext in (('native','.mdjx'),('textures','.jpg'))}
qa.fixture.v.PREPARE+=r'''
from tio.roster_progression import profile
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
template=bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex'])
for name in request:
 assert QA_LOGIN.fullmatch(name)
 for identity,resource,label in ((2,3,'Doberman QA'),(3,4,'Husky QA'),(4,5,'Shepherd QA')):
  packet=profile(template,identity,resource,label.encode('ascii'))
  # An unequipped dog vest permits a separate native armor-fit check.
  inventory=encode_item_list(identity,(item(9100+identity,255,current=100,maximum=100),)) if identity==2 else encode_item_list(identity,())
  OwnedPetStore(path).validate(packet,inventory,False)
  with sqlite3.connect(path) as db:
   assert excluded(db,name)
   db.execute('INSERT INTO owned_pets VALUES (?,?,?,?,?)',(name,identity,0,packet,inventory))
 # Available recruits are all visible in the native roster even outside squad.
 SquadStore(path).assign(name,2,2);SquadStore(path).assign(name,3,3)
'''

def launch():
 rows={r['path']:r for r in json.loads(urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=20).read())['files']}
 for name in ('ti.exe','orange.dll','silver.dll'):assert qa.sha((qa.GAME/name).read_bytes())==rows[name]['sha256']
 qa.auth.HASHES={name:rows[name]['sha256'] for name in ('ti.exe','orange.dll','silver.dll')}
 data=json.loads(qa.fixture.PRIVATE.read_text())
 bridge=qa.auth.HostedGraphicalQaBridge(qa.GAME,dict(login=data['names'][0],password=data['passwords'][0],fresh_qa=True),
  auto_select=True,launcher=qa.LAUNCHER,launcher_sha256='52f29d6376dc6d5fc96ab13672bb05c4ca2802ff85236313ba06df7ca2533cc2')
 staged=(qa.OUT/'qa-stage.json').exists()
 for name,source in qa.MAPPING.items():
  raw=(qa.ASSET/source).read_bytes()
  if staged:qa.atomic(qa.GAME/name,raw)
  else:assert qa.sha((qa.GAME/name).read_bytes())==qa.sha(raw)==rows[name]['sha256'],name
 print(json.dumps(dict(started=True,pid=bridge.pid,private_candidate=staged,published_assets=not staged)),flush=True)
 try:
  print(json.dumps(bridge.start_connect()),flush=True)
  for line in sys.stdin:
   if line.strip()=='status':
    status=bridge.status();(qa.OUT/('gui-status-candidate.json' if staged else 'gui-status-published.json')).write_text(json.dumps(status,indent=2));print(json.dumps(status),flush=True)
   elif line.strip()=='stop':break
 finally:
  bridge.release(cleanup=True);(qa.OUT/('gui-events-candidate.json' if staged else 'gui-events-published.json')).write_text(json.dumps(bridge.events,indent=2))

def armor_fixture():
 code=r'''
import json,sqlite3
from dataclasses import replace
from tio.rating_visibility import QA_LOGIN,excluded
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import decode_item_list,encode_item_list
from tio.level_progression import FLOORS
path='/var/lib/tio-server/reservation.sqlite3'
with sqlite3.connect(path) as db:
 for name in request:
  assert QA_LOGIN.fullmatch(name) and excluded(db,name)
  raw,inventory=db.execute('SELECT pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=2 AND human=0',(name,)).fetchone()
  pet=decode_pet_info(raw,human_equipment=False);assert pet.fields['0x8c446f']==3
  raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':4,'0x8c4b05':FLOORS[3]}))
  items=decode_item_list(inventory)[1]
  items=tuple(replace(i,unknown_u8_01=1,location_raw=4) if i.template_id==255 else i for i in items)
  db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=2',(raw,encode_item_list(2,items),name))
print(json.dumps(dict(passed=True,excluded_owned_accounts_only=True,breed='doberman',equipped_template=255)))
'''
 data=json.loads(qa.fixture.PRIVATE.read_text());result=qa.fixture.v.remote(code,data['names'])
 (qa.OUT/'armor-fixture.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','stage','launch','restore','cleanup','network','armor'));mode=p.parse_args().mode
 if mode=='provision':qa.fixture.provision()
 elif mode=='cleanup':qa.fixture.cleanup()
 elif mode=='network':qa.fixture.run()
 elif mode=='launch':launch()
 elif mode=='armor':armor_fixture()
 else:getattr(qa,mode)()
