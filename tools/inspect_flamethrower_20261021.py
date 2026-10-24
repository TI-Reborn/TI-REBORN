"""Read-only hosted baseline for the approved directed flamethrower."""
import hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH,remote
WORK=ROOT/'work/flamethrower-implementation-20261021'
OUT=ROOT/'reports/flamethrower-implementation-20261021'
FILES=('tio/combat.py','tio/combat_rolls.py','tio/visibility.py','tio/battle_hazards.py',
       'tio/battle_item_effects.py','tio/protocol/battle_attack.py','server/battle_events.py',
       'config/special_items.json','config/weapon_catalog.json','server/battle_journal.py')
def main():
 WORK.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
 assert not (WORK/'baseline').exists()
 r=subprocess.run(SSH+['tar -czf - -C /opt/tio-emulator '+' '.join(FILES)],capture_output=True,check=True,timeout=60)
 with tarfile.open(fileobj=io.BytesIO(r.stdout),mode='r:gz') as a:a.extractall(WORK/'baseline',filter='data')
 state=remote('''import json,sqlite3,subprocess,hashlib,base64
from pathlib import Path
db=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
state=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],accounts=db.execute('SELECT count(*) FROM accounts').fetchone()[0],retained={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs')},table_count=len(tables))
state['service']=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True)
state['connections']=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines())
for key,name in [('manifest','/var/www/tio-client/updates/manifest.json'),('launcher_manifest','/var/www/tio-client/downloads/launcher-manifest.json')]:
 raw=Path(name).read_bytes();state[key]=json.loads(raw);state[key+'_raw']=base64.b64encode(raw).decode()
print(json.dumps(state))
''')
 import base64
 for k in ('manifest','launcher_manifest'):(WORK/(k+'-before.json')).write_bytes(base64.b64decode(state.pop(k+'_raw')))
 hashes={n:hashlib.sha256((WORK/'baseline'/n).read_bytes()).hexdigest() for n in FILES}
 state['local_differences']=[n for n,h in hashes.items() if not (ROOT/n).exists() or hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
 (OUT/'baseline-hashes.json').write_text(json.dumps(hashes,indent=2))
 (OUT/'inspection.json').write_text(json.dumps(state,indent=2))
 print(json.dumps({k:v for k,v in state.items() if k not in ('manifest',)}))
if __name__=='__main__':main()
