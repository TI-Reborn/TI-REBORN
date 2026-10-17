"""Read-only final production checks after both hosted acceptance scenarios."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.verify_game_operations_hosted import remote
REPORT=ROOT/'reports/bank-trade-release-20261015'
CHECK=r'''
from pathlib import Path
from datetime import datetime,timezone
from hashlib import sha256
import json,sqlite3,subprocess,stat
root=Path('/opt/tio-emulator');backup=Path(request['backup'])
installed={p:sha256((root/p).read_bytes()).hexdigest()==r['after'] for p,r in request['manifest'].items()}
services={name:subprocess.check_output(['systemctl','is-active',name],text=True).strip()
 for name in ('tio-server','tio-bank-api','tio-game-api','tio-registration','tio-portal','nginx')}
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
 foreign=len(db.execute('PRAGMA foreign_key_check').fetchall())
 accounts=db.execute('SELECT count(*) FROM accounts').fetchone()[0]
 leftovers=sum(db.execute('SELECT count(*) FROM accounts WHERE login=?',(name,)).fetchone()[0] for name in request['fixtures'])
 with sqlite3.connect((backup/'at-cutover.sqlite3').as_uri()+'?mode=ro',uri=True) as old:
  old_names={r[0] for r in old.execute('SELECT login FROM accounts')}
  current_names={r[0] for r in db.execute('SELECT login FROM accounts')}
  original_accounts_preserved=old_names<=current_names
 backup_integrities={}
 for name in ('before.sqlite3','at-cutover.sqlite3'):
  with sqlite3.connect((backup/name).as_uri()+'?mode=ro',uri=True) as saved:
   backup_integrities[name]=saved.execute('PRAGMA integrity_check').fetchone()[0]
receipt=json.loads((backup/'backup-manifest.json').read_text())
backup_hashes={name:sha256((backup/name).read_bytes()).hexdigest()==receipt[key] for name,key in
 (('before.sqlite3','database_sha256'),('at-cutover.sqlite3','at_cutover_sha256'),('previous-code-config.tar.gz','code_config_sha256'))}
permissions=dict(directory=oct(stat.S_IMODE(backup.stat().st_mode)),
 files={p.name:oct(stat.S_IMODE(p.stat().st_mode)) for p in backup.iterdir() if p.is_file()})
config_preserved=sha256(Path('/etc/tio-server/server.toml').read_bytes()).hexdigest()==receipt['config_sha256']
report=dict(utc=datetime.now(timezone.utc).isoformat(),installed=True,installed_files=installed,
 services=services,integrity=integrity,foreign_key_violations=foreign,accounts=accounts,
 original_accounts_preserved=original_accounts_preserved,qa_accounts_remaining=leftovers,
 backup_integrity=backup_integrities,backup_hashes=backup_hashes,backup_permissions=permissions,
 config_preserved=config_preserved,graphical_client_verified=False)
report['passed']=all(installed.values()) and all(s=='active' for s in services.values()) and integrity=='ok' and foreign==0 and not leftovers and original_accounts_preserved and all(v=='ok' for v in backup_integrities.values()) and all(backup_hashes.values()) and config_preserved
print(json.dumps(report))
'''

def main():
    fixtures=[]
    for stage in ('bank','trade'):
        accepted=json.loads((ROOT/f'reports/{stage}-operations-20261015/hosted-verification.json').read_text())
        assert accepted['passed'] and accepted['cleanup']['integrity']=='ok'
        fixtures+=accepted['fixtures']
    # Include a fully cleaned earlier attempt as well.
    for path in (ROOT/'reports/bank-operations-20261015').glob('hosted-verification-attempt*.json'):
        fixtures+=json.loads(path.read_text()).get('fixtures',[])
    result=remote(CHECK,dict(backup=json.loads((REPORT/'package.json').read_text())['backup'],
        manifest=json.loads((REPORT/'patch-manifest.json').read_text()),fixtures=fixtures))
    (REPORT/'hosted-health-final.json').write_text(json.dumps(result,indent=2))
    for stage in ('bank','trade'):
        target=ROOT/f'reports/{stage}-operations-20261015/hosted-health-final.json'
        previous=target.with_name('hosted-health-preparation.json')
        if target.exists() and not previous.exists():target.replace(previous)
        target.write_text(json.dumps(result,indent=2))
    print(json.dumps(result));sys.exit(not result['passed'])

if __name__=='__main__':main()
