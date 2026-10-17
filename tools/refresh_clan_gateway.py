"""Load the deployed crest API, retaining protected keys and game identity."""
import argparse,json
from pathlib import Path
from tools.deploy_stage4_economy import remote

REMOTE=r'''
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,subprocess,sys,time,urllib.request,urllib.error
p=json.load(sys.stdin)
def run(*args):return subprocess.run(args,capture_output=True,text=True,check=True,timeout=30).stdout.strip()
def state(name):return run('systemctl','show',name,'-p','MainPID','-p','ActiveState','-p','NRestarts')
source=Path('/opt/tio-emulator/server/bank_gateway.py')
if hashlib.sha256(source.read_bytes()).hexdigest()!=p['sha256']:raise RuntimeError('Gateway deployment differs')
game=state('tio-server');portal=state('tio-portal')
protected=Path('/etc/tio-server/bank-api.env');before=hashlib.sha256(protected.read_bytes()).hexdigest()
run('systemctl','restart','tio-bank-api')
status=None
for attempt in range(20):
 try:
  urllib.request.urlopen('http://127.0.0.1:8082/v1/clan/crests/4294967295',timeout=2)
 except urllib.error.HTTPError as error:status=error.code;break
 except urllib.error.URLError:time.sleep(.25)
if status!=401:raise RuntimeError('Private gateway authorization check failed')
if game!=state('tio-server') or portal!=state('tio-portal'):raise RuntimeError('Unrelated service changed')
if before!=hashlib.sha256(protected.read_bytes()).hexdigest():raise RuntimeError('Protected configuration changed')
print(json.dumps(dict(passed=True,timestamp_utc=datetime.now(timezone.utc).isoformat(),private_authorization_status=status,
 gateway=state('tio-bank-api'),game_unchanged=True,portal_unchanged=True,protected_configuration_unchanged=True)))
'''

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--deployment',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    args=p.parse_args()
    if args.report.exists():p.error('Preserve prior evidence')
    proof=json.loads(args.deployment.read_text())
    if not proof.get('source_parity'):raise ValueError('Actual deployed source parity required')
    result=remote(REMOTE,dict(sha256=proof['source_sha256']['server/bank_gateway.py']))
    with args.report.open('x',encoding='utf8') as output:json.dump(result,output,indent=2)
    print(json.dumps(result))

if __name__=='__main__':main()
