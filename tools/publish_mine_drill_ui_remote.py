"""Scoped .1 -> .2 mine hover and native icon rendering hotfix publication.

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

REPORT_ROOT = ROOT / 'reports/mine-drill-ui-20261010'
DEPLOYMENT = REPORT_ROOT / 'deployment'
BASELINE = REPORT_ROOT / 'baseline/manifest.json'
PREVIOUS_VERSION = '2026.10.10.1'
VERSION = '2026.10.10.2'
MANIFEST_SHA = 'c3171a2c47df2c872306072a34878e81065a67d010c1f45f0779273079fa9dc9'
BASELINE_RECORDS = 6544
SILVER_SHA = 'c8849a2997909c9ad6e09c674e67a641de7604aec2ddb829e4ee4187b87a972c'
SILVER_BYTES = 8004096
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
 if set(p)!={'schema','previous_version','version','baseline_manifest_sha256','selection','native_review','files'} or type(p['schema'])is not int or p['schema']!=1 or p['previous_version']!=PREVIOUS_VERSION or p['version']!=VERSION or p['baseline_manifest_sha256']!=MANIFEST_SHA:raise ValueError('Unknown reviewed package metadata')
 if p['selection']!={'fix':'battle-ui-quality-and-mine-hover'}:raise ValueError('Package differs from requested battle UI fixes')
 native_review_identity(p['native_review'])
 if not isinstance(p['files'],list) or not 1<=len(p['files'])<=256:raise ValueError('Package record count exceeds explicit scope')
 seen=set();kinds=set();total=0
 for item in p['files']:
  if set(item)!={'path','source','sha256','size','kind'}:raise ValueError('Unknown resource package field')
  name=safe_target(item['path']);safe_target(item['source']);key=name.casefold()
  if key in seen:raise ValueError('Duplicate/case-colliding resource package path')
  seen.add(key);kind=item['kind'];kinds.add(kind);limit=4*1024*1024
  if kind=='native':
   if name!='silver.dll':raise ValueError('Only Silver native client patch accepted')
   limit=SILVER_BYTES+512*1024
  elif kind=='icon_image':
   if not name.startswith('base/ui-hd/') or name.startswith('base/ui-hd/fonts/') or not name.endswith('.png'):raise ValueError('PNG path exceeds requested icon/button scope')
  else:raise ValueError('Unreviewed resource kind')
  if type(item['size'])is not int or not 1<=item['size']<=limit or not isinstance(item['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',item['sha256']):raise ValueError('Invalid reviewed resource identity')
  if kind=='native' and not SILVER_BYTES<=item['size']<=limit:raise ValueError('Native candidate size exceeds bounded allowance')
  total+=item['size']
 if 'native' not in kinds or sum(x['kind']=='native' for x in p['files'])!=1 or total>64*1024*1024:raise ValueError('Incomplete or oversized reviewed resource package')
 if any(str(parent).casefold() in seen for item in p['files'] for parent in PurePosixPath(item['path']).parents if str(parent)!='.'):raise ValueError('Resource file/directory prefix collision')
 return p

def native_review_identity(review):
 if not isinstance(review,dict) or set(review)!={'changes','appended_size','appended_sha256'} or not isinstance(review['changes'],list) or not 1<=len(review['changes'])<=128:raise ValueError('Explicit reviewed native change ranges required')
 end=0;total=0
 for span in review['changes']:
  if not isinstance(span,dict) or set(span)!={'offset','size','source_sha256','candidate_sha256','purpose'}:raise ValueError('Unknown native range metadata')
  at,size=span['offset'],span['size']
  if type(at)is not int or type(size)is not int or at<end or size<1 or at+size>SILVER_BYTES or not isinstance(span['purpose'],str) or not 1<=len(span['purpose'])<=160:raise ValueError('Invalid/overlapping native range')
  if any(not isinstance(span[k],str) or not re.fullmatch('[a-f0-9]{64}',span[k]) for k in ('source_sha256','candidate_sha256')):raise ValueError('Native range hashes required')
  end=at+size;total+=size
 if total>65536 or type(review['appended_size'])is not int or not 0<=review['appended_size']<=512*1024 or not isinstance(review['appended_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',review['appended_sha256']):raise ValueError('Reviewed native range/append allowance exceeded')
 return review

def pe_layout(raw):
 # Validate the complete mapped x86 DLL, not merely the RVAs queried by the
 # preservation checks. An append must be described by the final section.
 if len(raw)<0x100 or raw[:2]!=b'MZ':raise ValueError('Native image is not PE')
 header=struct.unpack_from('<I',raw,0x3c)[0]
 if header<0x40 or header+24>len(raw) or raw[header:header+4]!=b'PE\0\0':raise ValueError('Invalid PE header boundary')
 machine,count=struct.unpack_from('<HH',raw,header+4);optional_size=struct.unpack_from('<H',raw,header+20)[0];optional=header+24
 if machine!=0x14c or not 1<=count<=32 or optional_size!=224 or optional+optional_size>len(raw) or struct.unpack_from('<H',raw,optional)[0]!=0x10b or struct.unpack_from('<I',raw,optional+28)[0]!=0x400000:raise ValueError('Expected fixed-base x86 PE32 DLL')
 section_alignment,file_alignment=struct.unpack_from('<II',raw,optional+32)
 if not 0x200<=file_alignment<=0x10000 or file_alignment&(file_alignment-1) or section_alignment<file_alignment or section_alignment&(section_alignment-1):raise ValueError('Invalid PE alignments')
 image_size,headers_size=struct.unpack_from('<II',raw,optional+56);table=optional+optional_size
 if table+count*40>headers_size or headers_size>len(raw) or headers_size%file_alignment or len(raw)%file_alignment:raise ValueError('Invalid PE headers/file alignment')
 sections=[];physical=[];virtual=[]
 for index in range(count):
  at=table+index*40;virtual_size,rva,raw_size,offset=struct.unpack_from('<IIII',raw,at+8)
  if not virtual_size or rva<headers_size or rva%section_alignment or raw_size%file_alignment:raise ValueError('Invalid PE section geometry')
  if raw_size:
   if offset<headers_size or offset%file_alignment or offset+raw_size>len(raw):raise ValueError('PE section raw range exceeds file')
   physical.append((offset,offset+raw_size,index))
  elif offset!=0:raise ValueError('Empty PE raw section has an unexpected offset')
  mapped_size=(max(virtual_size,raw_size)+section_alignment-1)&~(section_alignment-1)
  if rva+mapped_size>0xffffffff:raise ValueError('PE virtual section overflows address space')
  virtual.append((rva,rva+mapped_size,index));sections.append(dict(at=at,virtual_size=virtual_size,rva=rva,raw_size=raw_size,offset=offset,header=raw[at:at+40]))
 physical.sort();virtual.sort()
 if not physical or any(a[1]>b[0] for a,b in zip(physical,physical[1:])) or any(a[1]>b[0] for a,b in zip(virtual,virtual[1:])):raise ValueError('Overlapping PE section ranges')
 if physical[0][0]!=headers_size or any(a[1]!=b[0] for a,b in zip(physical,physical[1:])) or physical[-1][1]!=len(raw) or physical[-1][2]!=count-1:raise ValueError('PE gaps/overlay or unmapped appended bytes refused')
 if image_size!=virtual[-1][1] or virtual[-1][2]!=count-1:raise ValueError('PE SizeOfImage does not match mapped final section')
 entry=struct.unpack_from('<I',raw,optional+16)[0]
 if not any(s['rva']<=entry<s['rva']+min(s['virtual_size'],s['raw_size']) and struct.unpack_from('<I',s['header'],36)[0]&0x20000000 for s in sections):raise ValueError('PE entry point is outside an executable mapped section')
 return dict(header=header,optional=optional,optional_size=optional_size,table=table,sections=sections,image_size=image_size,section_alignment=section_alignment,file_alignment=file_alignment)

def native_structure_preserved(source,candidate,appended_size):
 a,b=pe_layout(source),pe_layout(candidate)
 if a['header']!=b['header'] or source[0x3c:0x40]!=candidate[0x3c:0x40] or source[a['header']:a['optional']]!=candidate[b['header']:b['optional']]:raise ValueError('PE signature/COFF header properties changed')
 # Preserve entry point, preferred base, alignments, subsystem, imports,
 # exports, relocation and resource directories, and all other optional fields.
 ao,bo=a['optional'],b['optional']
 if source[ao:ao+56]!=candidate[bo:bo+56] or source[ao+60:ao+a['optional_size']]!=candidate[bo+60:bo+b['optional_size']]:raise ValueError('Fixed PE optional header properties changed')
 for prior,after in zip(a['sections'][:-1],b['sections'][:-1]):
  if prior['header']!=after['header']:raise ValueError('Earlier PE section header changed')
 prior,after=a['sections'][-1],b['sections'][-1]
 if prior['header'][:8]!=after['header'][:8] or prior['header'][12:16]!=after['header'][12:16] or prior['header'][20:]!=after['header'][20:]:raise ValueError('Final PE section identity/address/flags changed')
 if prior['virtual_size']!=prior['raw_size'] or after['virtual_size']!=prior['virtual_size']+appended_size or after['raw_size']!=prior['raw_size']+appended_size:raise ValueError('Final PE raw/virtual extension differs from reviewed append')
 expected=(after['rva']+after['virtual_size']+a['section_alignment']-1)&~(a['section_alignment']-1)
 if b['image_size']!=expected:raise ValueError('PE SizeOfImage differs from aligned reviewed append')
 return dict(sections=len(a['sections']),same_section_count=True,fixed_optional_header_preserved=True,earlier_section_headers_preserved=True,final_section_append_mapped=True,size_of_image=b['image_size'],file_alignment=b['file_alignment'],section_alignment=b['section_alignment'])

def native_preserved(source,candidate,review):
 native_review_identity(review)
 cursor=0
 for span in review['changes']:
  at,size=span['offset'],span['size']
  if source[cursor:at]!=candidate[cursor:at]:raise ValueError('Unreviewed native bytes changed outside declared ranges')
  if hashlib.sha256(source[at:at+size]).hexdigest()!=span['source_sha256'] or hashlib.sha256(candidate[at:at+size]).hexdigest()!=span['candidate_sha256']:raise ValueError('Native range differs from exact review')
  cursor=at+size
 if source[cursor:]!=candidate[cursor:len(source)]:raise ValueError('Unreviewed trailing existing native bytes changed')
 appended=candidate[len(source):]
 if len(appended)!=review['appended_size'] or hashlib.sha256(appended).hexdigest()!=review['appended_sha256']:raise ValueError('Native appended payload differs from review')
 structure=native_structure_preserved(source,candidate,review['appended_size'])
 for marker in (b'TIO-independent-ui-scale-v1',b'TIO-ui-scale-controls-v1',b'TIO-portrait-512-preview-v1'):
  if candidate.count(marker)!=1:raise ValueError('Published12 UI/portrait marker missing or duplicated')
 for va,size in AUTH_SPANS:
  if pe_at(candidate,va-0x400000,size)!=pe_at(source,va-0x400000,size):raise ValueError('Original native authentication function changed')
 changed=sum(a!=b for a,b in zip(source,candidate))
 if changed>65536:raise ValueError('Native patch exceeds reviewed changed-byte allowance')
 return dict(changed_existing_bytes=changed,appended_bytes=len(candidate)-len(source),declared_existing_ranges=len(review['changes']),all_undeclared_native_bytes_preserved=True,auth_functions_preserved=len(AUTH_SPANS),pe_structure=structure)

def blob_identity(item,raw,source=None,native_review=None):
 if hashlib.sha256(raw).hexdigest()!=item['sha256'] or len(raw)!=item['size']:raise ValueError('Blob differs from the reviewed exact identity')
 kind=item['kind']
 if kind=='native':
  if source is None or (hashlib.sha256(source).hexdigest(),len(source))!=(SILVER_SHA,SILVER_BYTES):raise ValueError('Trusted published1 native source required')
  if item['sha256']==SILVER_SHA:raise ValueError('Native candidate is unchanged')
  return native_preserved(source,raw,native_review)
 if kind=='icon_image':
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
 return {}

def manifest_transition(old,new,package):
 if hashlib.sha256(old).hexdigest()!=MANIFEST_SHA:raise ValueError('Exact hosted1 manifest required')
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
        raise ValueError('Use only a reviewed reports/mine-drill-ui-20261010/client package')
    raw=package_path.read_bytes();package=package_identity(raw,expected_sha or sha(raw))
    old=Path(baseline).read_bytes()
    if sha(old)!=MANIFEST_SHA:raise ValueError('Exact inspected hosted1 manifest required')
    source_native=Path(baseline).parent.joinpath('silver.dll').read_bytes()
    payloads={}
    for item in package['files']:
        candidate=package_path.parent/item['source']
        if not no_symlinks(candidate) or not candidate.resolve().is_relative_to(package_path.parent.resolve()):
            raise ValueError('Source exceeds its reviewed regular package directory')
        data=candidate.read_bytes();blob_identity(item,data,source_native if item['kind']=='native' else None,package['native_review'])
        payloads[item['path']]=data
    return package,payloads


def make_payload(package_path, package_sha, action, baseline=BASELINE, before_inspect=None):
    if action not in ('inspect','apply'):
        raise ValueError('Unknown publication operation')
    package_path=Path(package_path)
    if not no_symlinks(package_path) or not package_path.resolve().is_relative_to(REPORT_ROOT/'client'):
        raise ValueError('Use only a reviewed reports/mine-drill-ui-20261010/client package')
    package,payloads=load_package(package_path,package_sha,baseline)
    package_raw=package_path.read_bytes()
    if sha(package_raw)!=package_sha:raise ValueError('Package changed during resource loading')
    old=Path(baseline).read_bytes()
    if sha(old)!=MANIFEST_SHA:
        raise ValueError('Exact inspected hosted1 manifest required')
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
        expected=dict(state=inspected['guards'],inspected_utc=inspected['verified_utc'],account_credentials_sha256=inspected['health']['account_credentials_sha256'])
    return dict(action=action,package_blob=base64.b64encode(package_raw).decode('ascii'),package_sha256=package_sha,
                updates=updates,before_manifest=base64.b64encode(old).decode('ascii'),after_manifest=base64.b64encode(new).decode('ascii'),
                after_manifest_sha256=sha(new),expected_guards=expected)


# Only the earlier publisher's read-only guards and atomic fs primitives are
# reused. Its previous transition, backup and execute implementations are not.
REMOTE = SCREEN_REMOTE.split('def transition(p):')[0] + '\nfrom pathlib import PurePosixPath\nimport struct,zlib\nfrom xml.etree import ElementTree\n' + (
    f'MANIFEST_SHA={MANIFEST_SHA!r}\nPREVIOUS_VERSION={PREVIOUS_VERSION!r}\nVERSION={VERSION!r}\nBASELINE_RECORDS={BASELINE_RECORDS}\n'
    f'SILVER_SHA={SILVER_SHA!r}\nSILVER_BYTES={SILVER_BYTES}\nTI_SHA={TI_SHA!r}\nTI_BYTES={TI_BYTES}\nAUTH_SPANS={AUTH_SPANS!r}\n'
) + __import__('tools.publish_ui_modernization_remote',fromlist=['VALIDATION']).VALIDATION.split('def preserved_native')[0] + VALIDATION + r'''

def guards():
 directory(DOWNLOADS)
 # Inspect and preserve the actual launcher inventory; stale earlier release
 # constants must never stand in for current hosting evidence.
 launchers={path.name:state(path) for path in sorted(DOWNLOADS.glob('TIO-Launcher*.exe'))}
 if 'TIO-Launcher.exe' not in launchers:raise RuntimeError('Actual hosting launcher missing')
 return dict(services=services(),launchers=launchers,configuration={str(path):state(path) for path in CONFIGS},game_code=code_states())

def database(path):
 regular(path)
 with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=15)) as db:
  db.execute('BEGIN')
  if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('Hosted SQLite integrity failed')
  rows={tuple(row) for row in db.execute('SELECT login,salt,digest,iterations FROM accounts')}
  encoded=json.dumps(sorted(rows),sort_keys=True,separators=(',',':'),default=lambda value:value.hex()).encode()
  return rows,dict(integrity='ok',accounts=len(rows),account_credentials_sha256=sha(encoded),checkpoints=db.execute('SELECT count(*) FROM battle_checkpoints').fetchone()[0],settlement_jobs=db.execute('SELECT count(*) FROM battle_settlement_jobs').fetchone()[0],active_gameplay_updates_allowed=True)

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
  details[name]=blob_identity(item,raw,sources.get(name) if item['kind']=='native' else None,package['native_review']);raws[name]=raw
 if state(LIVE/'blobs'/TI_SHA)!=dict(sha256=TI_SHA,size=TI_BYTES,uid=0,gid=0,mode=0o644):raise RuntimeError('Pinned TI blob differs')
 scope['resources']=details
 return old,new,sources,raws,scope

def filtered(member):
 return None if '__pycache__' in member.name.split('/') or member.name.endswith('.pyc') else member

def backup(old,sources,before):
 directory(PRIVATE)
 folder=Path(tempfile.mkdtemp(prefix='tio-before-mine-drill-ui-fix-',dir=PRIVATE));folder.chmod(0o700)
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
 saved_rows,saved_health=database(folder/'reservation.sqlite3')
 receipt=dict(created_utc=datetime.now(timezone.utc).isoformat(),sqlite_integrity='ok',accounts_in_backup=saved_accounts,account_credentials_sha256=saved_health['account_credentials_sha256'],files=files)
 private_json(folder/'backup-manifest.json',receipt)
 sync(PRIVATE)
 return folder,receipt

def execute(p):
 if p.get('action')=='snapshot':return snapshot(p)
 old,new,sources,raws,scope=transition(p);before=guards();ids,health=database(DB)
 if len(ids)<202:raise RuntimeError('Hosted accounts below inspected baseline')
 identities={name:dict(sha256=sha(raw),size=len(raw),kind=p['updates'][name]['kind']) for name,raw in raws.items()}
 if p['action']=='inspect':
  if regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:raise RuntimeError('Hosted guards changed during read-only inspection')
  return dict(passed=True,operation='inspect',remote_mutations=0,version=PREVIOUS_VERSION,package_sha256=p['package_sha256'],candidates=identities,manifest_sha256=sha(old),health=health,guards=before,patch_scope=scope,verified_utc=datetime.now(timezone.utc).isoformat())
 expected=p['expected_guards']
 if not isinstance(expected,dict) or set(expected)!={'state','inspected_utc','account_credentials_sha256'} or expected['state']!=before:raise RuntimeError('Hosted guards differ from final reviewed inspect')
 if expected['account_credentials_sha256']!=health['account_credentials_sha256']:raise RuntimeError('Hosted account identities/credentials changed since final inspected evidence')
 elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(expected['inspected_utc'])).total_seconds()
 if not 0<=elapsed<=900:raise RuntimeError('Final inspected hosting evidence is not fresh')
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
   account_credentials_sha256_before=health['account_credentials_sha256'],account_credentials_sha256_backup=receipt['account_credentials_sha256'],account_credentials_sha256_after=after_health['account_credentials_sha256'],
   health=after_health,guards=before,other_client_records_preserved=True,seed_records_preserved=True,ti_preserved=True,launcher_preserved=True,
   code_and_config_preserved=True,services_unchanged=True,server_restarted=False,database_written=False,database_gameplay_changes_allowed=True,local_player_data_uploaded=False)
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
    bootstrap="import base64,zlib;exec(compile(zlib.decompress(base64.b64decode("+repr(base64.b64encode(zlib.compress(REMOTE.encode('utf-8'))).decode('ascii'))+")),'scoped-battle-ui-publisher','exec'))"
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=15',
                           'root@185.184.42.88','/usr/bin/python3 -c '+shlex.quote(bootstrap)],input=json.dumps(payload),
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
        raise ValueError('Use a new reports/mine-drill-ui-20261010/deployment evidence path')
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
