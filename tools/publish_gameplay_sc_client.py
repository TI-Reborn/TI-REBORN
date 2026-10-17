"""Build/review the exact SC F8 client, then explicitly publish only silver.dll.

prepare is read-only remotely. publish backs up client/launcher/code/config files,
uses immutable blobs plus a guarded atomic manifest, and never opens a database,
uploads player data, changes launcher executables or restarts a service.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import uuid

from tools.deploy_stage4_economy import ROOT, remote
from deploy.client_sc_auction import patch, patch_plan, BASE_SHA, BASE_BYTES

VERSION = '2026.10.08.4'
PREVIOUS_VERSION = '2026.10.08.3'
CANDIDATE_SHA = '7ae830b5e8db3249915a3c10b9f45cf23ecac64984b95d4c02b7da326ad7a43b'
CANDIDATE_BYTES = BASE_BYTES + 8192
ORIGIN = 'https://185.184.42.88/updates/'
SOURCES = ('deploy/client_sc_auction.py', 'tio/protocol/sc_auction_view.py',
           'tio/protocol/sc_auction.py', 'tools/verify_sc_view_native.py')


def sha(raw): return hashlib.sha256(raw).hexdigest()


def checked_manifest(raw, *, version):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 4*1024*1024:
        raise ValueError('Manifest exceeds reviewed bound')
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get('schema') != 1 or value.get('version') != version:
        raise ValueError('Exact client source version required')
    files = value.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= 10000:
        raise ValueError('Invalid client file catalogue')
    paths = set()
    for row in files:
        if not isinstance(row, dict) or not {'path','size','sha256'} <= set(row) <= {'path','size','sha256','seed'}:
            raise ValueError('Unknown file descriptor')
        name = row['path']
        if (not isinstance(name, str) or not name or len(name) > 256 or chr(92) in name
                or any(ord(c)<32 or c==':' for c in name) or name != str(PurePosixPath(name))
                or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or name in paths):
            raise ValueError('Unsafe or duplicate client path')
        paths.add(name)
        if type(row['size']) is not int or not 0 <= row['size'] <= 64*1024*1024:
            raise ValueError('Invalid client blob size')
        if not isinstance(row['sha256'], str) or re.fullmatch('[a-f0-9]{64}', row['sha256']) is None:
            raise ValueError('Invalid immutable blob identity')
        if 'seed' in row and type(row['seed']) is not bool:
            raise ValueError('Invalid seed flag')
    dll = next((r for r in files if r['path'] == 'silver.dll'), None)
    expected = (BASE_SHA,BASE_BYTES) if version == PREVIOUS_VERSION else (CANDIDATE_SHA,CANDIDATE_BYTES)
    if dll is None or (dll['sha256'],dll['size']) != expected or dll.get('seed',False):
        raise ValueError('Exact bounded DLL release required')
    return value


def new_manifest(old):
    value = checked_manifest(old, version=PREVIOUS_VERSION)
    value['version'] = VERSION
    next(r for r in value['files'] if r['path'] == 'silver.dll').update(
        sha256=CANDIDATE_SHA, size=CANDIDATE_BYTES, seed=False)
    return (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8')


def transition(old, new):
    a = checked_manifest(old, version=PREVIOUS_VERSION)
    b = checked_manifest(new, version=VERSION)
    if set(a) != set(b) or any(a[k] != b[k] for k in a if k not in ('version','files')):
        raise ValueError('Unrelated manifest metadata changed')
    if len(a['files']) != len(b['files']) or [r['path'] for r in a['files']] != [r['path'] for r in b['files']]:
        raise ValueError('Unrelated client catalogue changed')
    changes = [y['path'] for x,y in zip(a['files'],b['files']) if x != y]
    if changes != ['silver.dll']:
        raise ValueError('Only the reviewed SC DLL can change')
    old_dll = next(r for r in a['files'] if r['path'] == 'silver.dll')
    new_dll = next(r for r in b['files'] if r['path'] == 'silver.dll')
    if new_dll != dict(old_dll, sha256=CANDIDATE_SHA, size=CANDIDATE_BYTES, seed=False):
        raise ValueError('Unexpected DLL descriptor fields')
    return changes


def fetch(path, maximum):
    context = ssl.create_default_context(); context.keylog_filename = None
    url = ORIGIN + path
    request = urllib.request.Request(url, headers={'Cache-Control':'no-cache','Pragma':'no-cache'})
    with urllib.request.urlopen(request, context=context, timeout=45) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('Trusted HTTPS endpoint changed')
        raw = response.read(maximum+1)
    if len(raw) > maximum:
        raise ValueError('Trusted HTTPS response exceeds bound')
    return raw


# Self-contained stdlib code sent through reviewed SSH stdin. No SQL/DB or
# local save is accessed. Tests execute the same functions against temporary
# client files with isolated lock/service handles, never against the VPS.
REMOTE = r'''
from datetime import datetime,timezone
from pathlib import Path,PurePosixPath
import base64,hashlib,json,os,re,shutil,subprocess,tarfile,tempfile
LIVE=Path('/var/www/tio-client/updates');DOWNLOADS=Path('/var/www/tio-client/downloads')
GAME=Path('/opt/tio-emulator');PRIVATE=Path('/root')
CONFIGS=(Path('/etc/tio-server/server.toml'),Path('/etc/systemd/system/tio-server.service'),Path('/etc/nginx/snippets/tio-updates.conf'))
BASE='2c472913b2f1e9f5171b89518cba692b624d1d194c70024999baf3024da9794f';BASE_BYTES=7753216
CANDIDATE='7ae830b5e8db3249915a3c10b9f45cf23ecac64984b95d4c02b7da326ad7a43b';CANDIDATE_BYTES=7761408
def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(path):
 if path.is_symlink() or any(p.is_symlink() for p in path.parents):raise ValueError('Publication file must be regular')
 if not path.is_file():return None
 value=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):value.update(block)
 return dict(sha256=value.hexdigest(),size=path.stat().st_size)
def service():
 out=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True,timeout=30)
 value=dict(line.split('=',1) for line in out.splitlines() if '=' in line)
 if value.get('ActiveState')!='active':raise RuntimeError('Hosted game service must remain active')
 return value
def guards():
 launchers={name:digest(DOWNLOADS/name) for name in ('TIO-Launcher.exe','TIO-Launcher-0.1.4.exe')}
 if any(v is None for v in launchers.values()):raise RuntimeError('Published launcher missing')
 names=('tio/protocol/sc_auction_view.py','tio/protocol/sc_auction.py','tio/sc_auction.py','server/private_market.py','server/economy_runtime.py','tools/loopback_exchange.py','config/sc_auction.json')
 return dict(launchers=launchers,service=service(),runtime={n:digest(GAME/n) for n in names},configuration={str(p):digest(p) for p in CONFIGS})
def catalogue(raw,version):
 if not 1<=len(raw)<=4*1024*1024:raise ValueError('Manifest too large')
 value=json.loads(raw)
 if value.get('schema')!=1 or value.get('version')!=version:raise ValueError('Client source version changed')
 paths=set();files=value['files']
 if not isinstance(files,list) or not 1<=len(files)<=10000:raise ValueError('Invalid client file count')
 for row in files:
  if not isinstance(row,dict) or not {'path','size','sha256'}<=set(row)<={'path','size','sha256','seed'}:raise ValueError('Invalid descriptor')
  name=row['path']
  if not isinstance(name,str) or not name or len(name)>256 or chr(92) in name or any(ord(c)<32 or c==':' for c in name) or name!=str(PurePosixPath(name)) or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or name in paths:raise ValueError('Invalid client path')
  paths.add(name)
  if type(row['size'])is not int or not 0<=row['size']<=64*1024*1024 or not isinstance(row['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',row['sha256']):raise ValueError('Invalid blob')
  if 'seed'in row and type(row['seed'])is not bool:raise ValueError('Invalid seed flag')
 dll=next((r for r in files if r['path']=='silver.dll'),None)
 expected=(BASE,BASE_BYTES) if version=='2026.10.08.3' else (CANDIDATE,CANDIDATE_BYTES)
 if dll is None or (dll['sha256'],dll['size'])!=expected or dll.get('seed',False):raise ValueError('Unexpected DLL base')
 return value
def blobs(value):
 seen={}
 for row in value['files']:
  key=row['sha256']
  if key not in seen:seen[key]=digest(LIVE/'blobs'/key)
  if seen[key]!=dict(sha256=key,size=row['size']):raise RuntimeError('Published client blob corrupt or missing')
 return dict(verified_records=len(value['files']),verified_unique_blobs=len(seen))
def inspect():
 old=(LIVE/'manifest.json').read_bytes();version=json.loads(old).get('version')
 if version not in ('2026.10.08.3','2026.10.08.4'):raise RuntimeError('Unexpected live release version')
 a=catalogue(old,version)
 return dict(manifest=base64.b64encode(old).decode(),manifest_sha256=sha(old),version=a['version'],blobs=blobs(a),guards=guards(),
  database_opened=False,local_player_data_accessed=False,timestamp_utc=datetime.now(timezone.utc).isoformat())
def private_json(path,value):
 fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(value,f,indent=2);f.write(chr(10));f.flush();os.fsync(f.fileno())
def atomic(raw,target):
 fd,name=tempfile.mkstemp(prefix='.sc-client-',dir=target.parent);pending=Path(name)
 try:
  with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  pending.chmod(0o644);pending.replace(target)
 finally:pending.unlink(missing_ok=True)
def backup(before,old,new,op):
 saved=Path(tempfile.mkdtemp(prefix='tio-before-sc-client-',dir=PRIVATE));saved.chmod(0o700)
 (saved/'manifest.json').write_bytes(old);(saved/'new-manifest.json').write_bytes(new);(saved/'silver.dll').write_bytes(before)
 for name in ('TIO-Launcher.exe','TIO-Launcher-0.1.4.exe'):shutil.copy2(DOWNLOADS/name,saved/name)
 with tarfile.open(saved/'previous-code-config.tar.gz','w:gz') as archive:
  for directory,pattern in (('tio','*.py'),('server','*.py'),('tools','*.py'),('config','*.json')):
   for path in sorted((GAME/directory).rglob(pattern)):
    if path.is_symlink():raise RuntimeError('Unreviewed runtime link')
    archive.add(path,arcname='game/'+path.relative_to(GAME).as_posix())
  for path in CONFIGS:
   if path.is_file():archive.add(path,arcname='operational/'+path.name)
 private_json(saved/'prepared.json',dict(operation=op,before_manifest=sha(old),after_manifest=sha(new),candidate=CANDIDATE,
  database_opened=False,local_player_data_uploaded=False))
 return saved
def publish(p):
 import fcntl
 op=p['operation']
 if not isinstance(op,str) or not re.fullmatch('[a-f0-9]{32}',op):raise ValueError('Invalid reviewed operation')
 old=base64.b64decode(p['before_manifest'],validate=True);new=base64.b64decode(p['after_manifest'],validate=True)
 raw=base64.b64decode(p['candidate'],validate=True)
 a,b=catalogue(old,'2026.10.08.3'),catalogue(new,'2026.10.08.4')
 if set(a)!=set(b) or any(a[k]!=b[k] for k in a if k not in ('files','version')):raise ValueError('Unexpected manifest metadata')
 if len(a['files'])!=len(b['files']) or [r['path'] for r in a['files']]!=[r['path'] for r in b['files']]:raise ValueError('Unexpected client paths')
 if [y['path'] for x,y in zip(a['files'],b['files']) if x!=y]!=['silver.dll']:raise ValueError('Only SC DLL may change')
 prior=next(r for r in a['files'] if r['path']=='silver.dll');record=next(r for r in b['files'] if r['path']=='silver.dll')
 if record!=dict(prior,sha256=CANDIDATE,size=CANDIDATE_BYTES,seed=False):raise ValueError('Unexpected DLL descriptor')
 if len(raw)!=CANDIDATE_BYTES or sha(raw)!=CANDIDATE:raise ValueError('Candidate outside reviewed hash')
 with (PRIVATE/'.tio-gameplay-client.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  journal=PRIVATE/('tio-sc-client-'+op+'.json')
  if journal.exists():
   result=json.loads(journal.read_text());target=LIVE/'blobs'/CANDIDATE
   if result['manifest_sha256']!=sha(new) or (LIVE/'manifest.json').read_bytes()!=new or digest(target)!=dict(sha256=CANDIDATE,size=CANDIDATE_BYTES):raise RuntimeError('Prior SC publication no longer current')
   return dict(result,recovered_completed_publication=True)
  if (LIVE/'manifest.json').read_bytes()!=old:raise RuntimeError('Published manifest changed before SC release')
  before=(LIVE/'blobs'/BASE).read_bytes()
  if len(before)!=BASE_BYTES or sha(before)!=BASE:raise RuntimeError('Exact source DLL changed')
  plan=p['plan']
  if plan['previous_sha256']!=BASE or plan['updated_sha256']!=CANDIDATE or plan['appended_bytes']!=8192 or plan['existing_f6_f7_and_four_other_item_hooks_preserved']is not True or plan['all_stock_bd_builders_preserved']is not True or len(plan['changes'])!=4:raise ValueError('Unreviewed SC edit plan')
  allowed=set()
  for row in plan['changes']:
   at=row['offset'];x=bytes.fromhex(row['before_hex']);y=bytes.fromhex(row['after_hex'])
   if type(at)is not int or at<0 or len(x)!=len(y) or at+len(x)>len(before) or before[at:at+len(x)]!=x or raw[at:at+len(y)]!=y:raise ValueError('Invalid bounded edit')
   allowed.update(range(at,at+len(x)))
  if any(x!=y and i not in allowed for i,(x,y) in enumerate(zip(before,raw))):raise ValueError('Unrelated DLL bytes changed')
  blobs(a);state=guards()
  for name,expected in p['server_abi'].items():
   if name not in ('tio/protocol/sc_auction_view.py','tio/protocol/sc_auction.py') or state['runtime'].get(name) is None or state['runtime'][name]['sha256']!=expected:raise RuntimeError('Reviewed SC server ABI not deployed')
  if set(p['server_abi'])!={'tio/protocol/sc_auction_view.py','tio/protocol/sc_auction.py'}:raise ValueError('Missing deployed SC ABI guard')
  saved=backup(before,old,new,op);private_json(saved/'guards.json',state);committed=False
  try:
   if (LIVE/'manifest.json').read_bytes()!=old or guards()!=state:raise RuntimeError('Hosted client/runtime changed during backup')
   target=LIVE/'blobs'/CANDIDATE
   if target.exists():
    if target.read_bytes()!=raw:raise RuntimeError('Immutable SC blob already differs')
   else:atomic(raw,target)
   if (LIVE/'manifest.json').read_bytes()!=old or guards()!=state:raise RuntimeError('Hosted state changed before SC manifest commit')
   atomic(new,LIVE/'manifest.json');committed=True
   if (LIVE/'manifest.json').read_bytes()!=new or digest(target)!=dict(sha256=CANDIDATE,size=CANDIDATE_BYTES):raise RuntimeError('SC client parity failed')
   coverage=blobs(b)
   if guards()!=state:raise RuntimeError('Hosted state changed during SC publication')
   result=dict(passed=True,operation=op,version='2026.10.08.4',backup=str(saved),source_sha256=BASE,sha256=CANDIDATE,size=CANDIDATE_BYTES,
    changed=['silver.dll'],manifest_sha256=sha(new),timestamp_utc=datetime.now(timezone.utc).isoformat(),server_restarted=False,
    database_opened=False,database_written=False,local_player_data_uploaded=False,launchers_preserved=True,service_unchanged=True,
    other_client_files_preserved=True,seed_records_preserved=True,blob_coverage=coverage,guards=state)
   private_json(saved/'publication.json',result);private_json(journal,result);return result
  except BaseException:
   restored=False
   if committed and (LIVE/'manifest.json').read_bytes()==new:atomic(old,LIVE/'manifest.json');restored=True
   private_json(saved/'rollback.json',dict(manifest_restored=restored,current_manifest_sha256=sha((LIVE/'manifest.json').read_bytes()),
    immutable_unreferenced_blob_retained=True,database_opened=False,server_restarted=False))
   raise
'''
READ = REMOTE + "\nprint(json.dumps(inspect()))\n"
PUBLISH = REMOTE + "\nimport sys\nprint(json.dumps(publish(json.load(sys.stdin))))\n"


def folder_checked(folder):
    value = Path(folder).resolve()
    if not value.is_relative_to(ROOT/'reports/gameplay-completion'):
        raise ValueError('Expected bounded gameplay report folder')
    return value


def sources(): return {n:sha((ROOT/n).read_bytes()) for n in SOURCES}


def prepare(folder):
    folder = folder_checked(folder); folder.mkdir(parents=True, exist_ok=True)
    if (folder/'client').exists():
        raise ValueError('Preserve existing client candidate/evidence')
    observation = remote(READ, {})
    old = base64.b64decode(observation['manifest'], validate=True)
    if sha(old) != observation['manifest_sha256'] or fetch('manifest.json',4*1024*1024) != old:
        raise ValueError('SSH and trusted HTTPS manifest differ')
    checked_manifest(old, version=PREVIOUS_VERSION)
    source = fetch('blobs/'+BASE_SHA, BASE_BYTES)
    if len(source) != BASE_BYTES or sha(source) != BASE_SHA:
        raise ValueError('Trusted HTTPS exact source DLL differs')
    candidate = patch(source)
    if len(candidate) != CANDIDATE_BYTES or sha(candidate) != CANDIDATE_SHA or patch(candidate) != candidate:
        raise ValueError('F8 candidate outside reviewed release')
    plan = patch_plan(source,candidate); new = new_manifest(old); transition(old,new)
    source_hashes = sources()
    native = subprocess.run([sys.executable,str(ROOT/'tools/verify_sc_view_native.py')],cwd=ROOT,capture_output=True,text=True,timeout=120)
    if native.returncode:
        raise RuntimeError('Native SC verification failed; no candidate installed')
    proof = json.loads((ROOT/'evidence/sc_view_native.json').read_text(encoding='utf-8'))
    if proof.get('status') != 'PASS' or proof['patch_plan'] != plan or len(proof['proof']) != 2:
        raise ValueError('Native SC candidate proof differs')
    checks = subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_sc_auction_view.py','-v'],cwd=ROOT,capture_output=True,text=True,timeout=120)
    if checks.returncode or sources() != source_hashes:
        raise RuntimeError('SC codec/native tests failed or reviewed source changed')
    if base64.b64decode(remote(READ,{})['manifest'],validate=True) != old or fetch('manifest.json',4*1024*1024) != old:
        raise RuntimeError('Client source changed during candidate verification')
    with tempfile.TemporaryDirectory(prefix='sc-client-build-',dir=folder) as temporary:
        stage=Path(temporary)/'client';(stage/'source').mkdir(parents=True);(stage/'candidate').mkdir()
        (stage/'source/silver.dll').write_bytes(source);(stage/'candidate/silver.dll').write_bytes(candidate)
        (stage/'previous-manifest.json').write_bytes(old);(stage/'manifest.json').write_bytes(new)
        (stage/'remote-inspection.json').write_text(json.dumps(observation,indent=2)+'\n',encoding='utf-8')
        (stage/'native-proof.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
        (stage/'native-tests.txt').write_text(checks.stdout+checks.stderr,encoding='utf-8')
        release=dict(passed=True,operation=uuid.uuid4().hex,version=VERSION,previous_version=PREVIOUS_VERSION,
            source_sha256=BASE_SHA,source_bytes=BASE_BYTES,candidate_sha256=CANDIDATE_SHA,candidate_bytes=CANDIDATE_BYTES,
            before_manifest_sha256=sha(old),manifest_sha256=sha(new),native_proof_sha256=sha((stage/'native-proof.json').read_bytes()),
            source_hashes=source_hashes,patch_plan=plan,changed=['silver.dll'],trusted_https=True,prepared_utc=datetime.now(timezone.utc).isoformat(),
            published=False,graphical_acceptance_complete=False,database_opened=False,local_player_data_uploaded=False,
            preserved_records=len(json.loads(old)['files'])-1,server_abi={n:source_hashes[n] for n in SOURCES if n.startswith('tio/protocol/')},
            publish_command=f'python -m tools.publish_gameplay_sc_client publish --folder "{folder.relative_to(ROOT)}" --version {VERSION}')
        (stage/'release.json').write_text(json.dumps(release,indent=2)+'\n',encoding='utf-8')
        stage.replace(folder/'client')
    return release


def reviewed(folder):
    folder=folder_checked(folder);client=folder/'client'
    release=json.loads((client/'release.json').read_text(encoding='utf-8'))
    old=(client/'previous-manifest.json').read_bytes();new=(client/'manifest.json').read_bytes()
    source=(client/'source/silver.dll').read_bytes();candidate=(client/'candidate/silver.dll').read_bytes()
    if (release.get('passed') is not True or release['version']!=VERSION or release['previous_version']!=PREVIOUS_VERSION
            or release['source_sha256']!=BASE_SHA or release['source_bytes']!=BASE_BYTES
            or release['candidate_sha256']!=CANDIDATE_SHA or release['candidate_bytes']!=CANDIDATE_BYTES
            or release['source_hashes']!=sources() or release['before_manifest_sha256']!=sha(old) or release['manifest_sha256']!=sha(new)
            or sha(source)!=BASE_SHA or len(source)!=BASE_BYTES or sha(candidate)!=CANDIDATE_SHA or len(candidate)!=CANDIDATE_BYTES
            or patch(source)!=candidate or patch(candidate)!=candidate or patch_plan(source,candidate)!=release['patch_plan']):
        raise ValueError('Reviewed SC candidate/source/manifest changed')
    if release['server_abi']!={n:release['source_hashes'][n] for n in SOURCES if n.startswith('tio/protocol/')}:
        raise ValueError('Reviewed server ABI guard changed')
    transition(old,new)
    proof_raw=(client/'native-proof.json').read_bytes();proof=json.loads(proof_raw)
    if sha(proof_raw)!=release['native_proof_sha256'] or proof['status']!='PASS' or proof['patch_plan']!=release['patch_plan']:
        raise ValueError('Reviewed native proof changed')
    return release,old,new,candidate


def verify(folder):
    release,_,new,_=reviewed(folder)
    if fetch('manifest.json',4*1024*1024)!=new or sha(fetch('blobs/'+CANDIDATE_SHA,CANDIDATE_BYTES))!=CANDIDATE_SHA:
        raise ValueError('Trusted HTTPS published SC release differs')
    result=dict(passed=True,trusted_https=True,version=VERSION,origin=ORIGIN,manifest_sha256=sha(new),silver_sha256=CANDIDATE_SHA,
        database_opened=False,installed_client_changed=False,verified_utc=datetime.now(timezone.utc).isoformat())
    (folder_checked(folder)/'client/https-verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


def publish(folder):
    folder=folder_checked(folder)
    if (folder/'client/publication.json').exists():
        raise ValueError('Preserve publication evidence; use verify')
    release,old,new,candidate=reviewed(folder)
    for name in ('validation.json','hosted-economy.json'):
        if json.loads((folder/name).read_text(encoding='utf-8')).get('passed') is not True:
            raise ValueError('Server validation and hosted economy QA required before client publication')
    observation=remote(READ,{})
    current=base64.b64decode(observation['manifest'],validate=True)
    if current not in (old,new) or fetch('manifest.json',4*1024*1024)!=current:
        raise ValueError('Exact current published client baseline changed')
    result=remote(PUBLISH,dict(operation=release['operation'],before_manifest=base64.b64encode(old).decode(),
        after_manifest=base64.b64encode(new).decode(),candidate=base64.b64encode(candidate).decode(),
        plan=release['patch_plan'],server_abi=release['server_abi']))
    with (folder/'client/publication.json').open('x',encoding='utf-8') as output:
        json.dump(result,output,indent=2);output.write('\n')
    verify(folder)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','publish','verify'))
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--version',default=VERSION,choices=(VERSION,))
    args=parser.parse_args()
    result={'prepare':prepare,'publish':publish,'verify':verify}[args.action](args.folder)
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
