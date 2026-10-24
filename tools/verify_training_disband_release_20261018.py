"""Read-only release/own-character evidence for the native disband correction."""
import hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import remote
from launcher.build_archive import files_digest
OUT=ROOT/'reports/training-disband-20261018'

def main():
 data=json.loads((ROOT/'.secrets/training-disband-20261018.json').read_text())
 names=data['names']
 state=remote('''import json,sqlite3,subprocess,hashlib
from pathlib import Path
names='''+repr(names)+'''
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 result=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],own_locations={},own_journeys={})
 for name in names:
  result['own_locations'][name]=db.execute('SELECT town_id FROM character_locations WHERE account=?',(name,)).fetchall()
  result['own_journeys'][name]=db.execute('SELECT x,y,tx,ty,started,arrives FROM map_journeys WHERE account=?',(name,)).fetchall()
result['service']=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True)
result['source_hashes']={n:hashlib.sha256(Path(n).read_bytes()).hexdigest() for n in ('server/training_arena.py','server/contracts_service.py','tio/protocol/assault.py')}
print(json.dumps(result))
''')
 assert state['integrity']=='ok' and 'ActiveState=active' in state['service']
 if sys.argv[1]=='gui':
  assert state['own_journeys'][names[0]] or state['own_locations'][names[0]] != [[19]]
  state.update(disband_confirmed=True,recreate_confirmed=True,ready_leader_disband_confirmed=True,second_tls_member_notified=True,map_open_confirmed=True,exit_travel_confirmed=True,native_client_accounts=1,tls_peer_accounts=1,nonleader_gui_tested=False,client_sha256=hashlib.sha256((OUT/'silver.dll').read_bytes()).hexdigest())
  target='gui-verification.json'
 else:
  publication=json.loads((OUT/'client-publication.json').read_text())
  origin='https://185.184.42.88/updates/'
  raw=urllib.request.urlopen(origin+'manifest.json',timeout=30).read();manifest=json.loads(raw)
  assert manifest['version']=='2026.10.18.2' and hashlib.sha256(raw).hexdigest()==publication['manifest_sha256']
  previous=json.loads((OUT/'manifest-before.json').read_text(encoding='utf-8'))
  changed=[r['path'] for r in manifest['files'] if r!=next(p for p in previous['files'] if p['path']==r['path'])]
  assert changed==['silver.dll']
  row=next(r for r in manifest['files'] if r['path']=='silver.dll')
  blob=urllib.request.urlopen(origin+'blobs/'+row['sha256'],timeout=60).read()
  assert blob==(OUT/'silver.dll').read_bytes() and hashlib.sha256(blob).hexdigest()==row['sha256']
  assert files_digest(manifest)==manifest['archive']['filesSha256']
  head=urllib.request.urlopen(urllib.request.Request(origin+'blobs/'+manifest['archive']['sha256'],method='HEAD'),timeout=30)
  assert int(head.headers['Content-Length'])==manifest['archive']['size']
  state.update(version=manifest['version'],manifest_sha256=hashlib.sha256(raw).hexdigest(),https_silver_verified=True,archive_binding_verified=True,archive_size=manifest['archive']['size'],changed=changed)
  target='release-verification.json'
 (OUT/target).write_text(json.dumps(state,indent=2));print(json.dumps(state))

if __name__=='__main__':main()
