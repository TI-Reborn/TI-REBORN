"""Read-only final release/account/checkpoint verification after QA cleanup."""
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH,REPORT,WORK
def main():
    names=('server/training_arena.py','server/contracts_service.py','tio/protocol/assault.py')
    expected={n:hashlib.sha256((WORK/'candidate'/n).read_bytes()).hexdigest() for n in names}
    release={n:dict(before=hashlib.sha256((WORK/'baseline'/n).read_bytes()).hexdigest(),after=expected[n]) for n in names}
    (REPORT/'release-files.json').write_text(json.dumps(release,indent=2))
    fixtures=json.loads((REPORT/'hosted-verification.json').read_text())['fixtures']
    source='expected='+repr(expected)+'\nfixtures='+repr(fixtures)+'''\nimport hashlib,json,sqlite3,subprocess
from pathlib import Path
from tio.rating_visibility import QA_LOGIN
root=Path('/opt/tio-emulator')
assert all(hashlib.sha256((root/n).read_bytes()).hexdigest()==h for n,h in expected.items())
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
 accounts=db.execute('SELECT login FROM accounts').fetchall()
 counts={n:db.execute('SELECT count(*) FROM '+n).fetchone()[0] for n in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs')}
 qa=sum(bool(QA_LOGIN.fullmatch(n)) for n, in accounts)
with sqlite3.connect('file:/root/tio-before-game-operations-training-base-20261018/at-cutover.sqlite3?mode=ro',uri=True) as db:
 baseline={n for n, in db.execute('SELECT login FROM accounts')}
assert {n for n, in accounts}==baseline
remaining_owned=len(set(fixtures)&baseline)
manifest=json.loads(Path('/var/www/tio-client/updates/manifest.json').read_text())
status=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()
assert integrity=='ok' and status=='active' and len(accounts)==19 and not remaining_owned and not any(counts.values())
assert manifest['version']=='2026.10.18.1'
print(json.dumps(dict(passed=True,service=status,integrity=integrity,accounts=len(accounts),baseline_account_names_preserved=True,remaining_task_fixtures=remaining_owned,preexisting_reserved_accounts_preserved=qa,retained=counts,source_sha256=expected,client_version=manifest['version'],local_player_data_uploaded=False)))
'''
    r=subprocess.run(SSH+['cd /opt/tio-emulator && .venv/bin/python -'],input=source,capture_output=True,encoding='utf-8',timeout=60)
    if r.returncode:raise RuntimeError(r.stderr[-1500:])
    value=json.loads(r.stdout);assert not (ROOT/'.secrets/training-base-20261018.json').exists()
    (REPORT/'final-state.json').write_text(json.dumps(value,indent=2));print(json.dumps(value))
if __name__=='__main__':main()
