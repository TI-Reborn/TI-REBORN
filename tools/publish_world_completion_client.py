"""Prepare, publish or verify the bounded world zones XML client release.

prepare reads trusted HTTPS and saves reviewable files locally. Publication
requires matching server validation, deployment and hosted-world evidence.
The remote publisher changes one immutable XML blob and the manifest, backs
up previous code/config/client files, and never accesses hosted player data.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import ssl
import urllib.request
import uuid

from tools.deploy_stage4_economy import ROOT, remote
from tools import prepare_world_completion_catalog as catalogue_tool

FOLDER = ROOT/'reports/gameplay-completion/stage8-world'
VERSION = '2026.10.08.5'
PREVIOUS_VERSION = '2026.10.08.4'
CLIENT_PATH = 'base/shared config/zones.xml'
SOURCE_SHA = 'f707e1a4d077bd04e4643801f1c8a0ec4319779b71688dac8338951c3342f2d1'
SOURCE_BYTES = 9887
DLL_SHA = '7ae830b5e8db3249915a3c10b9f45cf23ecac64984b95d4c02b7da326ad7a43b'
DLL_BYTES = 7761408
ORIGIN = 'https://185.184.42.88/updates/'
REQUIRED_RUNTIME = ('config/world_completion.json', 'evidence/zones_diagnostic.xml')
SOURCE_FILES = ('tools/publish_world_completion_client.py',
                'tools/prepare_world_completion_catalog.py', 'tools/verify_world_catalog_native.py')


def sha(raw): return hashlib.sha256(raw).hexdigest()


def checked_manifest(raw, version, candidate=None):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 4*1024*1024:
        raise ValueError('Manifest exceeds reviewed bound')
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get('schema') != 1 or value.get('version') != version:
        raise ValueError('Exact client release version required')
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
        if not isinstance(row['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', row['sha256']):
            raise ValueError('Invalid immutable blob identity')
        if 'seed' in row and type(row['seed']) is not bool:
            raise ValueError('Invalid seed flag')
    dll = next((r for r in files if r['path']=='silver.dll'), None)
    if dll is None or (dll['sha256'],dll['size']) != (DLL_SHA,DLL_BYTES) or dll.get('seed',False):
        raise ValueError('Published DLL must remain unchanged')
    zones = next((r for r in files if r['path']==CLIENT_PATH), None)
    expected = (SOURCE_SHA,SOURCE_BYTES) if version==PREVIOUS_VERSION else candidate
    if expected is None or zones is None or (zones['sha256'],zones['size']) != expected or zones.get('seed') is not False:
        raise ValueError('Exact reviewed zones XML required')
    return value


def new_manifest(old, candidate):
    value = checked_manifest(old,PREVIOUS_VERSION)
    value['version'] = VERSION
    next(r for r in value['files'] if r['path']==CLIENT_PATH).update(sha256=sha(candidate),size=len(candidate))
    return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')


def transition(old,new,candidate):
    a=checked_manifest(old,PREVIOUS_VERSION)
    b=checked_manifest(new,VERSION,(sha(candidate),len(candidate)))
    if set(a)!=set(b) or any(a[k]!=b[k] for k in a if k not in ('files','version')):
        raise ValueError('Unrelated manifest metadata changed')
    if len(a['files'])!=len(b['files']) or [r['path'] for r in a['files']] != [r['path'] for r in b['files']]:
        raise ValueError('Unrelated client catalogue changed')
    changes=[y['path'] for x,y in zip(a['files'],b['files']) if x!=y]
    prior=next(r for r in a['files'] if r['path']==CLIENT_PATH)
    record=next(r for r in b['files'] if r['path']==CLIENT_PATH)
    if changes!=[CLIENT_PATH] or record!=dict(prior,sha256=sha(candidate),size=len(candidate)):
        raise ValueError('Only the reviewed zones XML descriptor can change')
    return changes


def fetch(path,maximum):
    context=ssl.create_default_context();context.keylog_filename=None
    url=ORIGIN+path
    request=urllib.request.Request(url,headers={'Cache-Control':'no-cache','Pragma':'no-cache'})
    with urllib.request.urlopen(request,context=context,timeout=45) as response:
        if response.status!=200 or response.geturl()!=url:
            raise ValueError('Trusted HTTPS endpoint changed')
        raw=response.read(maximum+1)
    if len(raw)>maximum: raise ValueError('Trusted HTTPS response exceeds bound')
    return raw


# Reviewed self-contained stdlib code. Tests run these exact functions in an
# isolated directory, with mocked lock/service handles and no network calls.
REMOTE = r'''
from datetime import datetime,timezone
from pathlib import Path,PurePosixPath
import base64,hashlib,json,os,re,shutil,subprocess,tarfile,tempfile
import xml.etree.ElementTree as ET
LIVE=Path('/var/www/tio-client/updates');DOWNLOADS=Path('/var/www/tio-client/downloads')
GAME=Path('/opt/tio-emulator');PRIVATE=Path('/root')
CONFIGS=(Path('/etc/tio-server/server.toml'),Path('/etc/systemd/system/tio-server.service'),Path('/etc/nginx/snippets/tio-updates.conf'))
PATH='base/shared config/zones.xml';PREVIOUS='2026.10.08.4';VERSION='2026.10.08.5'
SOURCE='f707e1a4d077bd04e4643801f1c8a0ec4319779b71688dac8338951c3342f2d1';SOURCE_BYTES=9887
DLL='7ae830b5e8db3249915a3c10b9f45cf23ecac64984b95d4c02b7da326ad7a43b';DLL_BYTES=7761408
REQUIRED=('config/world_completion.json','evidence/zones_diagnostic.xml')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def safe(name):
 return isinstance(name,str) and bool(name) and len(name)<=256 and chr(92) not in name and not any(ord(c)<32 or c==':' for c in name) and name==str(PurePosixPath(name)) and not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts
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
def runtime_plan(plan):
 if not isinstance(plan,dict) or not set(REQUIRED)<=set(plan) or len(plan)>100:raise ValueError('Missing reviewed world runtime hashes')
 for name,value in plan.items():
  if not safe(name) or not (name in REQUIRED or name.startswith(('tio/','server/','tools/','config/'))) or not name.endswith(('.py','.json','.xml')) or not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):raise ValueError('Unreviewed runtime guard')
 return plan
def guards(plan):
 runtime_plan(plan)
 launchers={n:digest(DOWNLOADS/n) for n in ('TIO-Launcher.exe','TIO-Launcher-0.1.4.exe')}
 if any(v is None for v in launchers.values()):raise RuntimeError('Published launcher missing')
 return dict(launchers=launchers,service=service(),runtime={n:digest(GAME/n) for n in plan},configuration={str(p):digest(p) for p in CONFIGS})
def catalogue(raw,version,candidate=None):
 if not isinstance(raw,bytes) or not 1<=len(raw)<=4*1024*1024:raise ValueError('Manifest too large')
 value=json.loads(raw)
 if not isinstance(value,dict) or value.get('schema')!=1 or value.get('version')!=version:raise ValueError('Client release version changed')
 paths=set();files=value.get('files')
 if not isinstance(files,list) or not 1<=len(files)<=10000:raise ValueError('Invalid client file count')
 for row in files:
  if not isinstance(row,dict) or not {'path','size','sha256'}<=set(row)<={'path','size','sha256','seed'}:raise ValueError('Invalid descriptor')
  name=row['path']
  if not safe(name) or name in paths:raise ValueError('Invalid client path')
  paths.add(name)
  if type(row['size'])is not int or not 0<=row['size']<=64*1024*1024 or not isinstance(row['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',row['sha256']):raise ValueError('Invalid blob')
  if 'seed'in row and type(row['seed'])is not bool:raise ValueError('Invalid seed flag')
 dll=next((r for r in files if r['path']=='silver.dll'),None)
 if dll is None or (dll['sha256'],dll['size'])!=(DLL,DLL_BYTES) or dll.get('seed',False):raise ValueError('Published DLL changed')
 row=next((r for r in files if r['path']==PATH),None);expected=(SOURCE,SOURCE_BYTES) if version==PREVIOUS else candidate
 if expected is None or row is None or (row['sha256'],row['size'])!=expected or row.get('seed')is not False:raise ValueError('Exact reviewed XML required')
 return value
def blobs(value):
 seen={}
 for row in value['files']:
  key=row['sha256']
  if key not in seen:seen[key]=digest(LIVE/'blobs'/key)
  if seen[key]!=dict(sha256=key,size=row['size']):raise RuntimeError('Published client blob corrupt or missing')
 return dict(verified_records=len(value['files']),verified_unique_blobs=len(seen))
def zones(raw,count):
 if not 1<=len(raw)<=50000 or b'<!' in raw:raise ValueError('Unsafe XML')
 root=ET.fromstring(raw)
 if root.tag!='towns' or root.attrib or len(root)!=count:raise ValueError('Unexpected world catalogue')
 ids=[]
 for node in root:
  if node.tag!='town' or set(node.attrib)!={'id','name'} or not node.attrib['name']:raise ValueError('Invalid town')
  ids.append(int(node.attrib['id']));keys=set()
  for value in node:
   if value.tag!='value' or set(value.attrib)!={'key','val'} or value.attrib['key']in keys or len(value):raise ValueError('Invalid world property')
   keys.add(value.attrib['key'])
 if ids!=list(range(1,count+1)):raise ValueError('Native town id-1 order changed')
 return root
def xml_transition(before,after):
 a,b=zones(before,17),zones(after,22)
 def semantic(node):return node.tag,tuple(sorted(node.attrib.items())),tuple(semantic(v) for v in node)
 changed=[i+1 for i in range(17) if semantic(a[i])!=semantic(b[i])]
 if changed!=[4,7,10]:raise ValueError('Unexpected changed world rows')
 pattern=re.compile(rb'  <town\b[^>]*\bid="([0-9]+)"[^>]*>.*?</town>',re.S)
 old={int(m[1]):m[0] for m in pattern.finditer(before)};new={int(m[1]):m[0] for m in pattern.finditer(after)}
 if set(old)!=set(range(1,18)) or set(new)!=set(range(1,23)) or any(old[i]!=new[i] for i in old if i not in (4,7,10)):raise ValueError('Foreign town bytes changed')
def inspect(p):
 plan=runtime_plan(p['server_runtime']);old=(LIVE/'manifest.json').read_bytes();version=json.loads(old).get('version')
 if version not in (PREVIOUS,VERSION):raise RuntimeError('Unexpected live release version')
 a=catalogue(old,version,(p['candidate_sha256'],p['candidate_bytes']))
 return dict(manifest=base64.b64encode(old).decode(),manifest_sha256=sha(old),version=version,blobs=blobs(a),guards=guards(plan),
  database_opened=False,local_player_data_accessed=False,timestamp_utc=datetime.now(timezone.utc).isoformat())
def private_json(path,value):
 fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(value,f,indent=2);f.write(chr(10));f.flush();os.fsync(f.fileno())
def atomic(raw,target):
 fd,name=tempfile.mkstemp(prefix='.world-client-',dir=target.parent);pending=Path(name)
 try:
  with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  pending.chmod(0o644);pending.replace(target)
 finally:pending.unlink(missing_ok=True)
def backup(before,old,new,op,plan):
 saved=Path(tempfile.mkdtemp(prefix='tio-before-world-client-',dir=PRIVATE));saved.chmod(0o700)
 (saved/'manifest.json').write_bytes(old);(saved/'new-manifest.json').write_bytes(new);(saved/'zones.xml').write_bytes(before)
 for name in ('TIO-Launcher.exe','TIO-Launcher-0.1.4.exe'):shutil.copy2(DOWNLOADS/name,saved/name)
 with tarfile.open(saved/'previous-code-config.tar.gz','w:gz') as archive:
  for directory,pattern in (('tio','*.py'),('server','*.py'),('tools','*.py'),('config','*.json')):
   for path in sorted((GAME/directory).rglob(pattern)):
    digest(path)
    archive.add(path,arcname='game/'+path.relative_to(GAME).as_posix())
  for name in plan:
   if name.endswith('.xml'):
    path=GAME/name;digest(path);archive.add(path,arcname='game/'+name)
  for path in CONFIGS:
   if path.is_file():
    digest(path);archive.add(path,arcname='operational/'+path.name)
 private_json(saved/'prepared.json',dict(operation=op,before_manifest=sha(old),after_manifest=sha(new),database_opened=False,local_player_data_uploaded=False))
 return saved
def publish(p):
 import fcntl
 op=p['operation']
 if not isinstance(op,str) or not re.fullmatch('[a-f0-9]{32}',op):raise ValueError('Invalid reviewed operation')
 plan=runtime_plan(p['server_runtime'])
 old=base64.b64decode(p['before_manifest'],validate=True);new=base64.b64decode(p['after_manifest'],validate=True);raw=base64.b64decode(p['candidate'],validate=True)
 expected=(p['candidate_sha256'],p['candidate_bytes'])
 if len(raw)!=expected[1] or sha(raw)!=expected[0]:raise ValueError('Candidate outside reviewed hash')
 a,b=catalogue(old,PREVIOUS),catalogue(new,VERSION,expected)
 if set(a)!=set(b) or any(a[k]!=b[k] for k in a if k not in ('files','version')):raise ValueError('Unexpected manifest metadata')
 if len(a['files'])!=len(b['files']) or [r['path'] for r in a['files']]!=[r['path'] for r in b['files']]:raise ValueError('Unexpected client paths')
 prior=next(r for r in a['files'] if r['path']==PATH);record=next(r for r in b['files'] if r['path']==PATH)
 if [y['path'] for x,y in zip(a['files'],b['files']) if x!=y]!=[PATH] or record!=dict(prior,sha256=expected[0],size=expected[1]):raise ValueError('Only reviewed world XML may change')
 with (PRIVATE/'.tio-gameplay-client.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  journal=PRIVATE/('tio-world-client-'+op+'.json');target=LIVE/'blobs'/expected[0]
  if journal.exists():
   result=json.loads(journal.read_text())
   if result['manifest_sha256']!=sha(new) or result['world_client_release']!=p['world_client_release'] or (LIVE/'manifest.json').read_bytes()!=new or digest(target)!=dict(sha256=expected[0],size=expected[1]) or guards(plan)!=result['guards']:raise RuntimeError('Prior world publication no longer current')
   return dict(result,recovered_completed_publication=True)
  if (LIVE/'manifest.json').read_bytes()!=old:raise RuntimeError('Published manifest changed before world release')
  before=(LIVE/'blobs'/SOURCE).read_bytes()
  if len(before)!=SOURCE_BYTES or sha(before)!=SOURCE:raise RuntimeError('Exact source XML changed')
  xml_transition(before,raw);blobs(a);state=guards(plan)
  for name,expected_hash in plan.items():
   if state['runtime'][name] is None or state['runtime'][name]['sha256']!=expected_hash:raise RuntimeError('Reviewed world server runtime not deployed')
  release=p['world_client_release']
  if release['policy_sha256']!=plan[REQUIRED[0]] or release['runtime_sha256']!=plan[REQUIRED[1]] or release['candidate_sha256']!=sha(raw):raise ValueError('World release hashes disagree')
  saved=backup(before,old,new,op,plan);private_json(saved/'guards.json',state);committed=False
  try:
   if (LIVE/'manifest.json').read_bytes()!=old or guards(plan)!=state:raise RuntimeError('Hosted client/runtime changed during backup')
   if target.exists():
    if target.read_bytes()!=raw:raise RuntimeError('Immutable world blob already differs')
   else:atomic(raw,target)
   if (LIVE/'manifest.json').read_bytes()!=old or guards(plan)!=state:raise RuntimeError('Hosted state changed before world manifest commit')
   atomic(new,LIVE/'manifest.json');committed=True
   if (LIVE/'manifest.json').read_bytes()!=new or digest(target)!=dict(sha256=sha(raw),size=len(raw)):raise RuntimeError('World client parity failed')
   coverage=blobs(b)
   if guards(plan)!=state:raise RuntimeError('Hosted state changed during world publication')
   result=dict(passed=True,operation=op,version=VERSION,backup=str(saved),source_sha256=SOURCE,sha256=sha(raw),size=len(raw),changed=[PATH],
    world_client_release=release,manifest_sha256=sha(new),timestamp_utc=datetime.now(timezone.utc).isoformat(),server_restarted=False,
    database_opened=False,database_written=False,local_player_data_uploaded=False,launchers_preserved=True,service_unchanged=True,
    other_client_files_preserved=True,seed_records_preserved=True,blob_coverage=coverage,guards=state)
   private_json(saved/'publication.json',result);private_json(journal,result);return result
  except BaseException:
   restored=False
   if committed and (LIVE/'manifest.json').read_bytes()==new:atomic(old,LIVE/'manifest.json');restored=True
   private_json(saved/'rollback.json',dict(manifest_restored=restored,current_manifest_sha256=sha((LIVE/'manifest.json').read_bytes()),immutable_unreferenced_blob_retained=True,database_opened=False,server_restarted=False))
   raise
'''
READ = REMOTE+"\nimport sys\nprint(json.dumps(inspect(json.load(sys.stdin))))\n"
PUBLISH = REMOTE+"\nimport sys\nprint(json.dumps(publish(json.load(sys.stdin))))\n"


def folder_checked(folder):
    path=Path(folder).resolve()
    if path!=FOLDER.resolve(): raise ValueError('Only the bounded stage8 report folder is writable')
    return path


def json_file(path): return json.loads(path.read_bytes())


def release_inputs(folder):
    folder=folder_checked(folder)
    catalog=json_file(folder/'catalog.json');source=(folder/'client/source/zones.xml').read_bytes()
    candidate=(folder/'client/candidate/zones.xml').read_bytes()
    policy_raw=(ROOT/'config/world_completion.json').read_bytes()
    runtime=(folder/'runtime/evidence/zones_diagnostic.xml').read_bytes()
    observation_raw=(folder/'client/source/observation.json').read_bytes()
    proof_raw=(folder/'client/native-proof.json').read_bytes();proof=json.loads(proof_raw)
    if (catalog.get('passed') is not True or catalog.get('source_version')!=PREVIOUS_VERSION or catalog.get('new_version')!=VERSION
            or catalog.get('client_path')!=CLIENT_PATH or catalog.get('source_client_sha256')!=SOURCE_SHA
            or catalog.get('policy_sha256')!=sha(policy_raw) or catalog.get('runtime_sha256')!=sha(runtime)
            or catalog.get('observation_sha256')!=sha(observation_raw) or catalog.get('candidate_sha256')!=sha(candidate)
            or catalog.get('candidate_size')!=len(candidate) or catalog.get('foreign_rows_preserved_byte_for_byte') is not True
            or catalog.get('changed_existing_ids')!=[4,7,10] or catalog.get('added_ids')!=[18,19,20,21,22]
            or catalog.get('contiguous_ids')!=list(range(1,23)) or len(source)!=SOURCE_BYTES or sha(source)!=SOURCE_SHA):
        raise ValueError('Reviewed world catalogue/source/policy changed')
    if catalogue_tool.merge(source,json.loads(policy_raw))!=candidate:
        raise ValueError('Candidate XML differs from reviewed world policy')
    server_source=(folder/'source/zones_diagnostic.xml').read_bytes()
    if sha(server_source)!=catalog.get('source_runtime_sha256') or catalogue_tool.merge(server_source,json.loads(policy_raw))!=runtime:
        raise ValueError('Runtime XML differs from reviewed original source/policy')
    if (proof.get('passed') is not True or proof.get('status')!='PASS' or proof.get('candidate_xml_sha256')!=sha(candidate)
            or proof.get('candidate_dll_sha256')!=DLL_SHA or len(proof.get('loader_cases',[]))!=22
            or len(proof.get('town_cases',[]))!=44 or proof.get('shared_config',{}).get('passed') is not True
            or proof.get('float_mapping',{}).get('passed') is not True
            or proof.get('float_mapping',{}).get('order')!=['influence','experience','profit']):
        raise ValueError('Exact native world loader/visibility/float proof required')
    hashes=dict(policy_sha256=sha(policy_raw),runtime_sha256=sha(runtime),candidate_sha256=sha(candidate),native_proof_sha256=sha(proof_raw))
    return catalog,candidate,json.loads(observation_raw)['manifest'],hashes


def sources(): return {name:sha((ROOT/name).read_bytes()) for name in SOURCE_FILES}


def save_json(path,value):
    with path.open('x',encoding='utf-8') as out:json.dump(value,out,ensure_ascii=True,indent=2);out.write('\n')


def prepare(folder=FOLDER):
    folder=folder_checked(folder)
    if (folder/'client/release.json').exists():
        return reviewed(folder)[0]
    catalog,candidate,observed,hashes=release_inputs(folder)
    paths=[folder/'client'/name for name in ('previous-manifest.json','manifest.json','release.json','prepare-https.json')]
    if any(path.exists() for path in paths): raise ValueError('Preserve partial preparation evidence before rebuilding')
    old=fetch('manifest.json',4*1024*1024)
    if checked_manifest(old,PREVIOUS_VERSION)!=observed: raise ValueError('Trusted HTTPS manifest differs from actual observed source')
    if fetch('blobs/'+SOURCE_SHA,SOURCE_BYTES)!=(folder/'client/source/zones.xml').read_bytes():
        raise ValueError('Trusted HTTPS source zones XML changed')
    new=new_manifest(old,candidate);transition(old,new,candidate)
    source_hashes=sources()
    if fetch('manifest.json',4*1024*1024)!=old or release_inputs(folder)[3]!=hashes:
        raise ValueError('Source/catalogue changed during preparation')
    release=dict(passed=True,operation=uuid.uuid4().hex,version=VERSION,previous_version=PREVIOUS_VERSION,
        client_path=CLIENT_PATH,source_sha256=SOURCE_SHA,source_bytes=SOURCE_BYTES,candidate_sha256=sha(candidate),candidate_bytes=len(candidate),
        before_manifest_sha256=sha(old),manifest_sha256=sha(new),catalog_sha256=sha((folder/'catalog.json').read_bytes()),
        world_client_release=hashes,source_hashes=source_hashes,changed=[CLIENT_PATH],trusted_https=True,
        prepared_utc=datetime.now(timezone.utc).isoformat(),published=False,database_opened=False,installed_client_changed=False,
        graphical_acceptance_complete=False,other_client_files_preserved=True,news_preserved=True,seed_records_preserved=True,dll_preserved=True)
    with paths[0].open('xb') as out:out.write(old)
    with paths[1].open('xb') as out:out.write(new)
    save_json(paths[3],dict(passed=True,origin=ORIGIN,source_version=PREVIOUS_VERSION,manifest_sha256=sha(old),zones_sha256=SOURCE_SHA,trusted_https=True))
    save_json(paths[2],release)
    return release


def reviewed(folder):
    folder=folder_checked(folder);release=json_file(folder/'client/release.json')
    catalog,candidate,observed,hashes=release_inputs(folder)
    old=(folder/'client/previous-manifest.json').read_bytes();new=(folder/'client/manifest.json').read_bytes()
    transition(old,new,candidate)
    if (release.get('passed') is not True or release.get('version')!=VERSION or release.get('previous_version')!=PREVIOUS_VERSION
            or release.get('world_client_release')!=hashes or release.get('source_hashes')!=sources()
            or release.get('before_manifest_sha256')!=sha(old) or release.get('manifest_sha256')!=sha(new)
            or release.get('catalog_sha256')!=sha((folder/'catalog.json').read_bytes()) or release.get('candidate_sha256')!=sha(candidate)
            or release.get('candidate_bytes')!=len(candidate) or release.get('changed')!=[CLIENT_PATH]
            or checked_manifest(old,PREVIOUS_VERSION)!=observed or not re.fullmatch('[a-f0-9]{32}',release.get('operation',''))):
        raise ValueError('Prepared world release changed; preserve evidence and review again')
    return release,old,new,candidate


def publication_gate(folder,release):
    expected=release['world_client_release']
    reports={name:json_file(folder/name) for name in ('validation.json','deployment.json','hosted-world.json')}
    for name,value in reports.items():
        if value.get('passed') is not True or value.get('world_client_release')!=expected:
            raise ValueError(name+' must pass for this exact world_client_release')
    deployment=reports['deployment.json']
    runtime=deployment.get('runtime_files',deployment.get('hashes'))
    if not isinstance(runtime,dict) or not set(REQUIRED_RUNTIME)<=set(runtime):
        raise ValueError('Deployment requires actual runtime_files or hashes name-to-SHA mapping')
    scope={};exec(compile(REMOTE,'reviewed-world-remote','exec'),scope)
    scope['runtime_plan'](runtime)
    if runtime[REQUIRED_RUNTIME[0]]!=expected['policy_sha256'] or runtime[REQUIRED_RUNTIME[1]]!=expected['runtime_sha256']:
        raise ValueError('Deployed world policy/XML hashes differ from reviewed release')
    return runtime


def verify(folder=FOLDER):
    folder=folder_checked(folder);release,_,new,candidate=reviewed(folder)
    if fetch('manifest.json',4*1024*1024)!=new or fetch('blobs/'+sha(candidate),len(candidate))!=candidate:
        raise ValueError('Trusted HTTPS published world release differs')
    result=dict(passed=True,trusted_https=True,version=VERSION,origin=ORIGIN,manifest_sha256=sha(new),zones_sha256=sha(candidate),
        world_client_release=release['world_client_release'],database_opened=False,installed_client_changed=False,
        graphical_acceptance_complete=False,verified_utc=datetime.now(timezone.utc).isoformat())
    path=folder/'client/https-verification.json'
    if path.exists():
        existing=json_file(path)
        if any(existing.get(k)!=v for k,v in result.items() if k!='verified_utc'): raise ValueError('Preserve different HTTPS verification evidence')
        return existing
    save_json(path,result);return result


def publish(folder=FOLDER):
    folder=folder_checked(folder);release,old,new,candidate=reviewed(folder)
    runtime=publication_gate(folder,release)
    inspection=remote(READ,dict(server_runtime=runtime,candidate_sha256=sha(candidate),candidate_bytes=len(candidate)))
    current=base64.b64decode(inspection['manifest'],validate=True)
    if current not in (old,new) or inspection['manifest_sha256']!=sha(current) or fetch('manifest.json',4*1024*1024)!=current:
        raise ValueError('Fresh SSH and trusted HTTPS manifest baseline differ')
    current_record=next(row for row in json.loads(current)['files'] if row['path']==CLIENT_PATH)
    expected_raw=(folder/'client/source/zones.xml').read_bytes() if current==old else candidate
    if fetch('blobs/'+current_record['sha256'],current_record['size'])!=expected_raw:
        raise ValueError('Fresh trusted HTTPS XML baseline differs')
    payload=dict(operation=release['operation'],before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),
        candidate=base64.b64encode(candidate).decode(),candidate_sha256=sha(candidate),candidate_bytes=len(candidate),
        server_runtime=runtime,world_client_release=release['world_client_release'])
    result=remote(PUBLISH,payload)
    if (result.get('passed') is not True or result.get('operation')!=release['operation'] or result.get('manifest_sha256')!=sha(new)
            or result.get('world_client_release')!=release['world_client_release'] or result.get('changed')!=[CLIENT_PATH]):
        raise ValueError('Remote publication outcome unconfirmed; retry this same operation')
    path=folder/'client/publication.json'
    if path.exists():
        previous=json_file(path)
        if any(previous.get(k)!=result.get(k) for k in ('operation','manifest_sha256','backup','world_client_release')):
            raise ValueError('Preserve differing publication evidence')
    else: save_json(path,result)
    verify(folder);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','publish','verify'))
    parser.add_argument('--folder',type=Path,default=FOLDER)
    parser.add_argument('--version',default=VERSION,choices=(VERSION,))
    args=parser.parse_args()
    print(json.dumps({'prepare':prepare,'publish':publish,'verify':verify}[args.action](args.folder),ensure_ascii=True,indent=2))


if __name__=='__main__':main()
