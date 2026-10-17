"""Read-only final service/timer/scratch audit after approved recovery capture."""
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.prepare_launcher_publication import PRELUDE


def main():
    report=ROOT/'reports/site-backups/launcher014-final-status.json'
    if report.exists():raise FileExistsError('Refusing to replace existing status evidence')
    source=PRELUDE+r'''
result={'checked_utc':datetime.now(timezone.utc).isoformat(),'read_only':True,'publication':before}
result['backup_services']={}
result['backup_timers']={}
for name in ('tio-backup.service','tio-portal-backup.service'):
    output=subprocess.run(['/usr/bin/systemctl','show',name,'-p','Result','-p','ExecMainStatus','-p','ActiveState'],capture_output=True,text=True,check=True).stdout
    result['backup_services'][name]=dict(line.split('=',1) for line in output.splitlines() if '=' in line)
for name in ('tio-backup.timer','tio-portal-backup.timer'):
    output=subprocess.run(['/usr/bin/systemctl','show',name,'-p','NextElapseUSecRealtime','-p','LastTriggerUSec','-p','Persistent','-p','ActiveState'],capture_output=True,text=True,check=True).stdout
    result['backup_timers'][name]=dict(line.split('=',1) for line in output.splitlines() if '=' in line)
query="SELECT count(*) FROM pg_database WHERE datname ~ '^tiobackupcheck_[a-f0-9]{32}$'"
scratch=checker._command(['psql','-X','--no-psqlrc','--no-align','--tuples-only','--set=ON_ERROR_STOP=1','--dbname=postgres','--command='+query],'scratch metadata',runner=subprocess.run,stdout=subprocess.PIPE)
result['scratch_databases_remaining']=int(scratch.stdout.strip())
print(json.dumps(result))
'''
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=15',
        'root@185.184.42.88','/usr/bin/python3 -'],input=source,text=True,capture_output=True)
    if result.returncode:raise RuntimeError('Read-only recovery status audit failed; private output suppressed')
    data=json.loads(result.stdout)
    with report.open('x',encoding='utf-8') as output:output.write(json.dumps(data,indent=2)+'\n')
    print(json.dumps(data))


if __name__=='__main__':main()
