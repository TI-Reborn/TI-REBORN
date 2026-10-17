"""Provide only the existing bank key to the in-process city API, backed up."""
import argparse
import json
from pathlib import Path
from tools.deploy_stage4_economy import remote

REMOTE=r'''
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,shlex,subprocess,sys,tempfile
os.umask(0o077)
p=json.load(sys.stdin)
backup=Path(p['backup'])
if backup.parent!=Path('/root') or not backup.name.startswith('tio-before-site-backups-'):raise ValueError('Verified private site backup required')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
for name,expected in p['files'].items():
 if Path(name).name!=name or sha(backup/name)!=expected:raise RuntimeError('Complete backup differs')
def state(name):return subprocess.check_output(['systemctl','show',name,'-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True).strip()
before={n:state(n) for n in ('tio-server','tio-bank-api','tio-portal')}
protected=tuple(map(Path,('/etc/tio-server/bank-api.env','/etc/tio-server/server.toml','/etc/systemd/system/tio-server.service','/etc/tio-portal/portal.env')))
guards={str(path):sha(path) for path in protected}
source=protected[0];keys=[]
for line in source.read_text().splitlines():
 if line.strip() and not line.lstrip().startswith('#') and '=' in line:
  name,value=line.split('=',1)
  if name.strip()=='BANK_SERVICE_KEY':keys.append(shlex.split(value,comments=True))
if len(keys)!=1 or len(keys[0])!=1 or not 32<=len(keys[0][0])<=512:raise ValueError('Exactly one existing private service key required')
key=keys[0][0]
if any(ord(c)<33 or ord(c)>126 for c in key):raise ValueError('Unsupported private key encoding')
environment=Path('/etc/tio-server/city-api.env')
dropin=Path('/etc/systemd/system/tio-server.service.d/city-api.conf')
targets={environment:('BANK_SERVICE_KEY='+json.dumps(key)+'\n').encode(),dropin:b'[Service]\nEnvironmentFile=/etc/tio-server/city-api.env\n'}
if any(path.is_symlink() or (path.exists() and path.read_bytes()!=raw) for path,raw in targets.items()):raise RuntimeError('Unexpected existing city adapter configuration')
folder=Path(tempfile.mkdtemp(prefix='tio-city-api-runtime-',dir='/root'))
previous={str(path):path.exists() for path in targets}
for path,exists in previous.items():
 if exists:(folder/Path(path).name).write_bytes(Path(path).read_bytes())
(folder/'previous.json').write_text(json.dumps(dict(paths=previous,service=before,guards=guards)))
created=[]
try:
 for path,raw in targets.items():
  path.parent.mkdir(parents=True,exist_ok=True)
  if path.exists():continue
  descriptor,name=tempfile.mkstemp(dir=path.parent,prefix='.city-api-')
  with os.fdopen(descriptor,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
  temp=Path(name);temp.chmod(0o600 if path==environment else 0o644);temp.replace(path);created.append(path)
 subprocess.run(['systemctl','daemon-reload'],check=True,capture_output=True)
 if before!={n:state(n) for n in before}:raise RuntimeError('Service identity changed during preparation')
 if guards!={str(path):sha(path) for path in protected}:raise RuntimeError('Protected settings changed')
except BaseException:
 for path in created:
  if sha(path)==hashlib.sha256(targets[path]).hexdigest():path.unlink()
 subprocess.run(['systemctl','daemon-reload'],check=True,capture_output=True)
 raise
print(json.dumps(dict(passed=True,utc=datetime.now(timezone.utc).isoformat(),backup=str(folder),
 configuration_sha256={str(path):sha(path) for path in targets},service_unchanged=True,
 protected_configuration_unchanged=True,stripe_configuration_changed=False,key_values_printed=False)))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-report',required=True,type=Path)
    parser.add_argument('--report',required=True,type=Path)
    args=parser.parse_args()
    if args.report.exists():parser.error('Preserve prior evidence')
    proof=json.loads(args.backup_report.read_text(encoding='utf-8'))
    if proof['sqlite_integrity']!='ok':raise ValueError('Complete backup integrity is required')
    result=remote(REMOTE,dict(backup=proof['backup'],files={n:r['sha256'] for n,r in proof['files'].items()}))
    with args.report.open('x',encoding='utf-8') as output:json.dump(result,output,indent=2)
    print(json.dumps(result))


if __name__=='__main__':main()
