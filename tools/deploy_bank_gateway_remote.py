"""Install disabled Stripe gateway with guarded protected config and rollback.

Only operational configuration is written. The key is generated on the host and
never returned. Requires an inspected portal and a successful economy deployment.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from tools.deploy_stage4_economy import remote,ROOT

REMOTE=r'''
from pathlib import Path
from contextlib import closing
from datetime import datetime,timezone
import base64,hashlib,json,os,secrets,sqlite3,subprocess,sys,tempfile,time,urllib.request,urllib.error
p=json.load(sys.stdin);os.umask(0o077)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
def run(*args):return subprocess.run(args,capture_output=True,text=True,check=True,timeout=30).stdout.strip()
root=Path('/opt/tio-emulator');env=Path('/etc/tio-portal/portal.env');site=Path('/etc/nginx/sites-available/tireborn')
backup=Path(p['backup'])
assert (backup/'backup-manifest.json').is_file() and (backup/'reservation.sqlite3').is_file() and (backup/'website.dump').is_file(),'Missing full backup'
assert sha(env)==p['env_sha'] and sha(site)==p['site_sha'],'Operational configuration changed after inspection'
assert str(Path('/opt/tio-portal/current').resolve())==p['portal_release'],'Portal release changed'
for name,digest in p['runtime_sha'].items():assert sha(root/name)==digest,'Economy runtime revision changed'
assert not Path('/etc/tio-server/bank-api.env').exists(),'Bank already configured; inspect instead of replacing'
assert json.loads((root/'config/bank_economy.json').read_text())['provider']['enabled'] is False,'This installer does not activate payments'
assert run(str(root/'.venv-web/bin/python'),'-c','import flask,waitress;print("ok")')=='ok','Missing gateway runtime'
before_game=run('systemctl','show','tio-server','-p','MainPID','-p','NRestarts','-p','ActiveState')
unit=Path('/etc/systemd/system/tio-bank-api.service');snippet=Path('/etc/nginx/snippets/tio-bank.conf')
bankenv=Path('/etc/tio-server/bank-api.env');dropin=Path('/etc/systemd/system/tio-portal.service.d/bank-cache.conf')
paths=(env,site,unit,snippet,bankenv,dropin)
saved={path:(path.read_bytes(),path.stat().st_mode&0o777) if path.exists() else None for path in paths}
rollback=Path(tempfile.mkdtemp(prefix='tio-bank-config-backup-',dir='/root'))
for i,(path,value) in enumerate(saved.items()):
 if value:(rollback/str(i)).write_bytes(value[0])
key=secrets.token_urlsafe(48)
def write(path,raw,mode):
 path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_name(path.name+'.bank-new')
 with temporary.open('xb') as out:out.write(raw)
 temporary.chmod(mode);temporary.replace(path)
try:
 write(bankenv,('TIO_CONFIG=/etc/tio-server/server.toml\nBANK_SERVICE_KEY='+key+'\n').encode(),0o600)
 write(env,saved[env][0].rstrip(b'\n')+('\nBANK_GATEWAY_URL=http://127.0.0.1:8082\nBANK_SERVICE_KEY='+key+'\n').encode(),saved[env][1])
 write(unit,base64.b64decode(p['unit'],validate=True),0o644)
 write(snippet,base64.b64decode(p['snippet'],validate=True),0o644)
 text=saved[site][0].decode();marker='    include /etc/nginx/snippets/tio-updates.conf;'
 assert text.count(marker)==1 and 'tio-bank.conf' not in text,'Unexpected TLS vhost structure'
 write(site,text.replace(marker,marker+'\n    include /etc/nginx/snippets/tio-bank.conf;').encode(),saved[site][1])
 write(dropin,b'[Service]\nReadWritePaths=-/opt/tio-portal/current/.next-bank-release/cache\n',0o644)
 run('nginx','-t');run('systemctl','daemon-reload');run('systemctl','enable','--now','tio-bank-api')
 def request(path,data,authorized=True):
  req=urllib.request.Request('http://127.0.0.1:8082'+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+key} if authorized else {})})
  try:
   with urllib.request.urlopen(req,timeout=3) as res:return res.status,json.load(res)
  except urllib.error.HTTPError as error:return error.code,json.load(error)
 for attempt in range(20):
  try:status,body=request('/v1/bank/status',dict(username=p['qa_login'],slot=1))
  except (OSError,urllib.error.URLError):time.sleep(.25);continue
  break
 assert status==200 and body['configured'] is False and body['canPurchase'] is False,'Disabled bank status failed'
 assert (body['currency'],body['minorUnitsPerGold'],body['minimumGold'])==('eur',1,50),'Approved tariff mismatch'
 assert request('/v1/bank/status',dict(username=p['qa_login'],slot=1),False)[0]==401,'Unauthenticated gateway admitted'
 assert request('/v1/bank/orders',dict(username=p['qa_login'],slot=1,gold=50,requestId='disabled_hosted_probe_0001'))==(503,dict(error='bank_not_configured')),'Disabled gateway created checkout'
 run('systemctl','reload','nginx')
 assert run('systemctl','show','tio-server','-p','MainPID','-p','NRestarts','-p','ActiveState')==before_game,'Gameplay service changed'
except BaseException:
 subprocess.run(['systemctl','stop','tio-bank-api'],capture_output=True)
 subprocess.run(['systemctl','disable','tio-bank-api'],capture_output=True)
 for path,value in saved.items():
  if value:write(path,value[0],value[1])
  elif path.exists():path.unlink()
 subprocess.run(['systemctl','daemon-reload'],capture_output=True)
 subprocess.run(['nginx','-t'],capture_output=True)
 subprocess.run(['systemctl','reload','nginx'],capture_output=True)
 raise
print(json.dumps(dict(installed_utc=datetime.now(timezone.utc).isoformat(),backup=str(backup),configuration_backup=str(rollback),
 gateway=run('systemctl','show','tio-bank-api','-p','MainPID','-p','ActiveState','-p','NRestarts'),
 tariff=dict(currency='eur',minor_units_per_gold=1,minimum_gold=50),merchant_enabled=False,
 private_authorization_checked=True,disabled_checkout_checked=True,game_service_unchanged=True,
 bank_key_returned=False,local_player_data_uploaded=False,portal_restart_required=True)))
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--economy-deployment',type=Path,required=True)
    parser.add_argument('--qa-login',required=True)
    args=parser.parse_args();folder=args.folder.resolve();target=folder/'gateway-deployment.json'
    if target.exists():parser.error('Preserve the prior deployment report')
    inspection=json.loads((folder/'remote-inspection.json').read_text())
    backup=json.loads((folder/'predeployment-backup.json').read_text())
    deployment=json.loads(args.economy_deployment.read_text())
    if not deployment.get('source_parity'):raise ValueError('Successful economy deployment required')
    required=('server/bank_gateway.py','tio/bank_economy.py','config/bank_economy.json')
    sources=deployment['source_sha256']
    site=inspection['nginx']['/etc/nginx/sites-available/tireborn']
    payload=dict(backup=backup['backup'],env_sha=inspection['portal_env_sha'],site_sha=hashlib.sha256(site.encode()).hexdigest(),
        portal_release=inspection['portal_release'],runtime_sha={n:sources[n] for n in required},qa_login=args.qa_login,
        unit=base64.b64encode((ROOT/'deploy/tio-bank-api.service').read_bytes()).decode(),
        snippet=base64.b64encode((ROOT/'deploy/tio-bank.nginx.inc').read_bytes()).decode())
    result=remote(REMOTE,payload);target.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':main()
