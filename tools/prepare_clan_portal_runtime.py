"""Back up and permit only the new Next cache; preserve live game identity."""
import argparse
import json
from pathlib import Path
from tools.deploy_stage4_economy import remote

REMOTE=r'''
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,os,subprocess,tempfile
os.umask(0o077)
def run(*args):return subprocess.run(args,capture_output=True,text=True,check=True,timeout=30).stdout.strip()
def state(name):return run('systemctl','show',name,'-p','MainPID','-p','ActiveState','-p','NRestarts')
before={n:state(n) for n in ('tio-server','tio-portal','tio-bank-api')}
if 'ActiveState=active' not in before['tio-portal']:raise RuntimeError('Portal is not active')
target=Path('/etc/systemd/system/tio-portal.service.d/clan-cache.conf')
raw=b'[Service]\nReadWritePaths=-/opt/tio-portal/current/.next-clan-release/cache\n'
if target.exists() and target.read_bytes()!=raw:raise RuntimeError('Unexpected existing clan cache permission')
folder=Path(tempfile.mkdtemp(prefix='tio-clan-portal-runtime-',dir='/root'))
old=target.read_bytes() if target.exists() else None
(folder/'previous.json').write_text(json.dumps(dict(path=str(target),existed=old is not None,service=before)))
if old is not None:(folder/'clan-cache.conf').write_bytes(old)
target.parent.mkdir(parents=True,exist_ok=True)
descriptor,name=tempfile.mkstemp(dir=target.parent,prefix='.clan-cache-')
with os.fdopen(descriptor,'wb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
Path(name).chmod(0o644);Path(name).replace(target)
run('systemctl','daemon-reload')
after={n:state(n) for n in before}
if before!=after:raise RuntimeError('Service identity changed during cache preparation')
print(json.dumps(dict(passed=True,timestamp_utc=datetime.now(timezone.utc).isoformat(),backup=str(folder),
 configuration_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),service_unchanged=True)))
'''

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',required=True,type=Path)
    args=p.parse_args()
    if args.report.exists():p.error('Preserve the prior report')
    result=remote(REMOTE,{})
    with args.report.open('x',encoding='utf-8') as output:json.dump(result,output,indent=2)
    print(json.dumps(result))

if __name__=='__main__':main()
