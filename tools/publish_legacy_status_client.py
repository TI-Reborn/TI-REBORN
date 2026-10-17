"""Scoped 2026.10.11.1 -> .2 Silver and thirteen native texture publisher.

Snapshot and inspect are read-only. Publish reuses the established online
SQLite/code/config/prior-blob backup and atomic manifest transaction.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FOLDER = ROOT / 'reports/gameplay-completion/legacy-status-20261011'
BASELINE = FOLDER / 'client/source/manifest.json'
PREVIOUS_VERSION = '2026.10.11.1'
VERSION = '2026.10.11.2'
MANIFEST_SHA = '3ca0411e03b00ba814c95b197ace1176377bd29635b0b805b3bd67ab3806099b'
SILVER_SHA = '4897eb6d6af6beb587fc9b303dc6911519d90b3414ae8cca8fd1ffb698c1f082'
SILVER_BYTES = 8118784
BASELINE_RECORDS = 6567
FIX = 'legacy-server-status-and-native-degrain-assets'
INVENTORY = FOLDER / 'textures/changed-files.json'
INVENTORY_SHA = '8963f669c002640ea776ef6b89bcad51676895cf9c646b22d9eca6302a8dbe27'
CONTRACT = ROOT / 'tools/native_texture_contract.py'
CONTRACT_SHA = '493766e9c1ade33664c1e718715eab8c59fb06efe59439558dc6482bff58933e'
NATIVE = FOLDER / 'client-freshness/silver.dll'
NATIVE_SHA = '853feb6a3803078ffaf1570969c8432bce37f8c20593acbadcdb5a68f798f3a1'
NATIVE_BYTES = 8126976
NATIVE_REVIEW = FOLDER / 'client-freshness/combined-review.json'
NATIVE_REVIEW_SHA = '70fa0e69dee2ed72563ece1044ecacc42d150985b5f7c8170a2e03c047e8d3b1'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned_inventory():
    raw = INVENTORY.read_bytes()
    if sha(raw) != INVENTORY_SHA:
        raise ValueError('Immutable thirteen-texture inventory changed')
    document = json.loads(raw)
    if (document['baseline_version'], document['baseline_manifest_sha256']) != (PREVIOUS_VERSION, MANIFEST_SHA):
        raise ValueError('Texture inventory baseline changed')
    rows = document['files']
    if len(rows) != 13 or len({row['path'] for row in rows}) != 13:
        raise ValueError('Exact thirteen-texture scope required')
    return rows


def replace_once(raw, before, after):
    if raw.count(before) != 1:
        raise ValueError('Established publisher guard changed: ' + before[:80])
    return raw.replace(before, after)


def configure():
    # Load a private instance; importing this adapter must not reconfigure an
    # earlier publisher already in use by a QA tool in the same process.
    spec = importlib.util.spec_from_file_location('_legacy_status_transaction', ROOT/'tools/publish_mine_drill_ui_remote.py')
    established = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(established)
    remote = established.REMOTE
    for key, value in dict(MANIFEST_SHA=MANIFEST_SHA, PREVIOUS_VERSION=PREVIOUS_VERSION,
                           VERSION=VERSION, SILVER_SHA=SILVER_SHA,
                           SILVER_BYTES=SILVER_BYTES, BASELINE_RECORDS=BASELINE_RECORDS).items():
        remote = replace_once(remote, f'{key}={getattr(established,key)!r}\n', f'{key}={value!r}\n')
        setattr(established, key, value)
    rows = pinned_inventory()
    allowed = {row['path']: (row['original_sha256'], row['original_size'], row['sha256'], row['size']) for row in rows}
    contract_raw = CONTRACT.read_bytes()
    if sha(contract_raw) != CONTRACT_SHA:
        raise ValueError('Reviewed native texture contract changed')
    contract = contract_raw.decode('utf-8').replace('from __future__ import annotations\n', '')
    review_raw = NATIVE_REVIEW.read_bytes()
    if sha(review_raw) != NATIVE_REVIEW_SHA:
        raise ValueError('Frozen native review changed')
    prefix = ('TEXTURES=' + repr(allowed) + '\nNATIVE_IDENTITY=' + repr((NATIVE_SHA,NATIVE_BYTES))
              + '\nNATIVE_REVIEW=json.loads(' + repr(review_raw.decode('utf-8')) + ')\n' + contract + '\n')
    validation = established.VALIDATION
    validation = replace_once(validation,
        "if p['selection']!={'fix':'battle-ui-quality-and-mine-hover'}:",
        "if p['selection']!={'fix':" + repr(FIX) + "}:")
    validation = replace_once(validation,
        "native_review_identity(p['native_review'])",
        "native_review_identity(p['native_review'])\n if not same_json(p['native_review'],NATIVE_REVIEW):raise ValueError('Native review differs from exact combined freeze')")
    validation = replace_once(validation,
        "if name!='silver.dll':raise ValueError('Only Silver native client patch accepted')",
        "if name!='silver.dll' or (item['sha256'],item['size'])!=NATIVE_IDENTITY:raise ValueError('Only the exact frozen Silver patch accepted')")
    validation = replace_once(validation,
        "if not isinstance(p['files'],list) or not 1<=len(p['files'])<=256:",
        "if not isinstance(p['files'],list) or len(p['files'])!=14 or {x.get('path') for x in p['files']}!=set(TEXTURES)|{'silver.dll'}:")
    validation = replace_once(validation,
        "elif kind=='icon_image':\n   if not name.startswith('base/ui-hd/') or name.startswith('base/ui-hd/fonts/') or not name.endswith('.png'):raise ValueError('PNG path exceeds requested icon/button scope')",
        "elif kind=='native_texture':\n   if name not in TEXTURES or (item['sha256'],item['size'])!=TEXTURES[name][2:]:raise ValueError('Texture differs from exact reviewed thirteen-asset identity')")
    start = validation.index('def blob_identity(')
    end = validation.index('def manifest_transition(', start)
    validation = validation[:start] + '''def blob_identity(item,raw,source=None,native_review=None):
 if hashlib.sha256(raw).hexdigest()!=item['sha256'] or len(raw)!=item['size']:raise ValueError('Blob differs from the reviewed exact identity')
 kind=item['kind']
 if kind=='native':
  if source is None or (sha(source),len(source))!=(SILVER_SHA,SILVER_BYTES):raise ValueError('Trusted published native source required')
  if item['sha256']==SILVER_SHA:raise ValueError('Native candidate is unchanged')
  return native_preserved(source,raw,native_review)
 if kind=='native_texture':
  expected=TEXTURES.get(item['path'])
  if expected is None or (item['sha256'],item['size'])!=expected[2:]:raise ValueError('Unreviewed texture identity')
  if source is None or (sha(source),len(source))!=expected[:2]:raise ValueError('Exact hosted prior texture blob required')
  return validate_replacement(source,raw)
 raise ValueError('Unreviewed resource kind')

''' + validation[end:]
    validation = replace_once(validation,
        "if len(prior)!=BASELINE_RECORDS or len({x['path'] for x in prior})!=BASELINE_RECORDS:",
        "if set(updates)!=set(TEXTURES)|{'silver.dll'} or len(current)!=BASELINE_RECORDS or any(name not in {x['path'] for x in prior} for name in updates):raise ValueError('Only fourteen existing records may change; additions refused')\n if len(prior)!=BASELINE_RECORDS or len({x['path'] for x in prior})!=BASELINE_RECORDS:")
    validation = replace_once(validation,
        "lookup={x['path']:x for x in prior};folded={x['path'].casefold() for x in prior}",
        "lookup={x['path']:x for x in prior};folded={x['path'].casefold() for x in prior}\n for name,expected in TEXTURES.items():\n  if (lookup[name]['sha256'],lookup[name]['size'],lookup[name].get('seed',False))!=(*expected[:2],False):raise ValueError('Pinned source texture manifest record changed')")
    remote = replace_once(remote, established.VALIDATION, prefix + validation)
    remote = replace_once(remote, "prefix='tio-before-mine-drill-ui-fix-'", "prefix='tio-before-legacy-status-client-'")
    remote = replace_once(remote,
        "details[name]=blob_identity(item,raw,sources.get(name) if item['kind']=='native' else None,package['native_review']);raws[name]=raw",
        "details[name]=blob_identity(item,raw,sources.get(name),package['native_review']);raws[name]=raw")
    remote = replace_once(remote,
        "if len(rows)<202 or regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:",
        "for name,expected in TEXTURES.items():\n  row=next(x for x in manifest['files'] if x['path']==name)\n  if (row['sha256'],row['size'],row.get('seed',False))!=(*expected[:2],False):raise RuntimeError('Hosted pinned source texture record changed')\n  value=state(LIVE/'blobs'/expected[0])\n  if value!=dict(sha256=expected[0],size=expected[1],uid=0,gid=0,mode=0o644):raise RuntimeError('Actual pinned source texture blob changed')\n  native[name]=value\n if len(rows)<202 or regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:")
    compile(remote, 'legacy-status-client-publication', 'exec')
    established.REMOTE = remote
    established.VALIDATION = prefix + validation
    established.REPORT_ROOT = FOLDER
    established.BASELINE = BASELINE
    exec(established.VALIDATION, established.__dict__)
    return established


PUBLISHER = configure()


def source_blob(name):
    return BASELINE.parent / ('silver.dll' if name == 'silver.dll' else 'assets/' + name)


def load_package(package_path, expected_sha=None, baseline=BASELINE):
    package_path = Path(package_path)
    if not PUBLISHER.no_symlinks(package_path) or not package_path.resolve().is_relative_to(FOLDER/'client'):
        raise ValueError('Use only a regular scoped client package')
    if Path(baseline).resolve() != BASELINE.resolve():
        raise ValueError('Use the exact scoped hosted baseline')
    raw = package_path.read_bytes()
    package = PUBLISHER.package_identity(raw, expected_sha or sha(raw))
    if sha(BASELINE.read_bytes()) != MANIFEST_SHA:
        raise ValueError('Exact inspected hosted manifest required')
    payloads = {}
    for item in package['files']:
        candidate = package_path.parent / item['source']
        if not PUBLISHER.no_symlinks(candidate) or not candidate.resolve().is_relative_to(package_path.parent.resolve()):
            raise ValueError('Source exceeds its regular package directory')
        source = source_blob(item['path'])
        if not PUBLISHER.no_symlinks(source):
            raise ValueError('Prior source blob must be regular')
        data = candidate.read_bytes()
        PUBLISHER.blob_identity(item, data, source.read_bytes(), package['native_review'])
        payloads[item['path']] = data
    return package, payloads


PUBLISHER.load_package = load_package


def baseline_snapshot():
    report = PUBLISHER.baseline_snapshot()
    lookup = {row['path']: row for row in json.loads(BASELINE.read_bytes())['files']}
    for row in pinned_inventory():
        name = row['path']
        expected = (row['original_sha256'], row['original_size'])
        record = lookup[name]
        if (record['sha256'], record['size'], record.get('seed',False)) != (*expected,False):
            raise ValueError('Trusted HTTPS prior texture record changed')
        raw = PUBLISHER.fetch('blobs/' + expected[0], expected[1])
        if (sha(raw), len(raw)) != expected:
            raise ValueError('Trusted HTTPS prior texture blob changed')
        path = source_blob(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError('Existing prior texture source differs')
        else:
            with path.open('xb') as stream:
                stream.write(raw)
    if PUBLISHER.fetch('manifest.json',4*1024*1024) != BASELINE.read_bytes():
        raise ValueError('Public baseline changed while saving prior texture sources')
    return dict(report, source_textures=13, texture_inventory_sha256=INVENTORY_SHA,
                texture_contract_sha256=CONTRACT_SHA, local_player_files_read=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot','inspect','publish','verify'))
    parser.add_argument('--package', type=Path, default=FOLDER/'client/package.json')
    parser.add_argument('--package-sha256')
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--inspect-report', type=Path)
    args = parser.parse_args()
    report = args.report.resolve()
    if report.exists() or not report.is_relative_to(FOLDER/'client') or not PUBLISHER.no_symlinks(report.parent):
        raise ValueError('Use a new regular scoped client report path')
    if args.action == 'snapshot':
        result = baseline_snapshot()
    else:
        if not args.package_sha256:
            raise ValueError('Pin the exact reviewed package SHA256')
        payload = PUBLISHER.make_payload(args.package, args.package_sha256,
                    'apply' if args.action=='publish' else 'inspect', baseline=BASELINE,
                    before_inspect=args.inspect_report)
        result = PUBLISHER.verify_https(payload) if args.action=='verify' else PUBLISHER.invoke(payload)
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open('x', encoding='utf-8') as out:
        json.dump(result, out, indent=2)
        out.write('\n')
    if args.action == 'publish':
        https = PUBLISHER.verify_https(payload)
        with report.with_name(report.stem+'-https.json').open('x', encoding='utf-8') as out:
            json.dump(https, out, indent=2)
            out.write('\n')
    print(json.dumps({k:result.get(k) for k in ('passed','operation','version','backup','manifest_sha256','services_unchanged')}, indent=2))


if __name__ == '__main__':
    main()
