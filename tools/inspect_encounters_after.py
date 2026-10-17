"""Read-only hosted encounter health report; no account secrets."""
from pathlib import Path
import json,subprocess,shlex
ROOT=Path(__file__).resolve().parents[1]
code="""import sqlite3,json,subprocess
db=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
print(json.dumps(dict(service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),
integrity=db.execute('PRAGMA integrity_check').fetchone()[0],accounts=db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],
checkpoints=db.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0],pending=db.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0],
encounters=db.execute('SELECT * FROM world_encounter_audit').fetchall(),
state=db.execute('SELECT * FROM world_encounter_state').fetchall(),
rewards=db.execute('SELECT account,result,credits FROM battle_rewards WHERE account IN (SELECT account FROM world_encounter_audit)').fetchall(),
rank=db.execute('SELECT account,earned FROM rank_battle_audit WHERE account IN (SELECT account FROM world_encounter_audit)').fetchall())))"""
result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@185.184.42.88','python3 -c '+shlex.quote(code)],capture_output=True,text=True)
if result.returncode:raise RuntimeError(result.stderr)
report=json.loads(result.stdout)
(ROOT/'reports/dog-encounters/hosted-health.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
