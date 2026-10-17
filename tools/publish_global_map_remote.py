"""Scoped .2026.10.10.4 -> .5 publication of original global-map PNGs.

--prepare creates an isolated reviewed package. --inspect and --verify are
read-only on hosting. Only --apply writes after online SQLite/code/config/prior
manifest and blob backups, and commits the manifest after all immutable blobs.
No player upload, XML/runtime policy changes, TI/launcher changes or restart.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_mine_path_entry_remote as primitives
from tools.publish_screen_settings_remote import REMOTE as SCREEN_REMOTE
from tools.publish_ui_modernization_remote import fetch, pe_at

REPORT_ROOT = ROOT / "reports/global-map-integration-20261010"
DEPLOYMENT = REPORT_ROOT / "deployment"
BASELINE = REPORT_ROOT / "baseline/manifest.json"
BASELINE_CLIENT = REPORT_ROOT / "baseline/client"
CANDIDATE = REPORT_ROOT / "client/candidate"
PREVIOUS_VERSION = "2026.10.10.4"
VERSION = "2026.10.10.5"
MANIFEST_SHA = "a76ff9795f02da06064e7eb4f522e2f4dd99571f54abbc4149a5bb422cfb0232"
BASELINE_RECORDS = 6544
SILVER_SHA = "077a80c0f856a9496745c50b19ef51d31a6e85e857b2f22025cbcd60c0bed1c0"
SILVER_BYTES = 8004608
TI_SHA = primitives.TI_SHA
TI_BYTES = primitives.TI_BYTES
AUTH_SPANS = primitives.AUTH_SPANS
MAX_APPEND = 128 * 1024
NATIVE_MARKER = b"TIO-native-global-map-full-viewport-v1"
ASSET_MANIFEST_SHA = '85e29536f7caf3246129922dee8680ae4bda6a13c36bd4bc7c813fe4eff24ed6'
LAYOUT_SHA = '3efc3a786fcd1e0dd03b47cf5d0c1f7e87af5d68476c8a453213f9d7e8298efe'
CATALOG_SHA = "1ae787c49fd857dbebdff9158110c1b8e4e6b95845e8ed6b0f27663677ceec04"
PINNED_ASSETS = {
  "base/pda/global-map-v2/gm-v2-terrain.png": {
    "sha256": "1edcbd64ea3db7a2b6c7775b5a1453538a96473b8f7ddb222c68528cbce4f035",
    "size": 3738125,
    "pixels": [
      1819,
      865
    ],
    "mode": "RGB"
  },
  "base/pda/global-map-v2/gm-v2-texas.png": {
    "sha256": "71f5fc67609309d8bf15f2a5dcd9a53061659274822cc62c958c2c5075a0a958",
    "size": 2284616,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-denver.png": {
    "sha256": "862a0d773494d27e942f6ed61e01efa1ae06d03f14f2771281e86fa4cdc31919",
    "size": 2685489,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-reservation.png": {
    "sha256": "a778751c28074fe3be8ddded1b26334a4595e212a6c0e5604a378301b411ba15",
    "size": 1929629,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-military-outpost.png": {
    "sha256": "c3f0dd6d07991b885eb5db6ee202c67e293f19a16b94902e3780c2c8ecb80d3c",
    "size": 2670398,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-new-york.png": {
    "sha256": "bc48cad1333f986b8c65fa3ef567c0825ba2c8aba433d17cd8724a894bc59adc",
    "size": 2988042,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-denver-base.png": {
    "sha256": "29803f8802c67d71c0bfbcd8ca0e2ece7dc9d51be91be0a63f36efbc141afec3",
    "size": 3284372,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-military-outpost-base.png": {
    "sha256": "2397162ec0fa5e140938caa31bedfb74e1dfb0f171b077b2dc06fe52dcc28293",
    "size": 3165692,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-military-zone.png": {
    "sha256": "af04d49af2fd9a017034be344ff44bcc975d72083580cbde7fc922d65c01083d",
    "size": 2067243,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-miner-s-town.png": {
    "sha256": "fd5904d952da8526e83ac3f3810826f1b0b245584dfc43a52756a931164d077b",
    "size": 1710804,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-prison.png": {
    "sha256": "362c1ac04da8c9193c7d81f48c22798ff4a08d505e8ac867ac291ef080e07a8d",
    "size": 2841635,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-ny-base.png": {
    "sha256": "a09adb4c495c0c4beabeb2dfe250b6367745359db3fab5cbd05d544dab28508b",
    "size": 2188065,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-mz-base.png": {
    "sha256": "4a079002cf86e1601cdc07703547aaa417ab80c0bdb2f4cd6e25f09deefde538",
    "size": 2449328,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-mine-4-6.png": {
    "sha256": "4f8db410864f59678a4ad96e85fd18bc0d7a30c29eb72eff0807fb22a45acd99",
    "size": 2774793,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-mine-7-10.png": {
    "sha256": "aa2f70c8191b190aecc5697fd774a3acfd2649ebb3ac928fdae78e870e1eb7d8",
    "size": 2502908,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-mine-11-15.png": {
    "sha256": "5d3d971077849748cefdc1281a6b146a13401d947d14f350a3a4441aeb51aef3",
    "size": 3029036,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-mine-16-20.png": {
    "sha256": "873788c685704718c56b77dd61ea648040215f0713d23e390891c59423e25b2e",
    "size": 2926044,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-shooting-range.png": {
    "sha256": "79fb5137349706a46c34e79d3ffb381f155e19de58940416ddffd89e7f3864c4",
    "size": 2850329,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-detroit.png": {
    "sha256": "968fb4ae3ef96d9fa882bea6a85f6cd369a9daeff23fccf040c04fe569bc2559",
    "size": 2902269,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-training-base-4-6.png": {
    "sha256": "882bce733cc8bbe18e6ec08ddeb421175faa78f7f6c1126870e853a8f23bfb0a",
    "size": 3430562,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-training-base-7-10.png": {
    "sha256": "a1c5b4555125ab3bc44bc4ffd9a32058997dfaf06f47b2de3b714a3cbbba8762",
    "size": 2717899,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-training-base-11-15.png": {
    "sha256": "8ec96a990a3d7dfe89f88e3248c0c9cbf04428cc230f1035e09be50b957e9e30",
    "size": 2232704,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  },
  "base/pda/global-map-v2/gm-v2-training-base-16-20.png": {
    "sha256": "860a850249f6ccfbb29e773af8f18a785402bf6a78be63ecfda0b486df077f11",
    "size": 2724627,
    "pixels": [
      1254,
      1254
    ],
    "mode": "RGBA"
  }
}

# The validators below are embedded verbatim on Linux. Reuse only the prior
# publisher's safe path and full PE structure/preservation implementations.
PE_VALIDATION = primitives.VALIDATION[
    primitives.VALIDATION.index("def pe_layout("):
    primitives.VALIDATION.index("def blob_identity(")
]
SAFE_PATH_VALIDATION = primitives.VALIDATION[
    primitives.VALIDATION.index("def same_json("):
    primitives.VALIDATION.index("def package_identity(")
]
VALIDATION = SAFE_PATH_VALIDATION + r'''
def native_review_identity(review):
 if not isinstance(review,dict) or set(review)!={'changes','appended_size','appended_sha256'} or not isinstance(review['changes'],list) or not 1<=len(review['changes'])<=128:raise ValueError('Explicit reviewed native ranges required')
 end=0;total=0
 for span in review['changes']:
  if not isinstance(span,dict) or set(span)!={'offset','size','source_sha256','candidate_sha256','purpose'}:raise ValueError('Unknown native range metadata')
  at,size=span['offset'],span['size']
  if type(at)is not int or type(size)is not int or at<end or size<1 or at+size>SILVER_BYTES or not isinstance(span['purpose'],str) or not 1<=len(span['purpose'])<=160:raise ValueError('Invalid or overlapping native range')
  if any(not isinstance(span[k],str) or not re.fullmatch('[a-f0-9]{64}',span[k]) for k in ('source_sha256','candidate_sha256')):raise ValueError('Exact reviewed native range hashes required')
  end=at+size;total+=size
 if total>16384 or type(review['appended_size'])is not int or not 512<=review['appended_size']<=MAX_APPEND or review['appended_size']%512 or not isinstance(review['appended_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',review['appended_sha256']):raise ValueError('Native reviewed range or append allowance exceeded')
 return review

def package_identity(raw,digest):
 if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest) or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Exact reviewed package SHA256 required')
 if len(raw)>1024*1024:raise ValueError('Package metadata exceeds bound')
 p=json.loads(raw)
 fields={'schema','previous_version','version','baseline_manifest_sha256','selection','asset_manifest_sha256','layout_sha256','source_catalog_sha256','native_review_receipt_sha256','native_review','files'}
 if set(p)!=fields or type(p['schema'])is not int or p['schema']!=1 or p['previous_version']!=PREVIOUS_VERSION or p['version']!=VERSION or p['baseline_manifest_sha256']!=MANIFEST_SHA:raise ValueError('Unknown scoped package metadata')
 if p['selection']!={'map':'global-map-v2','pixel_edits':False,'layers':'separate-native-PNGs','world_coordinates':'preserved'}:raise ValueError('Package differs from original-PNG global map scope')
 if (p['asset_manifest_sha256'],p['layout_sha256'],p['source_catalog_sha256'])!=(ASSET_MANIFEST_SHA,LAYOUT_SHA,CATALOG_SHA):raise ValueError('Reviewed asset/layout/source catalog identity differs')
 if not isinstance(p['native_review_receipt_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',p['native_review_receipt_sha256']):raise ValueError('Exact native review receipt identity required')
 native_review_identity(p['native_review'])
 if not isinstance(p['files'],list) or len(p['files'])!=24:raise ValueError('Exactly Silver and23original PNGs required')
 seen=set();total=0
 for item in p['files']:
  if set(item)!={'path','source','sha256','size','kind'}:raise ValueError('Unknown resource package field')
  name=safe_target(item['path']);safe_target(item['source']);key=name.casefold()
  if key in seen:raise ValueError('Duplicate or case-colliding resource path')
  seen.add(key)
  if item['source']!=name:raise ValueError('Package must use exact flat candidate resource paths')
  if type(item['size'])is not int or not isinstance(item['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',item['sha256']):raise ValueError('Invalid reviewed resource identity')
  if name=='silver.dll':
   if item['kind']!='native' or not SILVER_BYTES+512<=item['size']<=SILVER_BYTES+MAX_APPEND or item['size']!=SILVER_BYTES+p['native_review']['appended_size'] or item['sha256']==SILVER_SHA:raise ValueError('Invalid reviewed Silver extension')
  elif name in PINNED_ASSETS:
   pin=PINNED_ASSETS[name];kind='terrain_png' if name.endswith('/gm-v2-terrain.png') else 'map_object_png'
   if (item['sha256'],item['size'],item['kind'])!=(pin['sha256'],pin['size'],kind):raise ValueError('Only the exact original PNG identity is accepted')
  else:raise ValueError('Resource outside Silver and23original global-map PNG scope')
  total+=item['size']
 if seen!={name.casefold() for name in {'silver.dll',*PINNED_ASSETS}} or total>96*1024*1024:raise ValueError('Incomplete or oversized global-map package')
 return p

def png_identity(raw,pin):
 if len(raw)<45 or raw[:8]!=b'\x89PNG\r\n\x1a\n' or raw[8:16]!=b'\0\0\0\rIHDR':raise ValueError('Original resource is not PNG')
 width,height=struct.unpack_from('>II',raw,16);mode='RGBA' if raw[25]==6 else 'RGB' if raw[25]==2 else None
 if [width,height]!=pin['pixels'] or mode!=pin['mode'] or raw[24]!=8 or raw[-12:]!=b'\0\0\0\0IEND\xaeB\x60\x82':raise ValueError('Original PNG dimensions or alpha format changed')
 offset=8;ihdr=0;iend=0
 while offset<len(raw):
  if offset+12>len(raw):raise ValueError('Truncated PNG chunk')
  size=struct.unpack_from('>I',raw,offset)[0];end=offset+12+size
  if end>len(raw) or zlib.crc32(raw[offset+4:offset+8+size])&0xffffffff!=struct.unpack_from('>I',raw,offset+8+size)[0]:raise ValueError('PNG checksum differs')
  tag=raw[offset+4:offset+8];ihdr+=tag==b'IHDR';iend+=tag==b'IEND';offset=end
 if ihdr!=1 or iend!=1:raise ValueError('Repeated PNG boundary')
 return dict(width=width,height=height,mode=mode,original_bytes_preserved=True)

def blob_identity(item,raw,source=None,native_review=None):
 if (hashlib.sha256(raw).hexdigest(),len(raw))!=(item['sha256'],item['size']):raise ValueError('Blob differs from exact reviewed identity')
 if item['kind']=='native':
  if source is None or (hashlib.sha256(source).hexdigest(),len(source))!=(SILVER_SHA,SILVER_BYTES):raise ValueError('Exact hosted4 Silver source required')
  result=native_preserved(source,raw,native_review)
  if raw.count(NATIVE_MARKER)!=1:raise ValueError('Expected one reviewed native global-map marker')
  return result
 pin=PINNED_ASSETS.get(item['path'])
 if pin is None or (item['sha256'],item['size'])!=(pin['sha256'],pin['size']):raise ValueError('Unreviewed image or changed original pixels')
 return png_identity(raw,pin)

def manifest_transition(old,new,package):
 if hashlib.sha256(old).hexdigest()!=MANIFEST_SHA:raise ValueError('Exact hosted4 manifest required')
 a,b=json.loads(old),json.loads(new)
 if type(a.get('schema'))is not int or a.get('schema')!=1 or a.get('version')!=PREVIOUS_VERSION or b.get('version')!=VERSION or set(a)!=set(b) or any(not same_json(a[k],b[k]) for k in a if k not in ('version','files')):raise ValueError('Unexpected manifest metadata transition')
 prior=a['files'];current=b['files'];updates={x['path']:x for x in package['files']}
 if len(prior)!=BASELINE_RECORDS or len({x['path'] for x in prior})!=BASELINE_RECORDS or len({x['path'].casefold() for x in prior})!=BASELINE_RECORDS:raise ValueError('Exact record baseline differs')
 lookup={x['path']:x for x in prior};folded={x['path'].casefold() for x in prior}
 for name,expected in (('silver.dll',(SILVER_SHA,SILVER_BYTES)),('ti.exe',(TI_SHA,TI_BYTES))):
  if (lookup[name]['sha256'],lookup[name]['size'],lookup[name].get('seed',False))!=(*expected,False):raise ValueError('Pinned native baseline differs')
 if set(updates)!={'silver.dll',*PINNED_ASSETS} or any(name in lookup or name.casefold() in folded for name in PINNED_ASSETS):raise ValueError('Exactly23new PNG additions and one Silver replacement required')
 additions=sorted(PINNED_ASSETS,key=lambda x:(x.casefold(),x))
 if len(current)!=BASELINE_RECORDS+23 or [x['path'] for x in current[:BASELINE_RECORDS]]!=[x['path'] for x in prior] or [x['path'] for x in current[BASELINE_RECORDS:]]!=additions:raise ValueError('Record order changed beyond23reviewed additions')
 for previous,after in zip(prior,current):
  if previous['path']=='silver.dll':
   u=updates['silver.dll']
   if previous.get('seed',False) or previous['sha256']==u['sha256'] or not same_json(after,dict(previous,sha256=u['sha256'],size=u['size'])):raise ValueError('Silver record changed extra fields/seed or is unchanged')
  elif not same_json(previous,after):raise ValueError('Unreviewed client record or seed changed')
 for after,name in zip(current[BASELINE_RECORDS:],additions):
  u=updates[name]
  if not same_json(after,{'path':name,'size':u['size'],'sha256':u['sha256'],'seed':False}):raise ValueError('New original PNG record carries unexpected metadata')
 return dict(changed=['silver.dll'],added=additions,preserved_records=BASELINE_RECORDS-1,before_records=BASELINE_RECORDS,after_records=len(current))
''' + PE_VALIDATION
exec(VALIDATION)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def no_symlinks(path):
    return primitives.no_symlinks(Path(path))

def _owned(path,root):
    path=Path(path)
    if not no_symlinks(path) or not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("Use only regular files inside the owned candidate/report directory")
    return path.resolve()

def _source_native(baseline):
    path=Path(baseline).parent/"client/silver.dll"
    if (sha(path.read_bytes()),path.stat().st_size)!=(SILVER_SHA,SILVER_BYTES):
        raise ValueError("Exact inspected hosted4 native baseline required")
    return path.read_bytes()

def _candidate_metadata(package_folder):
    asset_folder=Path(package_folder)/"base/pda/global-map-v2"
    for name,digest in (("manifest.json",ASSET_MANIFEST_SHA),("layout.json",LAYOUT_SHA)):
        path=_owned(asset_folder/name,package_folder)
        if sha(path.read_bytes())!=digest:raise ValueError("Prepared asset manifest/layout changed")

def normalize_native_review(document, raw):
    """Extract the reviewed range contract from the hash-pinned QA receipt."""
    if not isinstance(document,dict):raise ValueError("Native review receipt must be an object")
    for key,expected in (("source_sha256",SILVER_SHA),("source_size",SILVER_BYTES),
                         ("candidate_sha256",sha(raw)),("candidate_size",len(raw))):
        if key in document and document[key]!=expected:
            raise ValueError("Native review receipt describes a different source or candidate")
    if document.get("all_undeclared_source_bytes_unchanged",True) is not True:
        raise ValueError("Native review reports undeclared source modifications")
    source=document.get("native_review",document)
    if not isinstance(source,dict):raise ValueError("Native review ranges missing")
    fields=("offset","size","source_sha256","candidate_sha256","purpose")
    try:
        review={"changes":[{key:span[key] for key in fields} for span in source["changes"]],
                "appended_size":source["appended_size"],"appended_sha256":source["appended_sha256"]}
    except (KeyError,TypeError):
        raise ValueError("Native review ranges incomplete") from None
    return native_review_identity(review)

def load_package(package_path,expected_sha=None,baseline=BASELINE):
    package_path=_owned(package_path,REPORT_ROOT/"client")
    raw=package_path.read_bytes();package=package_identity(raw,expected_sha or sha(raw))
    if sha(Path(baseline).read_bytes())!=MANIFEST_SHA:raise ValueError("Exact hosted4 manifest baseline required")
    _candidate_metadata(package_path.parent)
    source=_source_native(baseline);payloads={}
    for item in package["files"]:
        candidate=_owned(package_path.parent/item["source"],package_path.parent)
        data=candidate.read_bytes()
        blob_identity(item,data,source if item["kind"]=="native" else None,package["native_review"])
        payloads[item["path"]]=data
    return package,payloads

def prepare_package(native,native_sha,native_bytes,review_path,review_sha,package_path=CANDIDATE/"package.json"):
    native=_owned(native,REPORT_ROOT/"client");review_path=_owned(review_path,REPORT_ROOT/"client")
    package_path=_owned(package_path,REPORT_ROOT/"client")
    if package_path.parent!=CANDIDATE.resolve():raise ValueError("Package must be inside the complete candidate root")
    raw=native.read_bytes();review_raw=review_path.read_bytes()
    if (sha(raw),len(raw))!=(native_sha,native_bytes) or sha(review_raw)!=review_sha:
        raise ValueError("Native candidate/review differs from explicit reviewed hashes")
    review=normalize_native_review(json.loads(review_raw),raw)
    _candidate_metadata(package_path.parent)
    files=[dict(path="silver.dll",source="silver.dll",sha256=native_sha,size=native_bytes,kind="native")]
    for name,pin in sorted(PINNED_ASSETS.items()):
        original=_owned(package_path.parent/name,package_path.parent).read_bytes()
        item=dict(path=name,source=name,sha256=pin["sha256"],size=pin["size"],kind="terrain_png" if name.endswith("/gm-v2-terrain.png") else "map_object_png")
        blob_identity(item,original);files.append(item)
    source=_source_native(BASELINE);blob_identity(files[0],raw,source,review)
    package=dict(schema=1,previous_version=PREVIOUS_VERSION,version=VERSION,baseline_manifest_sha256=MANIFEST_SHA,
        selection=dict(map="global-map-v2",pixel_edits=False,layers="separate-native-PNGs",world_coordinates="preserved"),
        asset_manifest_sha256=ASSET_MANIFEST_SHA,layout_sha256=LAYOUT_SHA,source_catalog_sha256=CATALOG_SHA,
        native_review_receipt_sha256=review_sha,native_review=review,files=files)
    package_raw=(json.dumps(package,indent=2)+"\n").encode()
    package_identity(package_raw,sha(package_raw))
    if package_path.exists():
        if package_path.read_bytes()!=package_raw:raise ValueError("Existing prepared package differs; use a fresh candidate review")
    target=package_path.parent/"silver.dll"
    if target!=native:target.write_bytes(raw)
    if not package_path.exists():
        with package_path.open("xb") as stream:stream.write(package_raw)
    return dict(passed=True,operation="prepare",remote_mutations=0,package=str(package_path),package_sha256=sha(package_raw),
        native_sha256=native_sha,native_bytes=native_bytes,original_png_count=23,source_pixel_edits=False,
        native_review_receipt_sha256=review_sha,layout_sha256=LAYOUT_SHA,graphical_validation=False)

def make_payload(package_path,package_sha,action,baseline=BASELINE,before_inspect=None):
    if action not in ("inspect","apply"):raise ValueError("Unknown scoped publication action")
    package,payloads=load_package(package_path,package_sha,baseline)
    package_raw=Path(package_path).read_bytes()
    if sha(package_raw)!=package_sha:raise ValueError("Package changed during loading")
    old=Path(baseline).read_bytes();manifest=json.loads(old);lookup={r["path"]:r for r in manifest["files"]}
    updates={}
    for item in package["files"]:
        raw=payloads[item["path"]]
        updates[item["path"]]=dict(sha256=item["sha256"],size=item["size"],kind=item["kind"],blob=base64.b64encode(raw).decode())
        if item["path"]=="silver.dll":lookup["silver.dll"].update(sha256=item["sha256"],size=item["size"])
    manifest["files"] += [dict(path=name,size=updates[name]["size"],sha256=updates[name]["sha256"],seed=False)
                          for name in sorted(PINNED_ASSETS,key=lambda x:(x.casefold(),x))]
    manifest["version"]=VERSION
    new=(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n").encode()
    manifest_transition(old,new,package)
    expected=None
    if action=="apply":
        if before_inspect is None:raise ValueError("Apply requires fresh exact package inspect evidence")
        inspected=json.loads(_owned(before_inspect,DEPLOYMENT).read_bytes())
        if inspected.get("passed") is not True or inspected.get("operation")!="inspect" or inspected.get("remote_mutations")!=0 or inspected.get("package_sha256")!=package_sha or inspected.get("manifest_sha256")!=MANIFEST_SHA:
            raise ValueError("Inspect evidence differs from the exact reviewed package/baseline")
        expected=dict(state=inspected["guards"],inspected_utc=inspected["verified_utc"],account_credentials_sha256=inspected["health"]["account_credentials_sha256"])
    return dict(action=action,package_blob=base64.b64encode(package_raw).decode(),package_sha256=package_sha,updates=updates,
        before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),
        after_manifest_sha256=sha(new),expected_guards=expected)

# Runtime code from the validated publisher includes actual dynamic launcher
# inventory guards, online DB backup, lock, fsync, manifest-last commit and
# manifest-only rollback conditioned on our exact current publication.
REMOTE_CONSTANTS = (
    f"MANIFEST_SHA={MANIFEST_SHA!r}\nPREVIOUS_VERSION={PREVIOUS_VERSION!r}\nVERSION={VERSION!r}\nBASELINE_RECORDS={BASELINE_RECORDS}\n"
    f"SILVER_SHA={SILVER_SHA!r}\nSILVER_BYTES={SILVER_BYTES}\nTI_SHA={TI_SHA!r}\nTI_BYTES={TI_BYTES}\nAUTH_SPANS={AUTH_SPANS!r}\n"
    f"MAX_APPEND={MAX_APPEND}\nNATIVE_MARKER={NATIVE_MARKER!r}\nASSET_MANIFEST_SHA={ASSET_MANIFEST_SHA!r}\n"
    f"LAYOUT_SHA={LAYOUT_SHA!r}\nCATALOG_SHA={CATALOG_SHA!r}\nPINNED_ASSETS={PINNED_ASSETS!r}\n"
)
PE_AT_VALIDATION = __import__("tools.publish_ui_modernization_remote",fromlist=["VALIDATION"]).VALIDATION.split("def preserved_native")[0]
REMOTE = SCREEN_REMOTE.split("def transition(p):")[0] + "\nfrom pathlib import PurePosixPath\nimport struct,zlib\n" + REMOTE_CONSTANTS + PE_AT_VALIDATION + VALIDATION + primitives.REMOTE[primitives.REMOTE.rindex("\ndef guards():"):].replace("tio-before-mine-path-entry-fix-","tio-before-global-map-v2-")

def invoke(payload):
    encoded=base64.b64encode(zlib.compress(REMOTE.encode())).decode()
    bootstrap="import base64,zlib;exec(compile(zlib.decompress(base64.b64decode("+repr(encoded)+")),'scoped-global-map-publisher','exec'))"
    result=subprocess.run(["ssh","-i",str(Path.home()/".ssh/tio_server"),"-o","BatchMode=yes","-o","ConnectTimeout=15",
        "root@185.184.42.88","/usr/bin/python3 -c "+shlex.quote(bootstrap)],input=json.dumps(payload),text=True,capture_output=True,timeout=600)
    if result.returncode:raise RuntimeError("Scoped global-map operation failed; private SSH output suppressed")
    return json.loads(result.stdout)

def verify_https(payload):
    expected=base64.b64decode(payload["after_manifest"],validate=True)
    actual=fetch("manifest.json",4*1024*1024)
    if actual!=expected:raise ValueError("Public manifest differs from the complete reviewed transition")
    result={}
    for name,value in payload["updates"].items():
        raw=fetch("blobs/"+value["sha256"],value["size"])
        if (sha(raw),len(raw))!=(value["sha256"],value["size"]):raise ValueError("Public reviewed resource differs")
        result[name]=dict(sha256=sha(raw),size=len(raw),kind=value["kind"])
    ti=fetch("blobs/"+TI_SHA,TI_BYTES)
    if (sha(ti),len(ti))!=(TI_SHA,TI_BYTES):raise ValueError("Public unchanged pinned TI differs")
    return dict(passed=True,operation="verify_https",remote_mutations=0,version=VERSION,trusted_https=True,
        manifest_sha256=sha(actual),candidates=result,ti_preserved=True,original_pngs_preserved=True,graphical_validation=False)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package",type=Path,default=CANDIDATE/"package.json")
    parser.add_argument("--package-sha256")
    parser.add_argument("--native",type=Path)
    parser.add_argument("--native-sha256")
    parser.add_argument("--native-bytes",type=int)
    parser.add_argument("--native-review",type=Path)
    parser.add_argument("--native-review-sha256")
    parser.add_argument("--before-inspect",type=Path)
    parser.add_argument("--report",type=Path,required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    for name in ("prepare","inspect","apply","verify"):group.add_argument("--"+name,action="store_true")
    args=parser.parse_args(argv);report_path=_owned(args.report,DEPLOYMENT)
    if report_path.exists():raise ValueError("Use a fresh deployment evidence file")
    payload=None
    if args.prepare:
        if any(v is None for v in (args.native,args.native_sha256,args.native_bytes,args.native_review,args.native_review_sha256)):
            parser.error("Prepare requires explicit native file/hash/size and native-review file/hash")
        report=prepare_package(args.native,args.native_sha256,args.native_bytes,args.native_review,args.native_review_sha256,args.package)
    else:
        if not args.package_sha256:parser.error("Exact reviewed package SHA required")
        payload=make_payload(args.package,args.package_sha256,"apply" if args.apply else "inspect",before_inspect=args.before_inspect)
        report=verify_https(payload) if args.verify else invoke(payload)
    report_path.parent.mkdir(parents=True,exist_ok=True)
    with report_path.open("x",encoding="utf-8") as out:json.dump(report,out,indent=2);out.write("\n")
    if args.apply:
        https=verify_https(payload)
        with report_path.with_name(report_path.stem+"-https.json").open("x",encoding="utf-8") as out:json.dump(https,out,indent=2);out.write("\n")
    print(json.dumps(dict(passed=True,operation=report["operation"],report=str(report_path),version=report.get("version"),
        package_sha256=report.get("package_sha256"),remote_mutations=1 if args.apply else 0,backup=report.get("backup"))))

if __name__=="__main__":main()

