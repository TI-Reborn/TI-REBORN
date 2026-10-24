"""Read-only final audit against the actual backed-up hosting state."""
import hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import remote
OUT=ROOT/'reports/training-groups-20261018'
baseline=json.loads((OUT/'baseline.json').read_text())
candidate=json.loads((OUT/'server-review.json').read_text())
deployment=json.loads((OUT/'deployment.json').read_text())
assert json.loads((OUT/'remote-checks.json').read_text())['passed']
assert json.loads((OUT/'gui-verification.json').read_text())['passed']
state=remote('''import json,hashlib,sqlite3,subprocess
from pathlib import Path
from tio.rating_visibility import QA_LOGIN
backup=Path('''+repr(deployment['backup'])+''')
with sqlite3.connect('file:'+str(backup/'at-cutover.sqlite3')+'?mode=ro',uri=True) as old,sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 before={r[0] for r in old.execute('SELECT login FROM accounts')};after={r[0] for r in db.execute('SELECT login FROM accounts')}
 own={'qtb772dc6ea','qt87b4c530a'}
 assert before-own==after and not own&after
 assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
 r=dict(accounts=len(after),preexisting_accounts_preserved=True,own_fixtures_removed=True,integrity='ok',retained={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs')},backup_database_valid=old.execute('PRAGMA integrity_check').fetchone()==('ok',),backup_code_config_present=(backup/'previous-code-config.tar.gz').is_file())
 r['source_hashes']={n:hashlib.sha256(Path(n).read_bytes()).hexdigest() for n in ('server/training_arena.py','server/contracts_service.py','tio/protocol/assault.py')}
 r['service']=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True)
 assert 'ActiveState=active' in r['service']
print(json.dumps(r))
''')
assert state['source_hashes']['server/training_arena.py']==candidate['after_sha256']
for name in ('server/contracts_service.py','tio/protocol/assault.py'):assert state['source_hashes'][name]==baseline['source_hashes'][name]
raw=urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=30).read()
assert hashlib.sha256(raw).hexdigest()==baseline['manifest_sha256']
assert not (ROOT/'.secrets/training-groups-20261018.json').exists()
state.update(client_manifest_unchanged=True,private_credentials_removed=True,only_changed_source='server/training_arena.py')
(OUT/'final-state.json').write_text(json.dumps(state,indent=2));print(json.dumps(state))
