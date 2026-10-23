"""Excluded female hosted fixtures; original native authentication and animation."""
import argparse,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import fighter_model_gui_20261021 as qa
qa.OUT=ROOT/'reports/female-fighter-20261021';qa.ASSET=ROOT/'assets/female-fighter-v1'
qa.fixture.OUT=qa.OUT;qa.fixture.PRIVATE=ROOT/'.secrets/female-fighter-20261021.json'
qa.MAPPING={
 'base/models/chr_woman_head.mdjx':'native/tio_scout_head.mdjx',
 'base/models/chr_woman_body.mdjx':'native/tio_scout_torso.mdjx',
 'base/models/chr_woman_hands.mdjx':'native/tio_scout_hands.mdjx',
 'base/models/chr_woman_legs.mdjx':'native/tio_scout_legs.mdjx',
 'base/models/chr_woman_head.jpg':'textures/tio_scout_head.jpg',
 'base/models/chr_woman_body.jpg':'textures/tio_scout_body.jpg',
}
old="raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':4,'0x8c4b05':FLOORS[3],'0x8c4a07':115,'0x8c4ab1':115}))"
new="""from tio.appearance import with_appearance
pet=replace(pet,fields={**pet.fields,'0x8c4aef':4,'0x8c4b05':FLOORS[3],'0x8c4a07':115,'0x8c4ab1':115,'0x8c446f':2})
raw=encode_pet_info(with_appearance(pet,bytes((2,10,0,3,0,0))))"""
assert old in qa.fixture.v.PREPARE
qa.fixture.v.PREPARE=qa.fixture.v.PREPARE.replace(old,new)

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

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','stage','launch','restore','cleanup','network'));mode=p.parse_args().mode
 if mode=='provision':qa.fixture.provision()
 elif mode=='cleanup':qa.fixture.cleanup()
 elif mode=='network':qa.fixture.run()
 elif mode=='launch':launch()
 else:getattr(qa,mode)()
