"""Scoped .11 -> .12 client publisher for reviewed UI/portrait native patches.

Only --apply writes hosting. Silver is mandatory; TI is optional. Every other
manifest record, seed, launcher, hosted service, configuration and code file
remains exact. The complete .11 Screen Apply payload and its hooks must survive.
No local player files are read or uploaded. An uncertain result must be checked
with --verify-only; another --apply refuses the changed release baseline.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import ssl
import struct
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.publish_screen_settings_remote import REMOTE as SCREEN_REMOTE

REPORT_ROOT = ROOT / 'reports/ui-modernization'
BASELINE = REPORT_ROOT / 'baseline/manifest.json'
PREVIOUS_VERSION = '2026.10.09.11'
VERSION = '2026.10.09.12'
MANIFEST_SHA = 'b05f5ff717480e540dde4c13d152e2169861cc29d86801ee4ee591da8f079e6f'
SOURCES = {
    'silver.dll': ('7a58e792614a179cfef1920e7f2d3b1775bc573ef0c39c8dc00eef3ccf23a8a8', 7787008),
    'ti.exe': ('e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c', 3935232),
}
ORIGIN = 'https://185.184.42.88/updates/'

# Pure stdlib validation is shared literally with the Linux-side transition.
VALIDATION = r'''
def pe_at(raw,rva,size):
 if len(raw)<0x100 or raw[:2]!=b'MZ':raise ValueError('Native candidate is not PE')
 header=struct.unpack_from('<I',raw,0x3c)[0]
 if header<0x40 or header+24>len(raw) or raw[header:header+4]!=b'PE\0\0':raise ValueError('Unknown PE header')
 machine,count=struct.unpack_from('<HH',raw,header+4)
 optional_size=struct.unpack_from('<H',raw,header+20)[0];optional=header+24
 if machine!=0x14c or optional_size<0x60 or optional+optional_size>len(raw) or struct.unpack_from('<H',raw,optional)[0]!=0x10b or struct.unpack_from('<I',raw,optional+28)[0]!=0x400000:raise ValueError('Expected fixed preferred-base x86 PE')
 table=optional+optional_size
 if not 1<=count<=32 or table+count*40>len(raw):raise ValueError('Unknown PE section count')
 for index in range(count):
  at=table+index*40;virtual_size,virtual,raw_size,offset=struct.unpack_from('<IIII',raw,at+8)
  if virtual<=rva and rva+size<=virtual+raw_size:
   result=offset+rva-virtual
   if result+size>len(raw):raise ValueError('PE data exceeds file')
   return raw[result:result+size]
 raise ValueError('Native preserved region missing')

def preserved_native(name,source,candidate):
 # Verify the native host guard for either TI binary, too.
 if name=='ti.exe':
  if pe_at(candidate,0x346470,4)!=pe_at(source,0x346470,4):raise ValueError('TI Screen host guard changed')
  return
 if pe_at(candidate,0x823000,0x2000)!=pe_at(source,0x823000,0x2000):raise ValueError('Published11 Screen Apply payload must remain exact')
 for rva,size in ((0x483816,8),(0x483844,6),(0x483924,7)):
  if pe_at(candidate,rva,size)!=pe_at(source,rva,size):raise ValueError('Published11 Screen Apply hook must remain exact')
 for marker in (b'TIO-independent-ui-scale-v1',b'TIO-ui-scale-controls-v1',b'TIO-portrait-512-preview-v1'):
  if candidate.count(marker)!=1:raise ValueError('Expected complete reviewed UI/portrait patch markers')

def identity(name,raw,expected_sha,expected_bytes):
 if name not in SOURCES or not re.fullmatch('[a-f0-9]{64}',expected_sha or ''):raise ValueError('Unknown client record or missing exact reviewed SHA')
 old_sha,old_bytes=SOURCES[name]
 if type(expected_bytes)is not int or not old_bytes<=expected_bytes<=old_bytes+1024*1024:raise ValueError('Native patch size outside bounded allowance')
 if hashlib.sha256(raw).hexdigest()!=expected_sha or len(raw)!=expected_bytes or expected_sha==old_sha or raw[:2]!=b'MZ':raise ValueError('Candidate differs from exact review or is unchanged')

def manifest_transition(old,new,updates):
 if hashlib.sha256(old).hexdigest()!=MANIFEST_SHA:raise ValueError('Exact currently hosted11 manifest required')
 a,b=json.loads(old),json.loads(new)
 if a.get('schema')!=1 or a.get('version')!=PREVIOUS_VERSION or b.get('version')!=VERSION or set(a)!=set(b) or any(a[k]!=b[k] for k in a if k not in ('version','files')):raise ValueError('Unexpected manifest metadata transition')
 if set(updates) not in ({'silver.dll'},{'silver.dll','ti.exe'}):raise ValueError('Only Silver and optional TI may change')
 if len(a['files'])!=6330 or len(b['files'])!=6330 or [x['path'] for x in a['files']]!=[x['path'] for x in b['files']] or len({x['path'] for x in a['files']})!=6330:raise ValueError('Published record list/order must remain exact')
 changed=[]
 for prior,current in zip(a['files'],b['files']):
  name=prior['path']
  if name in SOURCES:
   if (prior['sha256'],prior['size'],prior.get('seed',False))!=(*SOURCES[name],False):raise ValueError('Published11 native source identity differs')
  if name in updates:
   value=updates[name]
   if set(value)!={'sha256','bytes','blob'}:raise ValueError('Unknown reviewed update metadata')
   if current!=dict(prior,sha256=value['sha256'],size=value['bytes']):raise ValueError('Reviewed native record changed extra fields')
   changed.append(name)
  elif current!=prior:raise ValueError('Unreviewed resource or seed changed')
 return changed
'''
exec(VALIDATION)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def make_payload(candidates, action, baseline=BASELINE):
    if action not in ('inspect', 'apply'):
        raise ValueError('Unknown publication action')
    if set(candidates) not in ({'silver.dll'}, {'silver.dll', 'ti.exe'}):
        raise ValueError('Provide reviewed Silver and optional TI identities')
    old = Path(baseline).read_bytes()
    if sha(old) != MANIFEST_SHA:
        raise ValueError('Exact hosted11 baseline required')
    manifest = json.loads(old)
    updates = {}
    for name, (path, expected_sha, expected_bytes) in candidates.items():
        path = Path(path)
        resolved = path.resolve()
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents) or not resolved.is_relative_to(REPORT_ROOT) or resolved.name != name:
            raise ValueError('Use reviewed regular reports/ui-modernization candidates')
        raw = resolved.read_bytes()
        identity(name, raw, expected_sha, expected_bytes)
        source = Path(baseline).parent.joinpath(name).read_bytes()
        if (sha(source), len(source)) != SOURCES[name]:
            raise ValueError('Trusted hosted11 source blob required')
        preserved_native(name, source, raw)
        if sum(x != y for x, y in zip(source, raw)) > 65536:
            raise ValueError('Native candidate exceeds bounded changed-byte allowance')
        updates[name] = dict(sha256=expected_sha, bytes=expected_bytes, blob=base64.b64encode(raw).decode('ascii'))
        record = next(row for row in manifest['files'] if row['path'] == name)
        record.update(sha256=expected_sha, size=expected_bytes)
    manifest['version'] = VERSION
    new = (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    manifest_transition(old, new, updates)
    return dict(action=action, updates=updates, before_manifest=base64.b64encode(old).decode('ascii'),
                after_manifest=base64.b64encode(new).decode('ascii'), after_manifest_sha256=sha(new))


# Reuse only the reviewed read-only guards and atomic filesystem primitives.
# The previous publisher's transition/backup/execute are never imported here.
REMOTE = SCREEN_REMOTE.split('def transition(p):')[0] + "\nimport struct\n" + (
    f"MANIFEST_SHA={MANIFEST_SHA!r}\nPREVIOUS_VERSION={PREVIOUS_VERSION!r}\nVERSION={VERSION!r}\nSOURCES={SOURCES!r}\n"
) + VALIDATION + r'''

def transition(p):
 if set(p)!={'action','updates','before_manifest','after_manifest','after_manifest_sha256'} or p['action'] not in ('inspect','apply'):raise ValueError('Unknown scoped release request')
 old=base64.b64decode(p['before_manifest'],validate=True);new=base64.b64decode(p['after_manifest'],validate=True)
 if sha(new)!=p['after_manifest_sha256']:raise ValueError('Reviewed manifest hash differs')
 changed=manifest_transition(old,new,p['updates'])
 directory(LIVE);directory(LIVE/'blobs')
 if regular(LIVE/'manifest.json').read_bytes()!=old:raise RuntimeError('Hosted baseline changed; refusing stale release')
 raws={};sources={};deltas={}
 for name,value in p['updates'].items():
  raw=base64.b64decode(value['blob'],validate=True);identity(name,raw,value['sha256'],value['bytes'])
  source=regular(LIVE/'blobs'/SOURCES[name][0]).read_bytes()
  if (sha(source),len(source))!=SOURCES[name]:raise RuntimeError('Actual hosted11 native source differs')
  preserved_native(name,source,raw)
  existing=sum(x!=y for x,y in zip(source,raw))
  if existing>65536:raise ValueError('Native patch changed-byte allowance exceeded')
  raws[name]=raw;sources[name]=source;deltas[name]=dict(changed_existing_bytes=existing,appended_bytes=len(raw)-len(source))
 return old,new,sources,raws,dict(changed=changed,preserved_records=6330-len(changed),native=deltas)

def filtered(member):
 return None if '__pycache__' in member.name.split('/') or member.name.endswith('.pyc') else member

def backup(old,sources,before):
 directory(PRIVATE)
 folder=Path(tempfile.mkdtemp(prefix='tio-before-ui-modernization-',dir=PRIVATE));folder.chmod(0o700)
 with closing(sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True,timeout=15)) as src,closing(sqlite3.connect(folder/'reservation.sqlite3')) as dst:
  src.backup(dst)
  if dst.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('Hosted online SQLite backup integrity failed')
  saved_accounts=dst.execute('SELECT count(*) FROM accounts').fetchone()[0]
 (folder/'reservation.sqlite3').chmod(0o600)
 (folder/'previous-manifest.json').write_bytes(old)
 for name,source in sources.items():(folder/name).write_bytes(source)
 with tarfile.open(folder/'previous-code.tar.gz','w:gz') as archive:
  for name in ('server','tio','tools','config','deploy','registration','requirements.txt','pyproject.toml'):
   if (GAME/name).exists():archive.add(GAME/name,arcname=name,filter=filtered)
 with tarfile.open(folder/'previous-config.tar.gz','w:gz') as archive:
  for name in ('/etc/tio-server','/etc/tio-portal','/etc/nginx/snippets/tio-updates.conf','/etc/systemd/system/tio-server.service'):
   path=Path(name)
   if path.exists():archive.add(path,arcname=name.lstrip('/'),filter=filtered)
 private_json(folder/'before.json',before)
 receipt=dict(created_utc=datetime.now(timezone.utc).isoformat(),sqlite_integrity='ok',accounts_in_backup=saved_accounts,
              files={path.name:state(path) for path in sorted(folder.iterdir()) if path.is_file()})
 private_json(folder/'backup-manifest.json',receipt)
 return folder,receipt

def execute(p):
 old,new,sources,raws,scope=transition(p)
 before=guards();ids,health=accounts()
 if len(ids)<202:raise RuntimeError('Hosted accounts fell below inspected202 baseline')
 identities={name:dict(sha256=sha(raw),bytes=len(raw)) for name,raw in raws.items()}
 if p['action']=='inspect':return dict(passed=True,operation='inspect',remote_mutations=0,client_version=PREVIOUS_VERSION,
       candidates=identities,manifest_sha256=sha(old),health=health,guards=before,patch_scope=scope,screen11_hotapply_preserved=True)
 os.umask(0o077)
 fd=os.open(PRIVATE/'.tio-gameplay-client.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:raise RuntimeError('Baseline changed before hosted backup')
  folder,receipt=backup(old,sources,before)
  if regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:raise RuntimeError('Baseline changed during hosted backup')
  private_json(folder/'publication-journal.json',dict(version=VERSION,candidates=identities,before_manifest_sha256=sha(old),
       after_manifest_sha256=sha(new),backup=str(folder),patch_scope=scope))
  try:
   # Upload every immutable candidate before exposing their manifest together.
   for name,raw in raws.items():immutable(raw,LIVE/'blobs'/sha(raw))
   if guards()!=before:raise RuntimeError('Hosted guards changed before manifest commit')
   atomic(new,LIVE/'manifest.json',old)
   if regular(LIVE/'manifest.json').read_bytes()!=new or guards()!=before:raise RuntimeError('Manifest or hosted guard postpublication parity failed')
   for name,raw in raws.items():
    if regular(LIVE/'blobs'/sha(raw)).read_bytes()!=raw:raise RuntimeError('Published immutable native blob differs')
   after_ids,after_health=accounts()
   if not ids<=after_ids:raise RuntimeError('Hosted account identity disappeared')
   if regular(LIVE/'manifest.json').read_bytes()!=new or guards()!=before:raise RuntimeError('Hosted commit changed during final account verification')
  except BaseException:
   # A failed .12 attempt may restore exactly its preceding .11 manifest only.
   # Never restore .10 or any DB, and never overwrite another publication.
   if regular(LIVE/'manifest.json').read_bytes()==new:atomic(old,LIVE/'manifest.json',new)
   raise
  report=dict(passed=True,operation='publish',version=VERSION,previous_version=PREVIOUS_VERSION,backup=str(folder),candidates=identities,
       manifest_sha256=sha(new),timestamp_utc=datetime.now(timezone.utc).isoformat(),patch_scope=scope,changed=scope['changed'],
       accounts_before=len(ids),accounts_in_backup=receipt['accounts_in_backup'],accounts_after=len(after_ids),hosted_accounts_preserved=True,
       health=after_health,guards=before,screen11_hotapply_preserved=True,other_client_records_preserved=True,seed_records_preserved=True,
       services_unchanged=True,launchers_preserved=True,code_and_config_preserved=True,server_restarted=False,database_written=False,
       local_player_data_uploaded=False)
  private_json(folder/'publication.json',report)
  return report
 finally:os.close(fd)

if __name__=='__main__':
 if os.geteuid()!=0:raise PermissionError('Run only on the existing hosting server as root')
 print(json.dumps(execute(json.load(sys.stdin))))
'''


def invoke(payload):
    result = subprocess.run(['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes',
                             '-o', 'ConnectTimeout=15', 'root@185.184.42.88',
                             '/usr/bin/python3 -c '+shlex.quote(REMOTE)],
                            input=json.dumps(payload), text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError('Scoped UI modernization remote operation failed; private output suppressed')
    return json.loads(result.stdout)


def fetch(path, maximum):
    context = ssl.create_default_context()
    context.keylog_filename = None
    url = ORIGIN+path
    request = urllib.request.Request(url, headers={'Cache-Control': 'no-cache', 'Pragma': 'no-cache'})
    with urllib.request.urlopen(request, context=context, timeout=60) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('Trusted HTTPS endpoint changed')
        raw = response.read(maximum+1)
    if len(raw) > maximum:
        raise ValueError('Trusted HTTPS response exceeds bound')
    return raw


def verify_https(payload):
    expected = base64.b64decode(payload['after_manifest'], validate=True)
    actual = fetch('manifest.json', 4*1024*1024)
    if actual != expected:
        raise ValueError('Public manifest differs from the complete reviewed transition')
    identities = {}
    for name, value in payload['updates'].items():
        raw = fetch('blobs/'+value['sha256'], value['bytes'])
        if sha(raw) != value['sha256'] or len(raw) != value['bytes']:
            raise ValueError('Public reviewed native blob differs')
        identities[name] = dict(sha256=sha(raw), bytes=len(raw))
    return dict(passed=True, version=VERSION, trusted_https=True, origin=ORIGIN,
                manifest_sha256=sha(actual), candidates=identities, graphical_validation=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--silver', type=Path, required=True)
    parser.add_argument('--silver-sha256', required=True)
    parser.add_argument('--silver-bytes', type=int, required=True)
    parser.add_argument('--ti', type=Path)
    parser.add_argument('--ti-sha256')
    parser.add_argument('--ti-bytes', type=int)
    parser.add_argument('--report', type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--inspect', action='store_true')
    group.add_argument('--apply', action='store_true')
    group.add_argument('--verify-only', action='store_true')
    args = parser.parse_args(argv)
    if any(x is not None for x in (args.ti, args.ti_sha256, args.ti_bytes)) and not all(x is not None for x in (args.ti, args.ti_sha256, args.ti_bytes)):
        parser.error('Optional TI requires its path, exact SHA256 and size together')
    report_path = args.report.resolve()
    if not report_path.is_relative_to(REPORT_ROOT) or report_path.exists() or args.report.is_symlink():
        raise ValueError('Use a new reports/ui-modernization evidence path')
    candidates = {'silver.dll': (args.silver, args.silver_sha256, args.silver_bytes)}
    if args.ti is not None:
        candidates['ti.exe'] = (args.ti, args.ti_sha256, args.ti_bytes)
    payload = make_payload(candidates, 'apply' if args.apply else 'inspect')
    report = verify_https(payload) if args.verify_only else invoke(payload)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
        output.write('\n')
    if args.apply:
        https = verify_https(payload)
        with report_path.with_name(report_path.stem+'-https.json').open('x', encoding='utf-8') as output:
            json.dump(https, output, indent=2)
            output.write('\n')
    print(json.dumps(dict(passed=True, report=str(report_path), operation=report.get('operation', 'verify_https'),
                          backup=report.get('backup'), candidates={name:dict(sha256=value['sha256'],bytes=value['bytes']) for name,value in payload['updates'].items()},
                          remote_mutations=1 if args.apply else 0)))


if __name__ == '__main__':
    main()
