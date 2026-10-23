"""Exact-owned, excluded male/female hosted fixtures for native mesh QA."""
import argparse,hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import verify_launcher_required_hosted_20261020 as qa
from tools import hosted_graphical_qa_bridge as auth
from tools.fix_flamethrower_rig_20261021 import OUT,NAME
qa.OUT=OUT;qa.PRIVATE=ROOT/'.secrets/flamethrower-rig-20261021.json'
qa.v.PREPARE=qa.v.PREPARE.replace('item(9001,301,current=50,maximum=350,equip=1)','item(9001,324,current=300,maximum=300,equip=1)')
qa.v.PREPARE+=r'''
from tio.roster_progression import profile
from tio.appearance import with_appearance
for index,name in enumerate(request):
 with sqlite3.connect(path) as db:
  assert excluded(db,name)
  packet=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(name,)).fetchone()[0]
  packet=profile(packet,1,1+index,b'Flame Rig QA')
  packet=encode_pet_info(with_appearance(decode_pet_info(packet,human_equipment=True),bytes((1,0,0,1,0,0))))
  db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(packet,name))
 SquadStore(path).assign(name,1,1)
'''
GAME=ROOT/'work/groza-20261019/gui/game-a'
LAUNCHER=ROOT/'work/flamethrower-rig-20261021/qa-launcher/TIO Launcher.exe'
def launch(index,candidate):
 assert (GAME/'.tio-owned-qa').is_file()
 manifest=json.loads(urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=20).read());rows={r['path']:r for r in manifest['files']}
 for n in ('ti.exe','orange.dll','silver.dll'):assert hashlib.sha256((GAME/n).read_bytes()).hexdigest()==rows[n]['sha256']
 auth.HASHES={n:rows[n]['sha256'] for n in ('ti.exe','orange.dll','silver.dll')}
 launcher_sha=hashlib.sha256(LAUNCHER.read_bytes()).hexdigest()
 (OUT/'private-qa-launcher.json').write_text(json.dumps(dict(sha256=launcher_sha,public_launcher_changed=False,change='Updater process guard scoped to exact .tio-owned-qa game root, preserving HTTPS resource verification and TLS identity'),indent=2))
 data=json.loads(qa.PRIVATE.read_text());bridge=auth.HostedGraphicalQaBridge(GAME,dict(login=data['names'][index],password=data['passwords'][index],fresh_qa=True),auto_select=True,launcher=LAUNCHER,launcher_sha256=launcher_sha)
 if candidate:(GAME/NAME).write_bytes((OUT/'candidate'/NAME).read_bytes())
 print(json.dumps(dict(started=True,pid=bridge.pid,account=index,candidate=candidate)),flush=True)
 try:
  print(json.dumps(bridge.start_connect()),flush=True)
  for line in sys.stdin:
   if line.strip()=='stop':break
   if line.strip()=='status':print(json.dumps(bridge.status()),flush=True)
 finally:
  bridge.release(cleanup=True);(OUT/f'gui-events-{index}.json').write_text(json.dumps(bridge.events,indent=2))
  if candidate:
   raw=urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+rows[NAME]['sha256'],timeout=30).read();assert hashlib.sha256(raw).hexdigest()==rows[NAME]['sha256'];(GAME/NAME).write_bytes(raw)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','launch','cleanup'));p.add_argument('--account',type=int,choices=(0,1),default=0);p.add_argument('--candidate',action='store_true');a=p.parse_args()
 if a.mode=='launch':launch(a.account,a.candidate)
 elif a.mode=='cleanup':
  data=json.loads(qa.PRIVATE.read_text());matches=json.loads((OUT/'native-matches.json').read_text())
  assert all(set(m['owners'])<=set(data['names']) for m in matches)
  assert qa.v.remote("import json,sqlite3\nwith sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account IN (?,?)',request).fetchone()\nprint(json.dumps(True))",data['names'])
  old="condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)"
  addition="\n  if 'match_id' in columns and request.get('matches'):\n   parts.append(quote('match_id')+' IN ('+','.join('?' for _ in request['matches'])+')');args+=request['matches']\n  "+old
  code=qa.v.CLEANUP.replace(old,addition);assert code!=qa.v.CLEANUP
  result=qa.v.remote(code,dict(names=data['names'],matches=[m['match'] for m in matches],protected_before=data['provision']['protected_before'],require_unchanged_players=False))
  (OUT/'fixture-cleanup.json').write_text(json.dumps(result,indent=2));qa.PRIVATE.unlink();print(json.dumps(result))
 else:qa.provision()
