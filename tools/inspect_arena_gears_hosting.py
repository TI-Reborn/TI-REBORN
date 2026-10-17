"""Read-only final parity, accounts/saves, service and recovery verification."""
from prepare_arena_gears_deploy import ROOT,SSH
import json,shlex,socket,subprocess


def main():
    folder=ROOT/'reports/arena-loading';manifest=json.loads((folder/'manifest.json').read_text())
    deployment=json.loads((folder/'deployment.json').read_text())
    code='''import json,sys,pathlib,sqlite3,hashlib,subprocess
data=json.load(sys.stdin);root=pathlib.Path('/opt/tio-emulator');backup=pathlib.Path(data['backup'])
assert backup.parent==pathlib.Path('/root') and backup.name.startswith('tio-before-arena-loading-')
with sqlite3.connect(backup/'reservation.sqlite3') as old,sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 preserved={}
 for name, in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'"):
  q='"'+name.replace('"','""')+'"'
  before=set(map(repr,old.execute('SELECT * FROM '+q)));after=set(map(repr,db.execute('SELECT * FROM '+q)))
  preserved[name]=dict(rows=len(before),preserved=before<=after)
 inv=subprocess.check_output(['systemctl','show','-p','InvocationID','--value','tio-server'],text=True).strip()
 journal=subprocess.check_output(['journalctl','_SYSTEMD_INVOCATION_ID='+inv,'--no-pager','-o','cat'],text=True)
 print(json.dumps(dict(service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),
  integrity=db.execute('PRAGMA integrity_check').fetchone()[0],old_accounts=old.execute('SELECT count(*) FROM accounts').fetchone()[0],
  accounts=db.execute('SELECT count(*) FROM accounts').fetchone()[0],preserved=preserved,
  pending=db.execute('SELECT count(*) FROM battle_settlement_jobs').fetchone()[0],
  checkpoints=db.execute('SELECT status,count(*) FROM battle_checkpoints GROUP BY status').fetchall(),
  unresolved=db.execute('SELECT count(*) FROM battle_failure_audit WHERE resolved=0').fetchone()[0],
  errors=[line for line in journal.splitlines() if ' ERROR ' in line or 'Traceback' in line],
  hashes={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in data['files']})))
'''
    result=subprocess.run(SSH+['python3 -c '+shlex.quote(code)],input=json.dumps(dict(backup=deployment['backup'],files=list(manifest))),capture_output=True,text=True,encoding='utf-8')
    if result.returncode:raise RuntimeError(result.stderr)
    report=json.loads(result.stdout);report['source_parity']=all(report['hashes'][n]==h['after'] for n,h in manifest.items())
    report['public_ports']={}
    for port in (28512,28513):
        with socket.create_connection(('185.184.42.88',port),timeout=5):report['public_ports'][str(port)]=True
    report['passed']=(report['service']=='active' and report['integrity']=='ok' and report['source_parity']
        and not report['pending'] and not report['checkpoints'] and not report['unresolved'] and not report['errors']
        and all(r['preserved'] for r in report['preserved'].values()))
    (folder/'hosting-inspection.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('hashes','preserved')}))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
