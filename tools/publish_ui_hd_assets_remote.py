"""Scoped .12 -> .13 publication of reviewed A icons / Roboto Condensed assets.

--snapshot and --inspect are read-only. Only --apply writes hosting, after a
fresh online SQLite/code/config/manifest/prior-blob backup. Every candidate
immutable blob precedes the single atomic manifest commit. No player files,
server source, service restarts, TI or launcher changes are accepted.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.publish_screen_settings_remote import REMOTE as SCREEN_REMOTE
from tools.publish_ui_modernization_remote import fetch, pe_at

REPORT_ROOT = ROOT / 'reports/ui-hd-assets'
DEPLOYMENT = REPORT_ROOT / 'deployment'
BASELINE = DEPLOYMENT / 'baseline/manifest.json'
PREVIOUS_VERSION = '2026.10.09.12'
VERSION = '2026.10.09.13'
MANIFEST_SHA = '77c984e9346f1208c84ee739ca18ebebdd45fcdc970cd4de50f618627191738d'
BASELINE_RECORDS = 6330
SILVER_SHA = '87645b946317a645552c3c2a5fcf586784d3920548288e2312dfb9ace065df4d'
SILVER_BYTES = 7823872
TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
TI_BYTES = 3935232
AUTH_SPANS = ((0x87c604,332),(0x87ce60,286),(0x87d1cc,124),(0x71fea0,160),
              (0x71e998,241),(0x87d00c,128),(0x87d400,64),(0x87d608,64),
              (0x87d8a4,64),(0x889eac,1568),(0x8a3108,168),(0x88a4cc,652),
              (0x889e3c,112),(0x87ba24,15),(0x87be58,365),(0x87bc04,397))

# These functions execute unchanged on Windows validation and Linux hosting.
VALIDATION = r'''
def same_json(a,b):
 return json.dumps(a,sort_keys=True,separators=(',',':'))==json.dumps(b,sort_keys=True,separators=(',',':'))

def safe_target(name):
 if not isinstance(name,str) or len(name)>180 or not re.fullmatch('[A-Za-z0-9_./-]+',name):raise ValueError('Unsafe client resource path')
 if name.startswith('/') or '\\' in name or ':' in name or any(x in ('','.', '..') or x.endswith('.') for x in name.split('/')) or name!=str(PurePosixPath(name)):raise ValueError('Noncanonical client resource path')
 if any(re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',x,re.I) for x in name.split('/')):raise ValueError('Windows device path refused')
 return name

def package_identity(raw,digest):
 if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest) or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Exact reviewed package SHA256 required')
 if len(raw)>1024*1024:raise ValueError('Package metadata exceeds bound')
 p=json.loads(raw)
 if set(p)!={'schema','previous_version','version','baseline_manifest_sha256','selection','files'} or type(p['schema'])is not int or p['schema']!=1 or p['previous_version']!=PREVIOUS_VERSION or p['version']!=VERSION or p['baseline_manifest_sha256']!=MANIFEST_SHA:raise ValueError('Unknown reviewed package metadata')
 if p['selection']!={'icons':'a-classic-hd','font_family':'Roboto Condensed'}:raise ValueError('Package differs from selected A icons / B font')
 if not isinstance(p['files'],list) or not 4<=len(p['files'])<=160:raise ValueError('Package record count exceeds explicit scope')
 seen=set();kinds=set();total=0
 for item in p['files']:
  if set(item)!={'path','source','sha256','size','kind'}:raise ValueError('Unknown resource package field')
  name=safe_target(item['path']);safe_target(item['source']);key=name.casefold()
  if key in seen:raise ValueError('Duplicate/case-colliding resource package path')
  seen.add(key);kind=item['kind'];kinds.add(kind);limit=4*1024*1024
  if kind=='native':
   if name!='silver.dll':raise ValueError('Only Silver native client patch accepted')
   limit=SILVER_BYTES+2*1024*1024
  elif kind=='font_atlas':
   if not name.startswith('base/ui-hd/fonts/') or not name.endswith('.png'):raise ValueError('Font atlas path exceeds resource scope')
  elif kind=='font_descriptor':
   if not name.startswith('base/ui-hd/fonts/') or not name.endswith('.xml'):raise ValueError('Font descriptor path exceeds resource scope')
  elif kind=='icon_image':
   if not name.startswith('base/ui-hd/icons/') or not name.endswith('.png'):raise ValueError('Icon path exceeds reviewed UI scope')
  elif kind=='font_source':
   if not name.startswith('base/ui-hd/fonts/') or not name.endswith('.ttf'):raise ValueError('Original font path exceeds scope')
  elif kind=='license':
   if not name.startswith('base/ui-hd/licenses/') or not name.endswith('.txt') or not any(x in PurePosixPath(name).name.casefold() for x in ('ofl','license','notice')):raise ValueError('Font license path exceeds scope')
   limit=128*1024
  else:raise ValueError('Unreviewed resource kind')
  if type(item['size'])is not int or not 1<=item['size']<=limit or not isinstance(item['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',item['sha256']):raise ValueError('Invalid reviewed resource identity')
  if kind=='native' and not SILVER_BYTES<=item['size']<=limit:raise ValueError('Native candidate size exceeds bounded allowance')
  total+=item['size']
 if not {'native','font_atlas','icon_image','license'}<=kinds or total>64*1024*1024:raise ValueError('Incomplete or oversized selected resource package')
 if any(str(parent).casefold() in seen for item in p['files'] for parent in PurePosixPath(item['path']).parents if str(parent)!='.'):raise ValueError('Resource file/directory prefix collision')
 return p

def native_preserved(source,candidate):
 if pe_at(candidate,0x823000,0xb000)!=pe_at(source,0x823000,0xb000):raise ValueError('Complete published11/12 Screen/UI/portrait payload changed')
 for rva,size in ((0x483816,8),(0x483844,6),(0x483924,7)):
  if pe_at(candidate,rva,size)!=pe_at(source,rva,size):raise ValueError('Published11 Screen Apply hook changed')
 for marker in (b'TIO-independent-ui-scale-v1',b'TIO-ui-scale-controls-v1',b'TIO-portrait-512-preview-v1'):
  if candidate.count(marker)!=1:raise ValueError('Published12 UI/portrait marker missing or duplicated')
 for va,size in AUTH_SPANS:
  if pe_at(candidate,va-0x400000,size)!=pe_at(source,va-0x400000,size):raise ValueError('Original native authentication function changed')
 changed=sum(a!=b for a,b in zip(source,candidate))
 if changed>131072:raise ValueError('Native patch exceeds reviewed changed-byte allowance')
 return dict(changed_existing_bytes=changed,appended_bytes=len(candidate)-len(source),published11_12_payload_bytes_preserved=0xb000,auth_functions_preserved=len(AUTH_SPANS))

def blob_identity(item,raw,source=None):
 if hashlib.sha256(raw).hexdigest()!=item['sha256'] or len(raw)!=item['size']:raise ValueError('Blob differs from the reviewed exact identity')
 kind=item['kind']
 if kind=='native':
  if source is None or (hashlib.sha256(source).hexdigest(),len(source))!=(SILVER_SHA,SILVER_BYTES):raise ValueError('Trusted published12 native source required')
  if item['sha256']==SILVER_SHA:raise ValueError('Native candidate is unchanged')
  return native_preserved(source,raw)
 if kind in ('font_atlas','icon_image'):
  if len(raw)<45 or raw[:8]!=b'\x89PNG\r\n\x1a\n' or raw[8:16]!=b'\0\0\0\rIHDR':raise ValueError('Reviewed image is not a PNG')
  width,height=struct.unpack_from('>II',raw,16)
  if not 1<=width<=8192 or not 1<=height<=8192 or raw[-12:]!=b'\0\0\0\0IEND\xaeB`\x82':raise ValueError('PNG geometry or final chunk invalid')
  offset=8;ihdr=0;iend=0
  while offset<len(raw):
   if offset+12>len(raw):raise ValueError('Truncated PNG chunk')
   size=struct.unpack_from('>I',raw,offset)[0];end=offset+12+size
   if end>len(raw) or zlib.crc32(raw[offset+4:offset+8+size])&0xffffffff!=struct.unpack_from('>I',raw,offset+8+size)[0]:raise ValueError('PNG chunk checksum differs')
   tag=raw[offset+4:offset+8];ihdr+=tag==b'IHDR';iend+=tag==b'IEND';offset=end
  if ihdr!=1 or iend!=1:raise ValueError('Repeated PNG image boundary')
  return dict(width=width,height=height)
 if kind=='font_descriptor':
  if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('XML external declarations refused')
  ElementTree.fromstring(raw)
 if kind=='font_source' and raw[:4] not in (b'\0\1\0\0',b'OTTO'):raise ValueError('Original font source is not TTF/OpenType')
 if kind=='license':
  text=raw.decode('utf-8-sig')
  if 'SIL OPEN FONT LICENSE' not in text or 'Version 1.1' not in text:raise ValueError('Roboto Condensed OFL notice required')
 return {}

def manifest_transition(old,new,package):
 if hashlib.sha256(old).hexdigest()!=MANIFEST_SHA:raise ValueError('Exact hosted12 manifest required')
 a,b=json.loads(old),json.loads(new)
 if type(a.get('schema'))is not int or a.get('schema')!=1 or a.get('version')!=PREVIOUS_VERSION or b.get('version')!=VERSION or set(a)!=set(b) or any(not same_json(a[k],b[k]) for k in a if k not in ('version','files')):raise ValueError('Unexpected manifest metadata transition')
 prior=a['files'];current=b['files'];updates={x['path']:x for x in package['files']}
 if len(prior)!=BASELINE_RECORDS or len({x['path'] for x in prior})!=BASELINE_RECORDS:raise ValueError('Published record baseline differs')
 lookup={x['path']:x for x in prior};folded={x['path'].casefold() for x in prior}
 for name,expected in (('silver.dll',(SILVER_SHA,SILVER_BYTES)),('ti.exe',(TI_SHA,TI_BYTES))):
  if (lookup[name]['sha256'],lookup[name]['size'],lookup[name].get('seed',False))!=(*expected,False):raise ValueError('Pinned native baseline differs')
 additions=sorted((name for name in updates if name not in lookup),key=lambda x:(x.casefold(),x))
 if len(current)!=BASELINE_RECORDS+len(additions) or [x['path'] for x in current[:BASELINE_RECORDS]]!=[x['path'] for x in prior] or [x['path'] for x in current[BASELINE_RECORDS:]]!=additions:raise ValueError('Record order/list changed beyond reviewed additions')
 changed=[]
 for previous,after in zip(prior,current):
  name=previous['path']
  if name in updates:
   u=updates[name]
   if previous.get('seed',False) or previous['sha256']==u['sha256'] or not same_json(after,dict(previous,sha256=u['sha256'],size=u['size'])):raise ValueError('Reviewed existing record changed extra fields/seed or is unchanged')
   changed.append(name)
  elif not same_json(previous,after):raise ValueError('Unreviewed client record changed')
 for after,name in zip(current[BASELINE_RECORDS:],additions):
  u=updates[name]
  if name.casefold() in folded or not same_json(after,{'path':name,'size':u['size'],'sha256':u['sha256'],'seed':False}):raise ValueError('New reviewed resource collides or carries unexpected metadata')
 if set(changed)|set(additions)!=set(updates):raise ValueError('Missing reviewed resource transition')
 return dict(changed=changed,added=additions,preserved_records=BASELINE_RECORDS-len(changed),before_records=BASELINE_RECORDS,after_records=len(current))
'''

import re, struct, zlib
from pathlib import PurePosixPath
from xml.etree import ElementTree
exec(VALIDATION)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def no_symlinks(path):
    return not any(x.is_symlink() or (hasattr(x,'is_junction') and x.is_junction()) for x in [path,*path.parents])


def load_package(package_path, expected_sha=None, baseline=BASELINE):
    """Return validated (package object, bytes by target) for owned QA staging.

    The optional expected SHA pins review/publication; schema, path/link scope,
    every exact resource identity and native regression guards always run.
    """
    package_path=Path(package_path)
    if not no_symlinks(package_path) or not package_path.resolve().is_relative_to((REPORT_ROOT/'client').resolve()):
        raise ValueError('Use only a reviewed reports/ui-hd-assets/client package')
    raw=package_path.read_bytes();package=package_identity(raw,expected_sha or sha(raw))
    old=Path(baseline).read_bytes()
    if sha(old)!=MANIFEST_SHA:raise ValueError('Exact inspected hosted12 manifest required')
    source_native=Path(baseline).parent.joinpath('silver.dll').read_bytes()
    payloads={}
    for item in package['files']:
        candidate=package_path.parent/item['source']
        if not no_symlinks(candidate) or not candidate.resolve().is_relative_to(package_path.parent.resolve()):
            raise ValueError('Source exceeds its reviewed regular package directory')
        data=candidate.read_bytes();blob_identity(item,data,source_native if item['kind']=='native' else None)
        payloads[item['path']]=data
    return package,payloads


def make_payload(package_path, package_sha, action, baseline=BASELINE, before_inspect=None):
    if action not in ('inspect','apply'):
        raise ValueError('Unknown publication operation')
    package_path=Path(package_path)
    if not no_symlinks(package_path) or not package_path.resolve().is_relative_to(REPORT_ROOT/'client'):
        raise ValueError('Use only a reviewed reports/ui-hd-assets/client package')
    package,payloads=load_package(package_path,package_sha,baseline)
    package_raw=package_path.read_bytes()
    if sha(package_raw)!=package_sha:raise ValueError('Package changed during resource loading')
    old=Path(baseline).read_bytes()
    if sha(old)!=MANIFEST_SHA:
        raise ValueError('Exact inspected hosted12 manifest required')
    manifest=json.loads(old);lookup={x['path']:x for x in manifest['files']}
    updates={}
    for item in package['files']:
        raw=payloads[item['path']]
        updates[item['path']]=dict(sha256=item['sha256'],size=item['size'],kind=item['kind'],blob=base64.b64encode(raw).decode('ascii'))
        if item['path'] in lookup:
            lookup[item['path']].update(sha256=item['sha256'],size=item['size'])
    manifest['files'] += [{'path':name,'size':updates[name]['size'],'sha256':updates[name]['sha256'],'seed':False}
                         for name in sorted(set(updates)-set(lookup),key=lambda x:(x.casefold(),x))]
    manifest['version']=VERSION
    new=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    manifest_transition(old,new,package)
    expected=None
    if action=='apply':
        if before_inspect is None:raise ValueError('Apply requires fresh exact package inspect evidence')
        inspected=json.loads(Path(before_inspect).read_bytes())
        if inspected.get('passed') is not True or inspected.get('operation')!='inspect' or inspected.get('remote_mutations')!=0 or inspected.get('package_sha256')!=package_sha or inspected.get('manifest_sha256')!=MANIFEST_SHA:
            raise ValueError('Inspect evidence differs from reviewed package/baseline')
        expected=inspected['guards']
    return dict(action=action,package_blob=base64.b64encode(package_raw).decode('ascii'),package_sha256=package_sha,
                updates=updates,before_manifest=base64.b64encode(old).decode('ascii'),after_manifest=base64.b64encode(new).decode('ascii'),
                after_manifest_sha256=sha(new),expected_guards=expected)


# Only the earlier publisher's read-only guards and atomic fs primitives are
# reused. Its previous transition, backup and execute implementations are not.
REMOTE = SCREEN_REMOTE.split('def transition(p):')[0] + '\nfrom pathlib import PurePosixPath\nimport struct,zlib\nfrom xml.etree import ElementTree\n' + (
    f'MANIFEST_SHA={MANIFEST_SHA!r}\nPREVIOUS_VERSION={PREVIOUS_VERSION!r}\nVERSION={VERSION!r}\nBASELINE_RECORDS={BASELINE_RECORDS}\n'
    f'SILVER_SHA={SILVER_SHA!r}\nSILVER_BYTES={SILVER_BYTES}\nTI_SHA={TI_SHA!r}\nTI_BYTES={TI_BYTES}\nAUTH_SPANS={AUTH_SPANS!r}\n'
) + __import__('tools.publish_ui_modernization_remote',fromlist=['VALIDATION']).VALIDATION.split('def preserved_native')[0] + VALIDATION + r'''

def database(path):
 regular(path)
 with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=15)) as db:
  db.execute('BEGIN')
  if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('Hosted SQLite integrity failed')
  rows={tuple(row) for row in db.execute('SELECT login,salt,digest,iterations FROM accounts')}
  return rows,dict(integrity='ok',accounts=len(rows),checkpoints=db.execute('SELECT count(*) FROM battle_checkpoints').fetchone()[0],settlement_jobs=db.execute('SELECT count(*) FROM battle_settlement_jobs').fetchone()[0])

def snapshot(p):
 if set(p)!={'action','expected_manifest_sha256'} or p['action']!='snapshot' or p['expected_manifest_sha256']!=MANIFEST_SHA:raise ValueError('Unknown read-only snapshot request')
 old=regular(LIVE/'manifest.json').read_bytes();manifest=json.loads(old)
 if sha(old)!=MANIFEST_SHA or manifest['version']!=PREVIOUS_VERSION or len(manifest['files'])!=BASELINE_RECORDS:raise RuntimeError('Actual hosted baseline changed')
 before=guards();rows,health=database(DB);native={}
 for name,digest,size in (('silver.dll',SILVER_SHA,SILVER_BYTES),('ti.exe',TI_SHA,TI_BYTES)):
  row=next(x for x in manifest['files'] if x['path']==name)
  if (row['sha256'],row['size'],row.get('seed',False))!=(digest,size,False):raise RuntimeError('Hosted pinned native manifest record changed')
  value=state(LIVE/'blobs'/digest)
  if value!=dict(sha256=digest,size=size,uid=0,gid=0,mode=0o644):raise RuntimeError('Actual pinned native blob changed')
  native[name]=value
 if len(rows)<202 or regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:raise RuntimeError('Hosted state changed during read-only snapshot')
 return dict(passed=True,operation='baseline_snapshot',remote_mutations=0,version=PREVIOUS_VERSION,manifest_sha256=sha(old),manifest_bytes=len(old),record_count=BASELINE_RECORDS,
  manifest_base64=base64.b64encode(old).decode('ascii'),native=native,guards=before,health=health,verified_utc=datetime.now(timezone.utc).isoformat(),database_written=False)

def transition(p):
 if set(p)!={'action','package_blob','package_sha256','updates','before_manifest','after_manifest','after_manifest_sha256','expected_guards'} or p['action'] not in ('inspect','apply'):raise ValueError('Unknown scoped resource release request')
 package_raw=base64.b64decode(p['package_blob'],validate=True);package=package_identity(package_raw,p['package_sha256'])
 old=base64.b64decode(p['before_manifest'],validate=True);new=base64.b64decode(p['after_manifest'],validate=True)
 if sha(new)!=p['after_manifest_sha256']:raise ValueError('Reviewed manifest hash differs')
 scope=manifest_transition(old,new,package);items={x['path']:x for x in package['files']}
 if set(p['updates'])!=set(items):raise ValueError('Package update inventory differs')
 directory(LIVE);directory(LIVE/'blobs')
 if regular(LIVE/'manifest.json').read_bytes()!=old:raise RuntimeError('Hosted baseline changed; refusing stale release')
 lookup={x['path']:x for x in json.loads(old)['files']};sources={};raws={};details={}
 for name,item in items.items():
  value=p['updates'][name]
  if set(value)!={'sha256','size','kind','blob'} or any(value[k]!=item[k] for k in ('sha256','size','kind')):raise ValueError('Reviewed resource identity differs')
  raw=base64.b64decode(value['blob'],validate=True)
  if name in lookup:
   source=regular(LIVE/'blobs'/lookup[name]['sha256']).read_bytes()
   if (sha(source),len(source))!=(lookup[name]['sha256'],lookup[name]['size']):raise RuntimeError('Actual prior reviewed resource blob differs')
   sources[name]=source
  details[name]=blob_identity(item,raw,sources.get(name) if item['kind']=='native' else None);raws[name]=raw
 if state(LIVE/'blobs'/TI_SHA)!=dict(sha256=TI_SHA,size=TI_BYTES,uid=0,gid=0,mode=0o644):raise RuntimeError('Pinned TI blob differs')
 scope['resources']=details
 return old,new,sources,raws,scope

def filtered(member):
 return None if '__pycache__' in member.name.split('/') or member.name.endswith('.pyc') else member

def backup(old,sources,before):
 directory(PRIVATE)
 folder=Path(tempfile.mkdtemp(prefix='tio-before-ui-hd-assets-',dir=PRIVATE));folder.chmod(0o700)
 with closing(sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True,timeout=15)) as src,closing(sqlite3.connect(folder/'reservation.sqlite3')) as dst:
  src.backup(dst)
  if dst.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('Hosted online SQLite backup integrity failed')
  saved_accounts=dst.execute('SELECT count(*) FROM accounts').fetchone()[0]
 (folder/'reservation.sqlite3').chmod(0o600);(folder/'previous-manifest.json').write_bytes(old)
 prior=folder/'previous-blobs';prior.mkdir(mode=0o700)
 for raw in sources.values():
  path=prior/sha(raw)
  if not path.exists():path.write_bytes(raw)
 with tarfile.open(folder/'previous-code.tar.gz','w:gz') as archive:
  for name in ('server','tio','tools','config','deploy','registration','requirements.txt','pyproject.toml'):
   if (GAME/name).exists():archive.add(GAME/name,arcname=name,filter=filtered)
 with tarfile.open(folder/'previous-config.tar.gz','w:gz') as archive:
  for name in ('/etc/tio-server','/etc/tio-portal','/etc/nginx/snippets/tio-updates.conf','/etc/systemd/system/tio-server.service'):
   path=Path(name)
   if path.exists():archive.add(path,arcname=name.lstrip('/'),filter=filtered)
 private_json(folder/'before.json',before)
 files={}
 for path in sorted(folder.rglob('*')):
  if path.is_file():
   path.chmod(0o600)
   with path.open('rb') as stream:os.fsync(stream.fileno())
   files[path.relative_to(folder).as_posix()]=state(path)
 sync(prior);sync(folder)
 receipt=dict(created_utc=datetime.now(timezone.utc).isoformat(),sqlite_integrity='ok',accounts_in_backup=saved_accounts,files=files)
 private_json(folder/'backup-manifest.json',receipt)
 return folder,receipt

def execute(p):
 if p.get('action')=='snapshot':return snapshot(p)
 old,new,sources,raws,scope=transition(p);before=guards();ids,health=database(DB)
 if len(ids)<202:raise RuntimeError('Hosted accounts below inspected baseline')
 identities={name:dict(sha256=sha(raw),size=len(raw),kind=p['updates'][name]['kind']) for name,raw in raws.items()}
 if p['action']=='inspect':return dict(passed=True,operation='inspect',remote_mutations=0,version=PREVIOUS_VERSION,package_sha256=p['package_sha256'],candidates=identities,manifest_sha256=sha(old),health=health,guards=before,patch_scope=scope)
 if p['expected_guards']!=before:raise RuntimeError('Hosted guards differ from final reviewed inspect')
 os.umask(0o077)
 fd=os.open(PRIVATE/'.tio-gameplay-client.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:raise RuntimeError('Baseline changed before online backup')
  folder,receipt=backup(old,sources,before)
  if regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:raise RuntimeError('Baseline changed during online backup')
  private_json(folder/'publication-journal.json',dict(version=VERSION,package_sha256=p['package_sha256'],candidates=identities,before_manifest_sha256=sha(old),after_manifest_sha256=sha(new),backup=str(folder),patch_scope=scope))
  try:
   for name,raw in raws.items():immutable(raw,LIVE/'blobs'/sha(raw))
   if guards()!=before:raise RuntimeError('Hosted guards changed before atomic manifest commit')
   atomic(new,LIVE/'manifest.json',old)
   if regular(LIVE/'manifest.json').read_bytes()!=new or guards()!=before:raise RuntimeError('Manifest/guard postpublication parity failed')
   for name,raw in raws.items():
    if regular(LIVE/'blobs'/sha(raw)).read_bytes()!=raw:raise RuntimeError('Published immutable resource blob differs')
   after_ids,after_health=database(DB)
   if not ids<=after_ids:raise RuntimeError('Hosted account identity/credentials disappeared')
   if regular(LIVE/'manifest.json').read_bytes()!=new or guards()!=before:raise RuntimeError('Hosted state changed during final verification')
  except BaseException:
   # Restore this attempt's exact prior manifest only if our result is still
   # current. Never restore player data or overwrite a concurrent release.
   if regular(LIVE/'manifest.json').read_bytes()==new:atomic(old,LIVE/'manifest.json',new)
   raise
  report=dict(passed=True,operation='publish',version=VERSION,previous_version=PREVIOUS_VERSION,package_sha256=p['package_sha256'],backup=str(folder),candidates=identities,
   manifest_sha256=sha(new),timestamp_utc=datetime.now(timezone.utc).isoformat(),patch_scope=scope,changed=scope['changed'],added=scope['added'],
   accounts_before=len(ids),accounts_in_backup=receipt['accounts_in_backup'],accounts_after=len(after_ids),account_identities_and_credentials_preserved=True,
   health=after_health,guards=before,other_client_records_preserved=True,seed_records_preserved=True,ti_preserved=True,launcher_preserved=True,
   code_and_config_preserved=True,services_unchanged=True,server_restarted=False,database_written=False,local_player_data_uploaded=False)
  try:private_json(folder/'publication.json',report)
  except BaseException:
   if regular(LIVE/'manifest.json').read_bytes()==new:atomic(old,LIVE/'manifest.json',new)
   raise
  return report
 finally:os.close(fd)

if __name__=='__main__':
 if os.geteuid()!=0:raise PermissionError('Use only the configured hosting root')
 print(json.dumps(execute(json.load(sys.stdin))))
'''


def invoke(payload):
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=15',
                           'root@185.184.42.88','/usr/bin/python3 -c '+shlex.quote(REMOTE)],input=json.dumps(payload),
                          text=True,capture_output=True,timeout=240)
    if result.returncode:
        raise RuntimeError('Scoped HD resource operation failed; private SSH output suppressed')
    return json.loads(result.stdout)


def baseline_snapshot():
    report=invoke(dict(action='snapshot',expected_manifest_sha256=MANIFEST_SHA))
    old=base64.b64decode(report.pop('manifest_base64'),validate=True)
    public=fetch('manifest.json',4*1024*1024)
    if old!=public or sha(old)!=MANIFEST_SHA:
        raise ValueError('Trusted HTTPS and actual SSH manifest differ')
    folder=BASELINE.parent
    folder.mkdir(parents=True,exist_ok=True)
    for name,raw in [('manifest.json',old),*[(name,fetch('blobs/'+digest,size)) for name,digest,size in
                                           [('silver.dll',SILVER_SHA,SILVER_BYTES),('ti.exe',TI_SHA,TI_BYTES)]]]:
        expected={'manifest.json':(MANIFEST_SHA,len(old)),'silver.dll':(SILVER_SHA,SILVER_BYTES),'ti.exe':(TI_SHA,TI_BYTES)}[name]
        if (sha(raw),len(raw))!=expected:raise ValueError('Trusted HTTPS pinned source blob differs')
        path=folder/name
        if path.exists():
            if path.read_bytes()!=raw:raise ValueError('Existing inspected baseline differs')
        else:
            with path.open('xb') as output:output.write(raw)
    return dict(report,trusted_https=True,https_manifest_and_native_match=True,baseline_local_path=str(BASELINE))


def verify_https(payload):
    expected=base64.b64decode(payload['after_manifest'],validate=True)
    actual=fetch('manifest.json',4*1024*1024)
    if actual!=expected:raise ValueError('Public manifest differs from the complete reviewed transition')
    result={}
    for name,value in payload['updates'].items():
        raw=fetch('blobs/'+value['sha256'],value['size'])
        if (sha(raw),len(raw))!=(value['sha256'],value['size']):raise ValueError('Public reviewed resource differs')
        result[name]=dict(sha256=sha(raw),size=len(raw),kind=value['kind'])
    ti=fetch('blobs/'+TI_SHA,TI_BYTES)
    if (sha(ti),len(ti))!=(TI_SHA,TI_BYTES):raise ValueError('Public unchanged pinned TI differs')
    return dict(passed=True,remote_mutations=0,version=VERSION,trusted_https=True,manifest_sha256=sha(actual),candidates=result,ti_preserved=True,graphical_validation=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path)
    parser.add_argument('--package-sha256')
    parser.add_argument('--before-inspect',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--snapshot',action='store_true')
    group.add_argument('--inspect',action='store_true')
    group.add_argument('--apply',action='store_true')
    group.add_argument('--verify-only',action='store_true')
    args=parser.parse_args(argv);path=args.report.resolve()
    if not no_symlinks(args.report) or not path.is_relative_to(DEPLOYMENT.resolve()) or path.exists():
        raise ValueError('Use a new reports/ui-hd-assets/deployment evidence path')
    if args.snapshot:
        if args.package or args.package_sha256 or args.before_inspect:parser.error('Baseline snapshot does not use a package')
        report=baseline_snapshot();payload=None
    else:
        if not args.package or not args.package_sha256:parser.error('Exact reviewed package path and SHA required')
        payload=make_payload(args.package,args.package_sha256,'apply' if args.apply else 'inspect',before_inspect=args.before_inspect)
        report=verify_https(payload) if args.verify_only else invoke(payload)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as output:json.dump(report,output,indent=2);output.write('\n')
    if args.apply:
        https=verify_https(payload)
        with path.with_name(path.stem+'-https.json').open('x',encoding='utf-8') as output:json.dump(https,output,indent=2);output.write('\n')
    print(json.dumps(dict(passed=True,operation=report.get('operation','verify_https'),report=str(path),remote_mutations=1 if args.apply else 0,
                         version=report.get('version'),accounts=report.get('health',{}).get('accounts'),backup=report.get('backup'))))


if __name__=='__main__':
    main()
