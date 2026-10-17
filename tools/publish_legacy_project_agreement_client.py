"""One-file .3 -> .4 publication of the TI-REBORN native user agreement.

Snapshot and inspect are read-only. The established online SQLite/code/config
backup and immutable-blob/atomic-manifest transaction remains unchanged. No
client executable, stored acceptance, player data, code or service is modified.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FOLDER = ROOT / 'reports/user-agreement-20261012'
CLIENT = FOLDER / 'client'
BASELINE = CLIENT / 'source/manifest.json'
PREVIOUS_VERSION = '2026.10.11.3'
VERSION = '2026.10.11.4'
MANIFEST_SHA = '0ef7c3438648b41aa174d5b577737755be930e27ab2f4565f7f392cd2c472b80'
BASELINE_RECORDS = 6567
SILVER_SHA = 'e1d9435a8521881a6559dd3d724d9f5ca865a7aaa72d1707cf1669adaa3a4d80'
SILVER_BYTES = 8131072
RULES_PATH = 'base/rules.txt'
RULES_SOURCE_SHA = '77c1ca324618885a864b6c91478a9571bc54169626eb5275760fb05e8eed3e2b'
RULES_SOURCE_BYTES = 25173
FIX = 'ti-reborn-project-user-agreement'
REVIEW = CLIENT / 'agreement-review.json'
REVIEW_SHA = '95ab1e3ef903b1b1d85e11d406f56562770e21da9e2190c8851197acbf6d3963'
CANONICAL = FOLDER / 'accepted-canonical/user-agreement.json'
ACCEPTED_REVIEW = FOLDER / 'accepted-canonical/review.json'
CANONICAL_TEXT = FOLDER / 'accepted-canonical/user-agreement.ru.txt'
CANONICAL_INPUTS = {
    'accepted-canonical/user-agreement.json': '0deaddc280cbcafc25bab83e4a28dc5af045e8c7b878579dd23c22bfcce04484',
    'accepted-canonical/review.json': 'aa47c90a23d2bfc38273c7625778a9ea45654f6f767b8f3865c441aa0e8aa3e4',
    'accepted-canonical/user-agreement.ru.txt': 'db383e50f0df3314ef5b11988daa812a7436911a9574ccff8560c7c7b93c76eb',
}
NATIVE_PROOF = CLIENT / 'native-loader-proof.json'
NATIVE_PROOF_SHA = 'caa5475247e8bdd9dc1c2fa833bfcc5b1739372173750adab8729cd1608ea8b0'
DEPENDENCIES = {
    'tools/publish_mine_drill_ui_remote.py': '825ea9459caddf9450fda94c836a11bbb9d0d21d251e172adee1797344de7727',
    'tools/publish_screen_settings_remote.py': '22bda28b094be4cceb1d14a2cf1b0a4a4296966aab9a03a4f2d326935f6dbb3d',
    'tools/publish_ui_modernization_remote.py': '4e73de6c86b40c0e56e3102c416d87c85b148276da65b76f4371a29cb908f308',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def regular(path):
    return not any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
                   for p in [path, *path.parents])


def replace_once(raw, before, after):
    if raw.count(before) != 1:
        raise ValueError('Established transaction guard changed: ' + before[:80])
    return raw.replace(before, after)


def immutable(path, raw):
    if not regular(path):
        raise ValueError('Only regular report paths accepted')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('Existing immutable report differs: ' + str(path))
    else:
        with path.open('xb') as output:
            output.write(raw)


def canonical_inputs():
    for name, expected in CANONICAL_INPUTS.items():
        path=FOLDER/name
        if not regular(path) or sha(path.read_bytes())!=expected:
            raise ValueError('Accepted canonical agreement source changed: '+name)
    accepted=json.loads(ACCEPTED_REVIEW.read_bytes())
    if accepted.get('accepted_review') is not True or accepted.get('sha256')!=CANONICAL_INPUTS['accepted-canonical/user-agreement.json'] or accepted.get('native_acceptance_must_remain_original') is not True:
        raise ValueError('Accepted canonical agreement review does not match')
    return CANONICAL_INPUTS


def foundation():
    for name, expected in DEPENDENCIES.items():
        path = ROOT / name
        if not regular(path) or sha(path.read_bytes()) != expected:
            raise ValueError('Established immutable publication dependency changed: ' + name)
    spec = importlib.util.spec_from_file_location('_legacy_agreement_transaction', ROOT / 'tools/publish_mine_drill_ui_remote.py')
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    remote = base.REMOTE
    for key, value in dict(MANIFEST_SHA=MANIFEST_SHA, PREVIOUS_VERSION=PREVIOUS_VERSION,
                           VERSION=VERSION, SILVER_SHA=SILVER_SHA, SILVER_BYTES=SILVER_BYTES,
                           BASELINE_RECORDS=BASELINE_RECORDS).items():
        remote = replace_once(remote, f'{key}={getattr(base,key)!r}\n', f'{key}={value!r}\n')
        setattr(base, key, value)
    remote = replace_once(remote, "prefix='tio-before-mine-drill-ui-fix-'", "prefix='tio-before-legacy-project-agreement-client-'")
    remote = replace_once(remote,
        "if state(LIVE/'blobs'/TI_SHA)!=dict(sha256=TI_SHA,size=TI_BYTES,uid=0,gid=0,mode=0o644):raise RuntimeError('Pinned TI blob differs')",
        "if state(LIVE/'blobs'/TI_SHA)!=dict(sha256=TI_SHA,size=TI_BYTES,uid=0,gid=0,mode=0o644):raise RuntimeError('Pinned TI blob differs')\n"
        " if state(LIVE/'blobs'/SILVER_SHA)!=dict(sha256=SILVER_SHA,size=SILVER_BYTES,uid=0,gid=0,mode=0o644):raise RuntimeError('Unchanged actual published3 Silver blob differs')")
    # Validate the actual prior rules blob as well as TI/Silver in snapshots.
    remote = replace_once(remote,
        "if len(rows)<202 or regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:",
        "row=next(x for x in manifest['files'] if x['path']==RULES_PATH)\n"
        " if (row['sha256'],row['size'],row.get('seed',False))!=(RULES_SOURCE_SHA,RULES_SOURCE_BYTES,False):raise RuntimeError('Actual agreement source record changed')\n"
        " value=state(LIVE/'blobs'/RULES_SOURCE_SHA)\n"
        " if value!=dict(sha256=RULES_SOURCE_SHA,size=RULES_SOURCE_BYTES,uid=0,gid=0,mode=0o644):raise RuntimeError('Actual agreement source blob changed')\n"
        " native[RULES_PATH]=value\n"
        " if len(rows)<202 or regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:")
    definitions = ('RULES_PATH=' + repr(RULES_PATH) + '\nRULES_SOURCE_SHA=' + repr(RULES_SOURCE_SHA)
                   + '\nRULES_SOURCE_BYTES=' + repr(RULES_SOURCE_BYTES) + '\n')
    remote = replace_once(remote, 'def sha(raw):return hashlib.sha256(raw).hexdigest()',
                          definitions + '\ndef sha(raw):return hashlib.sha256(raw).hexdigest()')
    base.REMOTE = remote
    base.REPORT_ROOT = FOLDER
    base.BASELINE = BASELINE
    return base


VALIDATION = r'''
def same_json(a,b):
 return json.dumps(a,sort_keys=True,separators=(',',':'))==json.dumps(b,sort_keys=True,separators=(',',':'))

def safe_target(name):
 if not isinstance(name,str) or len(name)>180 or not re.fullmatch('[A-Za-z0-9_./-]+',name):raise ValueError('Unsafe client resource path')
 if name.startswith('/') or '\\' in name or ':' in name or any(x in ('','.', '..') or x.endswith('.') for x in name.split('/')) or name!=str(PurePosixPath(name)):raise ValueError('Noncanonical client resource path')
 if any(re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',x,re.I) for x in name.split('/')):raise ValueError('Windows device path refused')
 return name

def agreement_identity(raw):
 if (sha(raw),len(raw))!=RULES_IDENTITY:raise ValueError('Exact reviewed TI-REBORN agreement required')
 if not raw or len(raw)>65536 or raw.startswith((b'\xef\xbb\xbf',b'\xff\xfe',b'\xfe\xff')) or b'\0' in raw:raise ValueError('Native agreement encoding boundary invalid')
 text=raw.decode('cp1251',errors='strict')
 if text.encode('cp1251')!=raw or not raw.endswith(b'\r\n') or raw.replace(b'\r\n',b'').find(b'\r')>=0 or raw.replace(b'\r\n',b'').find(b'\n')>=0:raise ValueError('Native agreement must use CP1251 and exact CRLF')
 if any(ord(c)<32 and c not in '\r\n' for c in text) or any(c in text for c in ('\u2013','\u2014','\u2018','\u2019','\u201c','\u201d')):raise ValueError('Unsupported native agreement control or punctuation')
 return dict(encoding='windows-1251',crlf=True,lines=raw.count(b'\r\n'),native_crc32=zlib.crc32(raw)&0xffffffff,stored_acceptance_untouched=True)

def package_identity(raw,digest):
 if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest) or sha(raw)!=digest:raise ValueError('Exact reviewed package SHA256 required')
 if len(raw)>65536:raise ValueError('Agreement package metadata exceeds bound')
 p=json.loads(raw)
 if set(p)!={'schema','previous_version','version','baseline_manifest_sha256','selection','native_review','files'} or type(p['schema'])is not int or p['schema']!=1 or p['previous_version']!=PREVIOUS_VERSION or p['version']!=VERSION or p['baseline_manifest_sha256']!=MANIFEST_SHA:raise ValueError('Unknown reviewed agreement package metadata')
 if p['selection']!={'fix':FIX} or p['native_review'] is not None:raise ValueError('Only a text agreement update accepted')
 if not isinstance(p['files'],list) or len(p['files'])!=1:raise ValueError('Exactly one existing agreement resource required')
 item=p['files'][0]
 if not isinstance(item,dict) or set(item)!={'path','source','sha256','size','kind'}:raise ValueError('Unknown agreement package field')
 if safe_target(item['path'])!=RULES_PATH or safe_target(item['source'])!='release-'+VERSION+'/assets/'+RULES_PATH or item['kind']!='project_agreement':raise ValueError('Agreement package exceeds exact native resource scope')
 if type(item['size']) is not int or (item['sha256'],item['size'])!=RULES_IDENTITY:raise ValueError('Agreement candidate differs from exact reviewed identity')
 return p

def blob_identity(item,raw,source=None,native_review=None):
 if item['path']!=RULES_PATH or item['kind']!='project_agreement' or (item['sha256'],item['size'])!=RULES_IDENTITY or native_review is not None:raise ValueError('Unreviewed client resource refused')
 if source is None or (sha(source),len(source))!=(RULES_SOURCE_SHA,RULES_SOURCE_BYTES):raise ValueError('Exact actual prior native agreement required')
 result=agreement_identity(raw)
 prior=zlib.crc32(source)&0xffffffff
 if result['native_crc32']==prior:raise ValueError('Agreement must trigger original native reacceptance')
 return dict(result,prior_native_crc32=prior,native_reacceptance_required=True)

def manifest_transition(old,new,package):
 if sha(old)!=MANIFEST_SHA:raise ValueError('Exact actual published3 manifest required')
 a,b=json.loads(old),json.loads(new)
 if type(a.get('schema'))is not int or a.get('schema')!=1 or a.get('version')!=PREVIOUS_VERSION or b.get('version')!=VERSION or set(a)!=set(b) or any(not same_json(a[k],b[k]) for k in a if k not in ('version','files')):raise ValueError('Unexpected manifest metadata transition')
 prior,current=a['files'],b['files'];updates={x['path']:x for x in package['files']}
 if set(updates)!={RULES_PATH} or len(prior)!=BASELINE_RECORDS or len(current)!=BASELINE_RECORDS or len({x['path'] for x in prior})!=BASELINE_RECORDS or [x['path'] for x in current]!=[x['path'] for x in prior]:raise ValueError('Only one existing agreement record may change')
 lookup={x['path']:x for x in prior}
 for name,expected in (('silver.dll',(SILVER_SHA,SILVER_BYTES)),('ti.exe',(TI_SHA,TI_BYTES)),(RULES_PATH,(RULES_SOURCE_SHA,RULES_SOURCE_BYTES))):
  if (lookup[name]['sha256'],lookup[name]['size'],lookup[name].get('seed',False))!=(*expected,False):raise ValueError('Pinned published3 source record differs')
 for previous,after in zip(prior,current):
  if previous['path']==RULES_PATH:
   u=updates[RULES_PATH]
   if previous['sha256']==u['sha256'] or not same_json(after,dict(previous,sha256=u['sha256'],size=u['size'])):raise ValueError('Agreement changed extra fields or is unchanged')
  elif not same_json(previous,after):raise ValueError('Unreviewed client record changed')
 return dict(changed=[RULES_PATH],added=[],preserved_records=BASELINE_RECORDS-1,before_records=BASELINE_RECORDS,after_records=BASELINE_RECORDS)
'''


def review():
    canonical_inputs()
    if not REVIEW_SHA or not regular(REVIEW) or sha(REVIEW.read_bytes()) != REVIEW_SHA:
        raise ValueError('Final canonical agreement review must be frozen first')
    value = json.loads(REVIEW.read_bytes())
    if value['source_sha256'] != RULES_SOURCE_SHA or value['source_bytes'] != RULES_SOURCE_BYTES or not value['passed'] or value.get('canonical_review_pending') is not False:
        raise ValueError('Canonical agreement review does not match the exact published source')
    if value.get('accepted_canonical_source_pins')!=CANONICAL_INPUTS or value.get('canonical_utf8_sha256')!=CANONICAL_INPUTS['accepted-canonical/user-agreement.json']:
        raise ValueError('Native text is not tied to the accepted canonical JSON and review')
    return value


def configure():
    base = foundation()
    frozen = review()
    if not NATIVE_PROOF_SHA or not regular(NATIVE_PROOF) or sha(NATIVE_PROOF.read_bytes())!=NATIVE_PROOF_SHA:
        raise ValueError('Final native loader and original reacceptance proof required')
    native=json.loads(NATIVE_PROOF.read_bytes())
    verifier=ROOT/'tools/verify_legacy_project_agreement_native.py'
    if native.get('passed') is not True or native.get('candidate_sha256')!=frozen['candidate_sha256'] or native.get('stored_acceptance_modified') is not False or native.get('implementation_sha256')!=sha(verifier.read_bytes()) or native.get('unchanged_silver_sha256')!=SILVER_SHA:
        raise ValueError('Native agreement proof differs from accepted text/source')
    identity = frozen['candidate_sha256'], frozen['candidate_bytes']
    prefix = ('RULES_IDENTITY=' + repr(identity) + '\nFIX=' + repr(FIX) + '\n'
              + 'RULES_PATH=' + repr(RULES_PATH) + '\nRULES_SOURCE_SHA=' + repr(RULES_SOURCE_SHA)
              + '\nRULES_SOURCE_BYTES=' + repr(RULES_SOURCE_BYTES) + '\n')
    validation = prefix + VALIDATION
    remote = replace_once(base.REMOTE, base.VALIDATION, validation)
    remote = replace_once(remote,
        "details[name]=blob_identity(item,raw,sources.get(name) if item['kind']=='native' else None,package['native_review']);raws[name]=raw",
        "details[name]=blob_identity(item,raw,sources.get(name),package['native_review']);raws[name]=raw")
    compile(remote, 'legacy-project-agreement-publication', 'exec')
    base.REMOTE, base.VALIDATION = remote, validation
    exec(validation, base.__dict__)
    base.load_package = load_package
    return base


PUBLISHER = None


def publisher():
    global PUBLISHER
    if PUBLISHER is None:
        PUBLISHER = configure()
    return PUBLISHER


def load_package(package_path, expected_sha=None, baseline=BASELINE):
    base = publisher()
    package_path = Path(package_path)
    if not regular(package_path) or not package_path.resolve().is_relative_to(CLIENT) or Path(baseline).resolve() != BASELINE.resolve():
        raise ValueError('Use only the new regular immutable agreement package and baseline')
    raw = package_path.read_bytes()
    package = base.package_identity(raw, expected_sha or sha(raw))
    if not regular(BASELINE) or sha(BASELINE.read_bytes()) != MANIFEST_SHA:
        raise ValueError('Exact actual published3 manifest required')
    item = package['files'][0]
    candidate = package_path.parent / item['source']
    source = CLIENT / 'source/assets' / RULES_PATH
    if not regular(candidate) or not candidate.resolve().is_relative_to(package_path.parent.resolve()) or not regular(source):
        raise ValueError('Agreement source exceeds its regular scoped directory')
    data = candidate.read_bytes()
    base.blob_identity(item, data, source.read_bytes(), None)
    return package, {RULES_PATH: data}


def baseline_snapshot():
    base = foundation()
    result = base.baseline_snapshot()
    manifest = json.loads(BASELINE.read_bytes())
    row = next(x for x in manifest['files'] if x['path'] == RULES_PATH)
    if (row['sha256'], row['size'], row.get('seed', False)) != (RULES_SOURCE_SHA, RULES_SOURCE_BYTES, False):
        raise ValueError('Actual published3 agreement source differs')
    raw = base.fetch('blobs/' + RULES_SOURCE_SHA, RULES_SOURCE_BYTES)
    if (sha(raw), len(raw)) != (RULES_SOURCE_SHA, RULES_SOURCE_BYTES):
        raise ValueError('Trusted HTTPS agreement source differs')
    immutable(CLIENT / 'source/assets' / RULES_PATH, raw)
    if base.fetch('manifest.json', 4 * 1024 * 1024) != BASELINE.read_bytes():
        raise ValueError('Actual baseline changed while saving agreement source')
    return dict(result, agreement_source_sha256=sha(raw), agreement_source_bytes=len(raw),
                local_player_files_read=False, stored_acceptance_untouched=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot', 'inspect', 'publish', 'verify'))
    parser.add_argument('--package', type=Path, default=CLIENT / 'package.json')
    parser.add_argument('--package-sha256')
    parser.add_argument('--inspect-report', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    path = args.report.resolve()
    if path.exists() or not path.is_relative_to(CLIENT) or not regular(path):
        raise ValueError('Use a new regular scoped agreement report')
    if args.action == 'snapshot':
        result = baseline_snapshot()
    else:
        if not args.package_sha256:
            raise ValueError('Exact reviewed package SHA256 required')
        base = publisher()
        payload = base.make_payload(args.package, args.package_sha256, 'apply' if args.action == 'publish' else 'inspect',
                                    baseline=BASELINE, before_inspect=args.inspect_report)
        result = base.verify_https(payload) if args.action == 'verify' else base.invoke(payload)
    immutable(path, (json.dumps(result, indent=2) + '\n').encode('utf-8'))
    if args.action == 'publish':
        immutable(path.with_name(path.stem + '-https.json'), (json.dumps(base.verify_https(payload), indent=2) + '\n').encode('utf-8'))
    print(json.dumps({k: result.get(k) for k in ('passed', 'operation', 'version', 'backup', 'manifest_sha256')}, indent=2))


if __name__ == '__main__':
    main()
