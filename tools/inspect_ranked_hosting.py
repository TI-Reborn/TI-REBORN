"""Verify live source parity, integrity and preservation of pre-update accounts."""
from prepare_ranked_deploy import ROOT,SSH
import json,shlex,subprocess

def main():
    manifest=json.loads((ROOT/'reports/ranked/manifest.json').read_text())
    code='''import json,sys,sqlite3,pathlib,hashlib,subprocess
manifest=json.load(sys.stdin);root=pathlib.Path('/opt/tio-emulator')
db=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
old=sqlite3.connect('file:/root/tio-before-ranked-hlua4zet/reservation.sqlite3?mode=ro',uri=True)
accounts=[r[0] for r in old.execute('SELECT login FROM accounts')]
preserved={}
for name, in old.execute("SELECT name FROM sqlite_master WHERE type='table'"):
 columns=[r[1] for r in old.execute('PRAGMA table_info("'+name+'")')]
 column='account' if 'account' in columns else 'login' if 'login' in columns else None
 if column:
  query='SELECT * FROM "'+name+'" WHERE "'+column+'" IN ('+','.join('?' for a in accounts)+')'
  before=sorted(map(repr,old.execute(query,accounts)));after=sorted(map(repr,db.execute(query,accounts)))
  preserved[name]=dict(rows=len(before),unchanged=before==after)
result=dict(service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),
 integrity=db.execute('PRAGMA integrity_check').fetchone()[0],original_accounts=len(accounts),
 accounts=db.execute('SELECT count(*) FROM accounts').fetchone()[0],preserved=preserved,
 pending=db.execute('SELECT count(*) FROM battle_settlement_jobs').fetchone()[0],
 checkpoints=db.execute('SELECT status,count(*) FROM battle_checkpoints GROUP BY status').fetchall(),
 unresolved=db.execute('SELECT count(*) FROM battle_failure_audit WHERE resolved=0').fetchone()[0],
 hashes={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in manifest})
print(json.dumps(result))
'''
    p=subprocess.run(SSH+['python3 -c '+shlex.quote(code)],input=json.dumps(manifest),capture_output=True,text=True,encoding='utf-8')
    if p.returncode:raise RuntimeError(p.stderr)
    report=json.loads(p.stdout)
    report['source_parity']=all(report['hashes'][n]==h['after'] for n,h in manifest.items())
    report['passed']=(report['service']=='active' and report['integrity']=='ok' and report['source_parity']
                      and not report['pending'] and not report['checkpoints'] and not report['unresolved']
                      and all(r['unchanged'] for r in report['preserved'].values()))
    (ROOT/'reports/ranked/hosting-inspection.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    if not report['passed']:raise SystemExit(1)

if __name__=='__main__':main()
