"""Publish only reviewed localization code/resources against the actual host.

Requires the existing verified online database/code/config backup. Player files
never enter the package. Default inspection performs no writes on the host.
"""
from pathlib import Path
import argparse,base64,hashlib,json,subprocess

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/english-localization'
REMOTE=r'''
from pathlib import Path
import base64,hashlib,json,os,sqlite3,subprocess,tempfile,time
from contextlib import closing
GAME=Path('/opt/tio-emulator');LIVE=Path('/var/www/tio-client/updates')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def regular(p):
 if p.is_symlink() or any(x.is_symlink() for x in p.parents):raise ValueError('Linked publication path')
 return p
def current(p):return regular(p).read_bytes() if p.exists() else None
def atomic(p,raw):
 regular(p);p.parent.mkdir(parents=True,exist_ok=True)
 fd,name=tempfile.mkstemp(prefix='.english-',dir=p.parent)
 try:
  with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
  os.chmod(name,0o644);os.replace(name,p)
 finally:
  if os.path.exists(name):os.unlink(name)
def account_ids():
 with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
  if db.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise ValueError('Hosted SQLite integrity failed')
  return {r[0] for r in db.execute('SELECT login FROM accounts')}
def service(name):
 out=subprocess.check_output(['systemctl','show',name,'-p','MainPID','-p','ActiveState'],text=True)
 return dict(x.split('=',1) for x in out.splitlines())
before=base64.b64decode(request['before_manifest']);after=base64.b64decode(request['after_manifest'])
if current(LIVE/'manifest.json')!=before:raise ValueError('Actual manifest changed after inspection')
a,b=json.loads(before),json.loads(after)
if a['version']!='2026.10.12.4' or b['version']!='2026.10.13.1' or a['schema']!=b['schema']:raise ValueError('Unexpected client versions')
old={r['path']:r for r in a['files']};new={r['path']:r for r in b['files']}
allowed={'base/english.lng'}|{'base/locales/'+locale+'/'+name for locale in ('en','ru') for name in ('battlelog.xml','quest/00000.xml','quest/tut_1000.xml','rules.txt','help.txt')}
delta={n for n in set(old)|set(new) if old.get(n)!=new.get(n)}
if delta!=allowed or not set(old)<=set(new) or len(new)!=len(b['files']):raise ValueError('Client change exceeds localization scope')
expected={'server/'+name+'.py' for name in ('tls','multi','assault_public','clan_gameplay','bank_gameplay','contracts_service','economy_runtime','mine_arena','social_commands','services_runtime','tutorial_arena','team_ranked','wager_arena')}|{'tools/loopback_exchange.py','tio/protocol/transport.py','tio/protocol/system_message.py','tio/protocol/chat.py','tio/localization.py','config/english_translations.json'}
if {r['path'] for r in request['code']}!=expected or len(request['code'])!=len(expected):raise ValueError('Unexpected server package scope')
prior={};code={}
for r in request['code']:
 raw=base64.b64decode(r['data']);path=GAME/r['path'];previous=current(path)
 if sha(raw)!=r['sha256'] or len(raw)!=r['size'] or (sha(previous) if previous is not None else None)!=r['previous_sha256']:raise ValueError('Reviewed code identity differs: '+r['path'])
 if path.suffix=='.py':compile(raw,r['path'],'exec')
 else:json.loads(raw)
 prior[path]=previous;code[path]=raw
blobs={}
for name in delta:
 record=new[name];raw=base64.b64decode(request['blobs'][record['sha256']])
 if record.get('seed') or sha(raw)!=record['sha256'] or len(raw)!=record['size']:raise ValueError('Reviewed resource differs')
 blobs[record['sha256']]=raw
states={name:service(name) for name in ('tio-server','tio-game-api','tio-portal','nginx')}
if any(s['ActiveState']!='active' for s in states.values()):raise ValueError('Services must be active before publication')
ids=account_ids();configs={str(p):sha(regular(p).read_bytes()) for p in (Path('/etc/tio-server/server.toml'),Path('/etc/tio-portal/portal.env'))}
report=dict(action=request['action'],before_version=a['version'],version=b['version'],accounts_before=len(ids),services_before=states,changed_resources=sorted(delta),changed_code=sorted(expected))
if request['action']=='apply':
 backup=regular(Path(request['backup']))
 if backup.parent!=Path('/root') or not backup.name.startswith('tio-before-launcher-'):raise ValueError('Fresh verified private backup required')
 receipt=json.loads((backup/'backup-manifest.json').read_bytes())
 if receipt['sqlite_integrity']!='ok' or receipt.get('website_full_isolated_restore') is not True or time.time()-backup.stat().st_mtime>3600:raise ValueError('Backup is not fresh/verified')
 if current(backup/'client-manifest.json')!=before:raise ValueError('Backup manifest differs from exact prepublication client')
 with closing(sqlite3.connect((backup/'reservation.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
  if not ids<={r[0] for r in db.execute('SELECT login FROM accounts')}:raise ValueError('Backup does not preserve current accounts')
 journal=backup/'english-publication.json';atomic(journal,json.dumps(report,indent=2).encode())
 try:
  subprocess.run(['systemctl','stop','tio-server'],check=True,timeout=60)
  if current(LIVE/'manifest.json')!=before:raise ValueError('Client changed during service shutdown')
  for path,raw in code.items():
   if current(path)!=prior[path]:raise ValueError('Code changed before replacement')
   atomic(path,raw)
  subprocess.run(['systemctl','start','tio-server'],check=True,timeout=60)
  for _ in range(25):
   now=service('tio-server')
   if now['ActiveState']=='active' and now['MainPID']!='0':break
   time.sleep(.2)
  else:raise ValueError('Updated service failed to start')
  time.sleep(2)
  if service('tio-server')['ActiveState']!='active':raise ValueError('Updated service failed preflight')
  for digest,raw in blobs.items():
   target=LIVE/'blobs'/digest
   if current(target) is None:atomic(target,raw)
   elif current(target)!=raw:raise ValueError('Immutable blob differs')
  atomic(LIVE/'manifest.json',after)
  after_ids=account_ids()
  if not ids<=after_ids or any(sha(Path(name).read_bytes())!=digest for name,digest in configs.items()):raise ValueError('Accounts/configuration preservation failed')
  report.update(passed=True,backup=str(backup),accounts_after=len(after_ids),services_after={name:service(name) for name in states},manifest_sha256=sha(after),server_restarts=1)
  for name in ('tio-game-api','tio-portal','nginx'):
   if states[name]!=report['services_after'][name]:raise ValueError('Unrelated service changed')
  atomic(journal,json.dumps(report,indent=2).encode())
 except Exception:
  subprocess.run(['systemctl','stop','tio-server'],check=True,timeout=60)
  for path,raw in prior.items():
   if raw is not None:atomic(path,raw)
   elif current(path)==code[path]:path.unlink()
  if current(LIVE/'manifest.json')==after:atomic(LIVE/'manifest.json',before)
  subprocess.run(['systemctl','start','tio-server'],check=True,timeout=60)
  raise
print(json.dumps(report))
'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');p.add_argument('--backup-report',type=Path);a=p.parse_args()
    records=json.loads((REPORT/'server-package.json').read_bytes())['files'];request={'action':'apply' if a.apply else 'inspect','code':[]}
    for r in records:request['code'].append(dict(r,data=base64.b64encode((REPORT/'runtime-candidate'/r['path']).read_bytes()).decode()))
    request['before_manifest']=base64.b64encode((REPORT/'baseline-manifest.json').read_bytes()).decode()
    request['after_manifest']=base64.b64encode((REPORT/'client-release/manifest.json').read_bytes()).decode()
    request['blobs']={path.name:base64.b64encode(path.read_bytes()).decode() for path in (REPORT/'client-release/blobs').iterdir()}
    if a.apply:
        if not a.backup_report:p.error('--backup-report is required for publication')
        request['backup']=json.loads(a.backup_report.read_bytes())['backup']
    source='request='+repr(request)+'\n'+REMOTE
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=15','root@185.184.42.88','python3 -'],input=source,encoding='utf-8',capture_output=True)
    if result.returncode:raise RuntimeError('Localization publication failed: '+result.stderr.strip().splitlines()[-1])
    data=json.loads(result.stdout);(REPORT/('deployment-'+request['action']+'.json')).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8');print(json.dumps(data))
if __name__=='__main__':main()
