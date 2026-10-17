"""Activate an already deployed gateway revision with private config backup."""
import argparse,json
from tools.deploy_gameplay_completion import ROOT
from tools.deploy_stage4_economy import remote

CODE=r'''
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,shutil,subprocess,sys,tempfile,time,urllib.request,urllib.error
os.umask(0o077);p=json.load(sys.stdin)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
source=Path('/opt/tio-emulator/server/bank_gateway.py')
if sha(source)!=p['sha256']:raise RuntimeError('Deployed gateway source differs')
env=Path('/etc/tio-server/bank-api.env');config=Path('/etc/tio-server/server.toml')
guards={str(path):sha(path) for path in (env,config)}
backup=Path(tempfile.mkdtemp(prefix='tio-before-bank-gateway-',dir='/root'))
shutil.copy2(env,backup/'bank-api.env')
unit=subprocess.check_output(['systemctl','cat','tio-bank-api'],text=True)
(backup/'tio-bank-api.service').write_text(unit)
subprocess.run(['systemctl','restart','tio-bank-api'],capture_output=True,check=True,timeout=30)
verified=False
for attempt in range(30):
 try:
  req=urllib.request.Request('http://127.0.0.1:8082/v2/services/status',data=b'{}',headers={'Content-Type':'application/json'})
  urllib.request.urlopen(req,timeout=2)
 except urllib.error.HTTPError as error:
  if error.code==401:verified=True;break
 except OSError:pass
 time.sleep(.2)
if not verified:raise RuntimeError('Private gateway did not become ready')
if guards!={str(path):sha(path) for path in (env,config)}:raise RuntimeError('Protected settings changed')
state=subprocess.check_output(['systemctl','show','tio-bank-api','-p','MainPID','-p','NRestarts','-p','ExecMainStatus','-p','ActiveState'],text=True).strip()
if 'ActiveState=active' not in state or 'ExecMainStatus=0' not in state:raise RuntimeError('Gateway service unhealthy')
print(json.dumps(dict(passed=True,utc=datetime.now(timezone.utc).isoformat(),backup=str(backup),service=state,
 source_parity=sha(source)==p['sha256'],protected_configuration_unchanged=True,unauthenticated_status=401,stripe_configuration_changed=False)))
'''

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--folder',required=True)
    args=parser.parse_args();folder=(ROOT/args.folder).resolve()
    if not folder.is_relative_to(ROOT/'reports/gameplay-completion'):raise ValueError('Scoped release required')
    target=folder/'gateway-restart.json'
    if target.exists():raise ValueError('Preserve previous gateway restart report')
    deployed=json.loads((folder/'deployment.json').read_text())
    if not deployed['source_parity'] or not deployed['accounts_preserved']:raise ValueError('Verified deployment required')
    manifest=json.loads((folder/'candidate-manifest.json').read_text())
    result=remote(CODE,dict(sha256=manifest['files']['server/bank_gateway.py']['sha256']))
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))

if __name__=='__main__':main()
