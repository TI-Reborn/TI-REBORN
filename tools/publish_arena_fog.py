"""Publish the reviewed client-only .1 -> .2 tint patch only with --execute.

Default and --self-test are offline. The hosted operation preserves every old
blob, backs up the live database consistently, and atomically switches only the
client manifest. It never uploads player data, code, configuration or binaries.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import errno
import hashlib
import io
import json
from pathlib import Path
import subprocess
import ssl
import sys
import tempfile
import time
import urllib.request
import urllib.error
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import prepare_arena_fog_deploy as prep

OUT = prep.OUT
HOST = 'root@185.184.42.88'
ORIGIN = 'https://185.184.42.88/updates/'
KEY = Path.home()/'.ssh/tio_server'
SSH = ['ssh','-i',str(KEY),'-o','BatchMode=yes','-o','ConnectTimeout=10',HOST]
SCP = ['scp','-i',str(KEY),'-o','BatchMode=yes','-o','ConnectTimeout=10']
require, sha, save = prep.require, prep.sha, prep.save


def load_bundle():
    report = json.loads((OUT/'release-verification.json').read_bytes())
    archive = (OUT/'patch.zip').read_bytes()
    require(report.get('passed') is True and report['version'] == prep.NEW and
            report['patch_zip_sha256'] == sha(archive) and report['patch_zip_size'] == len(archive),
            'Matching completed offline release required')
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        require(bundle.testzip() is None, 'ZIP CRC failed')
        names = bundle.namelist()
        require(len(set(names)) == len(names), 'Duplicate ZIP members')
        raw_guard = bundle.read('guard.json');guard = json.loads(raw_guard)
        require(sha(raw_guard) == report['guard_sha256'] == sha((OUT/'guard.json').read_bytes()), 'Guard hash differs')
        require(guard['schema'] == 'arena-surroundings-fog-release/v1' and guard['version'] == prep.NEW and
                guard['before_version'] == prep.OLD and guard['tint_color_hex'] == '00b1b1b1' and
                guard['alpha'] == 255 and guard['changed_raw_offsets'] == [52,53,54], 'Unexpected release scope')
        require(guard['database_uploaded'] is guard['server_code_uploaded'] is
                guard['service_restart_required'] is guard['executable_or_launcher_changes'] is False,
                'Client-only release scope changed')
        require(all(sha((ROOT/p).read_bytes()) == digest for p,digest in guard['tool_sources'].items()), 'Prepared deploy tool changed')
        expected = {'guard.json','client/manifest.json','client/previous-manifest.json'} | set(guard['proof_files']) | {
                   'client/blobs/'+r['after']['sha256'] for r in guard['replacements'].values()}
        require(set(names) == expected and all(not x.is_dir() and not ((x.external_attr>>16)&0o170000) == 0o120000
                for x in bundle.infolist()), 'Unexpected ZIP file/type')
        old_raw,new_raw = bundle.read('client/previous-manifest.json'),bundle.read('client/manifest.json')
        require(sha(old_raw) == guard['baseline_manifest_sha256'] and sha(new_raw) == guard['new_manifest_sha256'], 'Manifest pin differs')
        old,new = json.loads(old_raw),json.loads(new_raw)
        prep.validate_baseline(guard['baseline'],old_raw,guard['launcher_baseline'])
        delta = prep.validate_manifest_delta(old,new,{p:r['after'] for p,r in guard['replacements'].items()})
        for path,r in guard['replacements'].items():
            before = (prep.OLD_OVERLAY/path).read_bytes();after = bundle.read('client/blobs/'+r['after']['sha256'])
            require(sha(before) == r['before']['sha256'] and len(before) == r['before']['size'] and
                    sha(after) == r['after']['sha256'] and len(after) == r['after']['size'], 'Immutable TILE pin differs')
            require(len(before) == len(after) == 544 and before[:8] == after[:8] == b'TI TILE\0', 'Published TILE envelope changed')
            require(prep.tint_pair(before,after) == {k:r[k] for k in
                    ('changed_raw_offsets','old_native_sha256','new_native_sha256','color_hex','alpha')}, 'TILE delta proof differs')
        for p,digest in guard['proof_files'].items():require(sha(bundle.read(p)) == digest,'Proof hash differs')
        fog = json.loads(bundle.read('proofs/fog-proof.json'));tests = json.loads(bundle.read('proofs/local-tests.json'))
        require(fog.get('passed') is True and tests.get('passed') is True and
                max(tests.get('tests_run',0),tests.get('checks',0)) > 0 and
                tests.get('failures',0) == tests.get('errors',0) == 0, 'Incomplete local proof')
        native = json.loads(bundle.read('proofs/native-fog-tint.json'))
        prep.validate_native_proof(native,sha(bundle.read('proofs/native-v1.json')))
        require(native['full_native_audit']['sha256'] == sha(bundle.read('proofs/native-full-audit.json')) and
                fog['original_asset_proof_sha256'] == sha(bundle.read('proofs/original-asset-proof.json')), 'Native/original proof pin differs')
    return report,guard,old_raw,new_raw


# This source is sent through SSH stdin. It runs only with --execute; it uses no
# downloaded project scripts and accepts only this release's fixed resource set.
REMOTE = r'''
import hashlib,json,os,re,shutil,sqlite3,struct,subprocess,tempfile,zipfile,zlib
from pathlib import Path
from contextlib import closing
LIVE=Path('/var/www/tio-client/updates')
DB=Path('/var/lib/tio-server/reservation.sqlite3')
OLD='2026.10.07.1';NEW='2026.10.07.2'
SOURCES={'tio/arena_map.py','tio/map_generation.py','tio/arena_surroundings.py',
 'config/battle_map_profiles.json','config/arena_surroundings.json','config/arena_fragments.json',
 'config/reservation_visuals.json','tio/protocol/battle_ground.py'}
def check(value,message):
 if not value:raise RuntimeError(message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(path):return sha(Path(path).read_bytes())
def command(*args):return subprocess.check_output(args,text=True,timeout=20).strip()
def records(obj):
 files=obj['files'];result={r['path']:r for r in files}
 check(len(result)==len(files)==6218 and len({p.lower() for p in result})==6218 and
       all(re.fullmatch('[a-f0-9]{64}',r['sha256']) and type(r['size']) is int and r['size']>=0
           for r in files),'Client record set differs')
 return result
def database(path=DB):
 with closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)) as db:
  db.execute('BEGIN')
  names=sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
  counts={};fingerprints={}
  for name in names:
   rows=sorted(repr(row) for row in db.execute('SELECT * FROM "'+name.replace('"','""')+'"'))
   counts[name]=len(rows);fingerprints[name]=sha(json.dumps(rows,ensure_ascii=False).encode())
  return dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],accounts=counts['accounts'],
   checkpoints=counts['battle_checkpoints'],pending=counts['battle_settlement_jobs'],
   table_counts=counts,table_sha256=fingerprints)
def health(g,manifest_sha):
 b=g['baseline'];service=command('systemctl','is-active','tio-server')
 pid=command('systemctl','show','tio-server','--property=MainPID','--value')
 connections=command('ss','-Htn','state','established','( sport = :28512 or sport = :28513 )').splitlines()
 listeners=command('ss','-Hltn','( sport = :28512 or sport = :28513 )').splitlines()
 check(service=='active' and pid==b['pid'] and not connections and len(listeners)==2,'Service/PID/player preflight drift')
 check(digest(LIVE/'manifest.json')==manifest_sha,'Live client manifest drift')
 check(set(b['sources'])==SOURCES,'Unexpected baseline source scope')
 for name,entry in b['sources'].items():
  path=Path('/opt/tio-emulator')/name
  check(str(path)==entry['path'] and digest(path)==entry['sha256'],'Live source drift: '+name)
 check(digest('/etc/tio-server/server.toml')==b['configuration_sha256'],'Live configuration drift')
 fragment=command('systemctl','show','tio-server','--property=FragmentPath','--value')
 check(fragment==b['fragment_path']=='/etc/systemd/system/tio-server.service' and
       digest(fragment)==b['fragment_sha256'],'Systemd unit drift')
 for entry in g['launcher_baseline']['files']:
  path=Path('/var/www/tio-client')/entry['relative']
  check(str(path)==entry['path'] and path.is_file(),'Launcher baseline path differs')
  expected=manifest_sha if path==LIVE/'manifest.json' else entry['sha256']
  check(digest(path)==expected,'Launcher download/metadata drift')
 state=database()
 check(state['integrity']=='ok' and state['checkpoints']==state['pending']==0,'Database busy/unhealthy')
 check(state['accounts']==b['database']['accounts'] and state['table_counts']==b['database']['table_counts'],
       'Hosted database table-count drift')
 return dict(service=service,pid=pid,established_connections=0,gameplay_listeners=2,database=state,
  manifest_sha256=manifest_sha,code_configuration_unit_and_launcher_unchanged=True)
def atomic_manifest(raw):
 fd,path=tempfile.mkstemp(prefix='.manifest-fog-',dir=LIVE)
 try:
  with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
  os.chmod(path,0o644);os.replace(path,LIVE/'manifest.json')
  directory=os.open(LIVE,os.O_DIRECTORY)
  try:os.fsync(directory)
  finally:os.close(directory)
 finally:
  if os.path.exists(path):os.unlink(path)
def native(raw):
 if raw[:4]==b'\x03ZIP':
  result=zlib.decompress(raw[16:]);check(len(result)==struct.unpack_from('<I',raw,8)[0],'Native ZIP length differs');return result
 return raw
def validate_payload(bundle,g):
 names=bundle.namelist();changes=g['replacements']
 expected={'guard.json','client/manifest.json','client/previous-manifest.json'}|set(g['proof_files'])|{
  'client/blobs/'+r['after']['sha256'] for r in changes.values()}
 check(len(set(names))==len(names) and set(names)==expected and bundle.testzip() is None,'Unsafe/incomplete patch ZIP')
 check(all(not r.is_dir() and ((r.external_attr>>16)&0o170000)!=0o120000 for r in bundle.infolist()),'Unexpected ZIP member type')
 old_raw=bundle.read('client/previous-manifest.json');new_raw=bundle.read('client/manifest.json')
 check(sha(old_raw)==g['baseline_manifest_sha256'] and sha(new_raw)==g['new_manifest_sha256'],'Patch manifest pin differs')
 old=json.loads(old_raw);new=json.loads(new_raw);a=records(old);b=records(new)
 check(old['version']==OLD and new['version']==NEW and set(a)==set(b),'Unexpected client versions/path set')
 check(len(changes)==552 and {p for p in a if a[p]!=b[p]}==set(changes),'Only 552 records may change')
 check({k:v for k,v in old.items() if k not in ('version','news','files')}==
       {k:v for k,v in new.items() if k not in ('version','news','files')},'Manifest metadata changed')
 for p,r in changes.items():
  check(re.fullmatch(r'base/setting/arena_surroundings/as_(rv|de|ny|mz)_[1-3]_(38|57)_p[0-9]{4}\.t',p),
        'Unexpected changed resource path')
  check(a[p]==r['before'] and b[p]==r['after'] and
        {k:v for k,v in a[p].items() if k not in ('sha256','size')}==
        {k:v for k,v in b[p].items() if k not in ('sha256','size')},'Resource metadata changed')
  original=(LIVE/'blobs'/a[p]['sha256']).read_bytes();replacement=bundle.read('client/blobs/'+b[p]['sha256'])
  check(sha(original)==a[p]['sha256'] and len(original)==a[p]['size'] and
        sha(replacement)==b[p]['sha256'] and len(replacement)==b[p]['size'],'Immutable resource pin differs')
  x,y=native(original),native(replacement)
  check(original==x and replacement==y and len(x)==len(y)==544 and x[:8]==y[:8]==b'TI TILE\0' and
        struct.unpack_from('<II',x,52)==(0x00ffffff,255) and
        struct.unpack_from('<II',y,52)==(0x00b1b1b1,255) and
        [i for i in range(544) if x[i]!=y[i]]==[52,53,54],'Non-RGB native TILE change')
  check(sha(x)==r['old_native_sha256'] and sha(y)==r['new_native_sha256'],'Decoded native pin differs')
 for p,d in g['proof_files'].items():check(sha(bundle.read(p))==d,'Packaged proof pin differs')
 rgb=json.loads(bundle.read('proofs/native-fog-tint.json'));tests=json.loads(bundle.read('proofs/local-tests.json'))
 check(rgb['status']=='PASS' and rgb['tint_color_hex']=='00b1b1b1' and rgb['alpha']==255 and
       rgb['changed_raw_offsets']==[52,53,54] and rgb['runtime_rgb']['passed'] is True and
       rgb['runtime_rgb']['input_raw_color_hex']=='00b1b1b1' and
       all(x=='ffb1b1b1' for x in rgb['runtime_rgb']['final_vertex_colors_hex']) and
       bool(rgb['runtime_rgb']['final_vertex_colors_hex']) and rgb['fog_independent'] is True and
       rgb['interactive_fields_zero'] is True,'Native RGB proof differs')
 check(rgb['native_v1_proof_sha256']==sha(bundle.read('proofs/native-v1.json'))==g['native_v1_proof_sha256'] and
       rgb['full_native_audit']['sha256']==sha(bundle.read('proofs/native-full-audit.json')),'Original native proof differs')
 check(json.loads(bundle.read('proofs/fog-proof.json'))['passed'] is True and tests['passed'] is True and
       max(tests.get('tests_run',0),tests.get('checks',0))>0 and tests.get('failures',0)==tests.get('errors',0)==0,
       'Local proof is incomplete')
 check(g['database_uploaded'] is g['server_code_uploaded'] is g['service_restart_required'] is
       g['executable_or_launcher_changes'] is False,'Non-client release scope')
 return old_raw,new_raw
def backup(g,old_raw,before):
 destination=Path(tempfile.mkdtemp(prefix='tio-before-arena-surroundings-fog-',dir='/root'))
 destination.chmod(0o700)
 with closing(sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(destination/'reservation.sqlite3')) as target:
  source.backup(target)
 (destination/'reservation.sqlite3').chmod(0o600)
 check(database(destination/'reservation.sqlite3')==before['database'],'Consistent database backup differs')
 for name,entry in g['baseline']['sources'].items():
  target=destination/'code'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(entry['path'],target)
 for path,name in (('/etc/tio-server/server.toml','server.toml'),(g['baseline']['fragment_path'],'tio-server.service')):
  shutil.copy2(path,destination/name);(destination/name).chmod(0o600)
 for entry in g['launcher_baseline']['files']:
  target=destination/'client'/entry['relative'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(entry['path'],target)
 (destination/'previous-manifest.json').write_bytes(old_raw)
 (destination/'guard.json').write_text(json.dumps(g,ensure_ascii=False,indent=2)+'\n')
 (destination/'before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2)+'\n')
 return destination
def main(request):
 g=request['guard'];action=request['action']
 check(g['schema']=='arena-surroundings-fog-release/v1' and g['before_version']==OLD and g['version']==NEW,'Unknown guard')
 if action=='inspect':
  result=health(g,g['baseline_manifest_sha256']);result.update(passed=True,read_only=True);return result
 if action=='postflight':
  result=health(g,g['new_manifest_sha256'])
  check(result['database']==request['database_before'],'Hosted data changed during client publication')
  result.update(passed=True,read_only=True);return result
 if action=='rollback':
  health(g,g['new_manifest_sha256'])
  path=Path(request['backup']).resolve()
  check(path.parent==Path('/root') and path.name.startswith('tio-before-arena-surroundings-fog-'),'Invalid rollback source')
  old_raw=(path/'previous-manifest.json').read_bytes();check(sha(old_raw)==g['baseline_manifest_sha256'],'Rollback baseline differs')
  atomic_manifest(old_raw);health(g,g['baseline_manifest_sha256'])
  return dict(passed=True,rolled_back=True,database_restored=False,code_restored=False,immutable_blobs_retained=True)
 check(action=='publish','Unknown action')
 path=Path(request['zip_path']);check(str(path)=='/root/tio-arena-fog-'+request['zip_sha256']+'.zip' and
  re.fullmatch('[a-f0-9]{64}',request['zip_sha256']) and digest(path)==request['zip_sha256'],'Uploaded bundle pin differs')
 with zipfile.ZipFile(path) as bundle:
  check(sha(bundle.read('guard.json'))==request['guard_sha256'] and json.loads(bundle.read('guard.json'))==g,'Uploaded guard differs')
  old_raw,new_raw=validate_payload(bundle,g);before=health(g,g['baseline_manifest_sha256'])
  destination=backup(g,old_raw,before);switched=False
  try:
   new_blobs=0;reused_blobs=0
   for d in sorted({r['after']['sha256'] for r in g['replacements'].values()}):
    raw=bundle.read('client/blobs/'+d);target=LIVE/'blobs'/d
    if target.exists():check(target.is_file() and not target.is_symlink() and digest(target)==d,'Immutable blob collision');reused_blobs+=1
    else:
     with target.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
     target.chmod(0o644);new_blobs+=1
   before_switch=health(g,g['baseline_manifest_sha256'])
   check(before_switch['database']==before['database'],'Database changed before manifest switch')
   atomic_manifest(new_raw);switched=True
   after=health(g,g['new_manifest_sha256']);check(after['database']==before['database'],'Database changed during switch')
   result=dict(passed=True,version=NEW,previous_version=OLD,backup=str(destination),before=before,after=after,
    changed_records=552,unchanged_records=5666,legacy_records_preserved=5090,scene_records_preserved=24,
    png_records_preserved=552,new_immutable_blobs=new_blobs,reused_immutable_blobs=reused_blobs,
    database_uploaded=False,database_replaced=False,all_hosted_table_rows_preserved=True,
    code_uploaded=False,configuration_changed=False,service_restarted=False,pid_unchanged=True,
    launcher_executable_and_download_metadata_preserved=True,manifest_switched_atomically=True)
   (destination/'publication.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');return result
  except Exception as error:
   reverted=False
   if switched and digest(LIVE/'manifest.json')==g['new_manifest_sha256']:atomic_manifest(old_raw);reverted=True
   raise RuntimeError(str(error)+'; backup='+str(destination)+'; manifest_reverted='+str(reverted))
'''


def remote(action,guard,**data):
    script = REMOTE+'\ntry:\n result=main('+repr(dict(action=action,guard=guard,**data))+')\n print(json.dumps(result))\nexcept Exception as error:\n print(json.dumps(dict(passed=False,error=str(error),action='+repr(action)+')))\n raise SystemExit(1)\n'
    completed = subprocess.run(SSH+['python3 -'],input=script,text=True,encoding='utf-8',capture_output=True,timeout=180)
    try:result = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError,IndexError):raise RuntimeError('SSH returned no structured fog publication result')
    if completed.returncode or result.get('passed') is not True:
        save(OUT/('remote-'+action+'-failure.json'),result)
        raise RuntimeError(result.get('error','Hosted fog operation failed'))
    return result


def transient_https_error(error):
    if isinstance(error,urllib.error.HTTPError):
        return False
    reason=error.reason if isinstance(error,urllib.error.URLError) else error
    # Certificate/SSL protocol failures remain hard failures. The observed
    # handshake timeout is a TimeoutError inside URLError, not a cert failure.
    if isinstance(reason,ssl.SSLError):
        return False
    if isinstance(reason,(TimeoutError,ConnectionError)):
        return True
    if isinstance(reason,OSError) and reason.errno in (
        errno.ETIMEDOUT,errno.ECONNRESET,errno.ECONNABORTED,errno.ENETUNREACH,
        errno.EHOSTUNREACH,errno.EAGAIN,10054,10060,-3):
        return True
    return isinstance(error,urllib.error.URLError) and any(message in str(reason).lower() for message in
        ('timed out','temporary failure in name resolution','connection reset','connection aborted'))


def get(url,timeout=20,deadline=None):
    deadline=time.monotonic()+3*timeout+1 if deadline is None else deadline
    for attempt in range(3):
        remaining=deadline-time.monotonic()
        require(remaining>0,'Public HTTPS verification deadline exceeded')
        try:
            # Default urllib/system SSL verification remains enabled.
            with urllib.request.urlopen(url,timeout=min(timeout,remaining)) as response:
                require(response.status == 200 and response.geturl() == url,'Unexpected HTTPS response/redirect')
                raw=response.read(8*1024*1024+1)
                require(len(raw)<=8*1024*1024,'HTTPS response too large')
                return raw
        except (OSError,urllib.error.URLError) as error:
            if attempt==2 or not transient_https_error(error):
                raise
            remaining=deadline-time.monotonic()
            require(remaining>0,'Public HTTPS verification deadline exceeded')
            time.sleep(min(.25*(attempt+1),remaining))


def https_check(guard,old_raw,new_raw):
    deadline=time.monotonic()+300
    actual = get(ORIGIN+'manifest.json',deadline=deadline)
    require(actual == new_raw,'Public HTTPS manifest differs from prepared release')
    prep.validate_manifest_delta(json.loads(old_raw),json.loads(actual),{p:r['after'] for p,r in guard['replacements'].items()})
    def check(entry):
        path,record=entry
        remaining=deadline-time.monotonic()
        require(remaining>0,'Public HTTPS verification deadline exceeded')
        raw=get(ORIGIN+'blobs/'+record['after']['sha256'],deadline=deadline)
        require(len(raw)==record['after']['size'] and sha(raw)==record['after']['sha256'],'Public TILE hash differs: '+path)
        original=(prep.OLD_OVERLAY/path).read_bytes();prep.tint_pair(original,raw)
        return path
    with ThreadPoolExecutor(max_workers=3) as workers:verified=list(workers.map(check,sorted(guard['replacements'].items())))
    return dict(passed=True,client_version=prep.NEW,verified_tinted_tiles=len(verified),manifest_sha256=sha(actual),
                unchanged_manifest_records=5666,legacy_records_preserved=5090,scenes_preserved=24,pngs_preserved=552,
                actual_https=True,graphical_client_verification=False,
                request_attempt_limit=3,https_concurrency=3,deadline_seconds=300)


def publish(execute=False):
    report,guard,old_raw,new_raw = load_bundle()
    plan=dict(passed=True,execute_requested=execute,client_version=prep.NEW,previous_version=prep.OLD,
        changed_records=552,unchanged_records=5666,patch_zip_sha256=report['patch_zip_sha256'],
        fresh_remote_preflight_required=True,database_backup='Consistent SQLite backup of live hosted data',
        publication='Upload immutable TILE blobs, then atomic manifest replacement',
        database_uploaded=False,code_uploaded=False,service_restart_required=False,
        launcher_executable_changed=False,new_player_zip_published=False,server_contacted=False)
    save(OUT/'publication-plan.json',plan)
    if not execute:
        print(json.dumps(dict(passed=True,offline=True,version=prep.NEW,changed_records=552,
                             execute_required=True,server_contacted=False)));return plan
    save(OUT/'deployment.json',dict(passed=False,status='preflight',version=prep.NEW))
    before=remote('inspect',guard);save(OUT/'publication-preflight.json',before)
    target='/root/tio-arena-fog-'+report['patch_zip_sha256']+'.zip'
    subprocess.run(SCP+[str(OUT/'patch.zip'),HOST+':'+target],check=True,timeout=120,capture_output=True)
    deployed=remote('publish',guard,zip_path=target,zip_sha256=report['patch_zip_sha256'],guard_sha256=report['guard_sha256'])
    try:
        public=https_check(guard,old_raw,new_raw);save(OUT/'https-release.json',public)
        health=remote('postflight',guard,database_before=deployed['before']['database']);save(OUT/'hosted-health.json',health)
    except Exception as error:
        failure=dict(passed=False,version=prep.NEW,error=str(error),backup=deployed['backup'],published=False)
        try:failure['rollback']=remote('rollback',guard,backup=deployed['backup'])
        except Exception as rollback_error:failure['rollback_error']=str(rollback_error)
        save(OUT/'deployment.json',failure);raise
    deployed.update(patch_zip_sha256=report['patch_zip_sha256'],public_https_tiles_verified=552,
                    public_https_passed=True,postflight_passed=True,graphical_clients_verified=False)
    save(OUT/'deployment.json',deployed)
    print(json.dumps({k:deployed[k] for k in ('passed','version','changed_records','unchanged_records','backup','service_restarted')}))
    return deployed


def self_test():
    checks=prep.self_test()
    # Execute only the pure predicates in the remote source; no SSH, shell,
    # process inspection, database handle or hosted filesystem is opened.
    namespace={};exec(REMOTE,namespace)
    compile(REMOTE,'<fog-remote>','exec');checks+=1
    before=json.loads((OUT/'previous-client-manifest.json').read_bytes())
    require(namespace['records'](before)==prep.records(before),'Local/remote manifest interpretation differs');checks+=1
    broken=copy.deepcopy(before);broken['files'].append(copy.deepcopy(broken['files'][0]))
    try:namespace['records'](broken)
    except RuntimeError:checks+=1
    else:raise AssertionError('Remote duplicate manifest accepted')
    from tools.arena_surroundings_native import encode_tile
    native=encode_tile('as_mz_1_57_p0000.png',1024,1024,32,0,render_type=1)
    require(namespace['native'](native)==prep.native(native),'Native decoding differs');checks+=1
    # Confirm preflight rejects SHA drift before it can touch SQLite/backups.
    guard={'baseline':{'pid':'123','sources':{},'configuration_sha256':'x','fragment_path':'x'},
           'launcher_baseline':{'files':[]}}
    original_command,original_digest=namespace['command'],namespace['digest']
    namespace['command']=lambda *args: 'active' if args[:2]==('systemctl','is-active') else (
      '123' if args[:2]==('systemctl','show') else ('' if 'established' in args else 'listener1\nlistener2'))
    namespace['digest']=lambda path:'different'
    try:namespace['health'](guard,'expected')
    except RuntimeError as error:require(str(error)=='Live client manifest drift','Wrong drift guard');checks+=1
    else:raise AssertionError('Remote manifest drift accepted')
    namespace['command'],namespace['digest']=original_command,original_digest
    # Exercise the complete remote three-byte allowlist against the actual old
    # published mirror in a private temporary directory. All input reads below
    # are local; no publication, accounts, process or database access occurs.
    changes={};blobs={};after=copy.deepcopy(before);after['version']=prep.NEW
    for record in after['files']:
        if prep.surroundings(record['path']) and record['path'].endswith('.t'):
            old_raw=(prep.OLD_OVERLAY/record['path']).read_bytes()
            tinted=bytearray(prep.native(old_raw));tinted[52:55]=b'\xb1\xb1\xb1';tinted=bytes(tinted)
            after_record=copy.deepcopy(record);after_record.update(size=len(tinted),sha256=sha(tinted))
            changes[record['path']]=dict(before=copy.deepcopy(record),after=after_record,**prep.tint_pair(old_raw,tinted))
            record.update(after_record);blobs[sha(tinted)]=tinted
    old_raw=(OUT/'previous-client-manifest.json').read_bytes();new_raw=json.dumps(after).encode()
    proof_paths={'proofs/native-fog-tint.json':OUT/'native-fog-tint.json',
        'proofs/native-v1.json':prep.NATIVE_V1,'proofs/local-tests.json':OUT/'local-tests.json',
        'proofs/fog-proof.json':ROOT/'assets/arena-surroundings-v2/fog-proof.json',
        'proofs/native-full-audit.json':ROOT/'reports/arena-surroundings-implementation/native-permanent-outside-fog-audit.json'}
    proofs={p:v.read_bytes() for p,v in proof_paths.items()}
    guard=dict(replacements=changes,baseline_manifest_sha256=sha(old_raw),new_manifest_sha256=sha(new_raw),
       proof_files={p:sha(v) for p,v in proofs.items()},native_v1_proof_sha256=sha(proofs['proofs/native-v1.json']),
       database_uploaded=False,server_code_uploaded=False,service_restart_required=False,executable_or_launcher_changes=False)
    def archive(change=None,extra=False):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as bundle:
            bundle.writestr('guard.json',json.dumps(guard));bundle.writestr('client/previous-manifest.json',old_raw)
            bundle.writestr('client/manifest.json',new_raw)
            for p,v in proofs.items():bundle.writestr(p,v)
            for d,v in blobs.items():bundle.writestr('client/blobs/'+d,change(v) if change else v)
            if extra:bundle.writestr('../server.py',b'forbidden')
        return zipfile.ZipFile(io.BytesIO(data.getvalue()))
    with tempfile.TemporaryDirectory(prefix='tio-fog-offline-') as local:
        namespace['LIVE']=Path(local);(Path(local)/'blobs').mkdir()
        for r in changes.values():
            (Path(local)/'blobs'/r['before']['sha256']).write_bytes((prep.OLD_OVERLAY/r['before']['path']).read_bytes())
        with archive() as bundle:namespace['validate_payload'](bundle,guard);checks+=1
        for change,extra in ((lambda v:v[:56]+b'\xfe'+v[57:],False),(None,True)):
            try:
                with archive(change,extra) as bundle:namespace['validate_payload'](bundle,guard)
            except RuntimeError:checks+=1
            else:raise AssertionError('Remote malformed/foreign payload accepted')
    # Fake only the HTTP transport, never TLS policy or live resources. Test
    # transient recovery, three-attempt exhaustion and hard security failures.
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def geturl(self):return ORIGIN+'manifest.json'
        def read(self,*args):return b'expected'
    original_open,original_sleep=urllib.request.urlopen,time.sleep
    calls=[]
    def fake_open(url,**kwargs):
        calls.append(kwargs)
        if len(calls)<3:raise urllib.error.URLError(TimeoutError('TLS handshake timed out'))
        return Response()
    try:
        urllib.request.urlopen=fake_open;time.sleep=lambda delay:None
        require(get(ORIGIN+'manifest.json')==b'expected' and len(calls)==3 and
                all(set(c)=={'timeout'} for c in calls),'Bounded retry/default TLS differs');checks+=1
        for error,expected_attempts in ((urllib.error.URLError(TimeoutError('timed out')),3),
                (urllib.error.URLError(ssl.SSLCertVerificationError('certificate verify failed')),1)):
            calls.clear()
            def fail_open(url,**kwargs):calls.append(kwargs);raise error
            urllib.request.urlopen=fail_open
            try:get(ORIGIN+'manifest.json')
            except (OSError,urllib.error.URLError):require(len(calls)==expected_attempts,'Wrong HTTP retry count');checks+=1
            else:raise AssertionError('Failed HTTPS accepted')
        calls.clear()
        class Redirect(Response):
            def geturl(self):return ORIGIN+'redirected.json'
        def redirect_open(url,**kwargs):calls.append(kwargs);return Redirect()
        urllib.request.urlopen=redirect_open
        try:get(ORIGIN+'manifest.json')
        except RuntimeError:require(len(calls)==1,'Redirect was retried');checks+=1
        else:raise AssertionError('Redirect accepted')
        calls.clear()
        try:get(ORIGIN+'manifest.json',deadline=time.monotonic()-1)
        except RuntimeError:require(not calls,'Expired deadline opened HTTP');checks+=1
        else:raise AssertionError('Expired deadline accepted')
    finally:
        urllib.request.urlopen,time.sleep=original_open,original_sleep
    result=dict(passed=True,checks=checks,server_contacted=False,accounts_created=0,remote_mutations=0)
    save(OUT/'deployment-tools-self-test.json',result);print(json.dumps(result));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',help='Authorize SSH upload, backup and atomic client manifest publication')
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    require(not (args.execute and args.self_test),'Self-test cannot execute publication')
    if args.self_test:self_test()
    else:publish(args.execute)
