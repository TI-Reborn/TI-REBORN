"""Scoped .2 -> .3 legacy arena navigation and thirteen main-HUD textures.

Snapshot/inspect are read-only. Publish preserves accounts and reuses the
established full online SQLite/code/config/prior-blob backup and atomic commit.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
FOLDER = ROOT/'reports/gameplay-completion/legacy-status-20261011'
CLIENT = FOLDER/'client-navigation-release'
BASELINE = CLIENT/'source/manifest.json'
PREVIOUS_VERSION = '2026.10.11.2'
VERSION = '2026.10.11.3'
MANIFEST_SHA = 'f28a1f36ed14414df565f47826ed522ea3db60e81dedb239ed6983351d2aea99'
SILVER_SHA = '853feb6a3803078ffaf1570969c8432bce37f8c20593acbadcdb5a68f798f3a1'
SILVER_BYTES = 8126976
BASELINE_RECORDS = 6567
FIX = 'legacy-arena-navigation-and-main-hud-textures'
INVENTORY = FOLDER/'textures-main-hud/changed-files.json'
INVENTORY_SHA = '254ae0ab0cb268940e787fcdc66dd5db3ad30010af90ddbdd4cec9bc0ff5b37f'
CONTRACT = ROOT/'tools/native_texture_contract_hud.py'
CONTRACT_SHA = 'b49b43820b22a87c3658f34441b048268d35d0ce8b5cc49dde90582db8b8d6a1'
NATIVE = FOLDER/'client-availability-navigation/silver.dll'
NATIVE_SHA = 'afaa457c06ba6223476bc6e53eeff9947e9291acbce19700bb10ed5c3b29bdad'
NATIVE_BYTES = 8131072
NATIVE_REVIEW = FOLDER/'client-availability-navigation/combined-review.json'
NATIVE_REVIEW_SHA = '8a21ac17cc576514af7dfacb4d2970737567f1080d185e54df89a435a194d165'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def replace_once(raw,before,after):
    if raw.count(before)!=1:
        raise ValueError('Established publisher guard changed: '+before[:80])
    return raw.replace(before,after)


def regular(path):
    return not any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in [path,*path.parents])


def foundation():
    # A private module instance leaves every earlier release adapter unchanged.
    spec=importlib.util.spec_from_file_location('_legacy_navigation_transaction',ROOT/'tools/publish_mine_drill_ui_remote.py')
    base=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    remote=base.REMOTE
    for key,value in dict(MANIFEST_SHA=MANIFEST_SHA,PREVIOUS_VERSION=PREVIOUS_VERSION,
                          VERSION=VERSION,SILVER_SHA=SILVER_SHA,SILVER_BYTES=SILVER_BYTES,
                          BASELINE_RECORDS=BASELINE_RECORDS).items():
        remote=replace_once(remote,f'{key}={getattr(base,key)!r}\n',f'{key}={value!r}\n')
        setattr(base,key,value)
    base.REMOTE=replace_once(remote,"prefix='tio-before-mine-drill-ui-fix-'","prefix='tio-before-legacy-navigation-client-'")
    base.REPORT_ROOT=FOLDER
    base.BASELINE=BASELINE
    base.REPORT_CLIENT=CLIENT
    payload_code=replace_once(inspect.getsource(base.make_payload),
        "package_path.resolve().is_relative_to(REPORT_ROOT/'client')",
        "package_path.resolve().is_relative_to(REPORT_CLIENT)")
    payload_code=replace_once(payload_code,
        'Use only a reviewed reports/mine-drill-ui-20261010/client package',
        'Use only the reviewed client-navigation-release package')
    exec(compile(payload_code,'legacy-navigation-scoped-payload','exec'),base.__dict__)
    return base


def pinned_inventory():
    if not INVENTORY_SHA:
        raise ValueError('Main-HUD texture inventory is not frozen yet')
    raw=INVENTORY.read_bytes()
    if not regular(INVENTORY) or sha(raw)!=INVENTORY_SHA:
        raise ValueError('Immutable main-HUD inventory changed')
    document=json.loads(raw)
    if (document['baseline_version'],document['baseline_manifest_sha256'])!=(PREVIOUS_VERSION,MANIFEST_SHA):
        raise ValueError('Main-HUD inventory baseline changed')
    rows=document['files']
    if len(rows)!=13 or len({x['path'] for x in rows})!=13:
        raise ValueError('Exactly thirteen frozen existing textures required')
    return rows


def configure():
    base=foundation()
    rows=pinned_inventory()
    allowed={x['path']:(x['original_sha256'],x['original_size'],x['sha256'],x['size']) for x in rows}
    if not all((CONTRACT_SHA,NATIVE_SHA,NATIVE_REVIEW_SHA)):
        raise ValueError('Independent native/texture composition must freeze first')
    contract_raw=CONTRACT.read_bytes()
    review_raw=NATIVE_REVIEW.read_bytes()
    if not regular(CONTRACT) or not regular(NATIVE_REVIEW) or sha(contract_raw)!=CONTRACT_SHA or sha(review_raw)!=NATIVE_REVIEW_SHA:
        raise ValueError('Frozen native contract/review changed')
    contract=contract_raw.decode('utf-8').replace('from __future__ import annotations\n','')
    prefix=('TEXTURES='+repr(allowed)+'\nNATIVE_IDENTITY='+repr((NATIVE_SHA,NATIVE_BYTES))
            +'\nNATIVE_REVIEW=json.loads('+repr(review_raw.decode('utf-8'))+')\n'+contract+'\n')
    validation=base.VALIDATION
    validation=replace_once(validation,"if p['selection']!={'fix':'battle-ui-quality-and-mine-hover'}:","if p['selection']!={'fix':"+repr(FIX)+"}:")
    validation=replace_once(validation,"native_review_identity(p['native_review'])","native_review_identity(p['native_review'])\n if not same_json(p['native_review'],NATIVE_REVIEW):raise ValueError('Native review differs from exact navigation freeze')")
    validation=replace_once(validation,"if not isinstance(p['files'],list) or not 1<=len(p['files'])<=256:","if not isinstance(p['files'],list) or len(p['files'])!=14 or {x.get('path') for x in p['files']}!=set(TEXTURES)|{'silver.dll'}:")
    validation=replace_once(validation,"if name!='silver.dll':raise ValueError('Only Silver native client patch accepted')","if name!='silver.dll' or (item['sha256'],item['size'])!=NATIVE_IDENTITY:raise ValueError('Only the exact frozen navigation Silver accepted')")
    validation=replace_once(validation,
        "elif kind=='icon_image':\n   if not name.startswith('base/ui-hd/') or name.startswith('base/ui-hd/fonts/') or not name.endswith('.png'):raise ValueError('PNG path exceeds requested icon/button scope')",
        "elif kind=='native_texture':\n   if name not in TEXTURES or (item['sha256'],item['size'])!=TEXTURES[name][2:]:raise ValueError('Texture differs from exact main-HUD scope')")
    start=validation.index('def blob_identity(');end=validation.index('def manifest_transition(',start)
    validation=validation[:start]+'''def blob_identity(item,raw,source=None,native_review=None):
 if hashlib.sha256(raw).hexdigest()!=item['sha256'] or len(raw)!=item['size']:raise ValueError('Blob differs from exact identity')
 if item['kind']=='native':
  if source is None or (sha(source),len(source))!=(SILVER_SHA,SILVER_BYTES):raise ValueError('Actual published2 Silver source required')
  if item['sha256']==SILVER_SHA:raise ValueError('Native candidate unchanged')
  return native_preserved(source,raw,native_review)
 if item['kind']=='native_texture':
  expected=TEXTURES.get(item['path'])
  if expected is None or (item['sha256'],item['size'])!=expected[2:]:raise ValueError('Unreviewed texture identity')
  if source is None or (sha(source),len(source))!=expected[:2]:raise ValueError('Actual published2 prior texture source required')
  return validate_replacement(source,raw)
 raise ValueError('Unreviewed resource kind')

'''+validation[end:]
    validation=replace_once(validation,
        "if len(prior)!=BASELINE_RECORDS or len({x['path'] for x in prior})!=BASELINE_RECORDS:",
        "if set(updates)!=set(TEXTURES)|{'silver.dll'} or len(current)!=BASELINE_RECORDS or any(name not in {x['path'] for x in prior} for name in updates):raise ValueError('Only fourteen existing records may change; additions refused')\n if len(prior)!=BASELINE_RECORDS or len({x['path'] for x in prior})!=BASELINE_RECORDS:")
    validation=replace_once(validation,
        "lookup={x['path']:x for x in prior};folded={x['path'].casefold() for x in prior}",
        "lookup={x['path']:x for x in prior};folded={x['path'].casefold() for x in prior}\n for name,expected in TEXTURES.items():\n  if (lookup[name]['sha256'],lookup[name]['size'],lookup[name].get('seed',False))!=(*expected[:2],False):raise ValueError('Pinned published2 texture manifest record changed')")
    remote=replace_once(base.REMOTE,base.VALIDATION,prefix+validation)
    remote=replace_once(remote,
        "details[name]=blob_identity(item,raw,sources.get(name) if item['kind']=='native' else None,package['native_review']);raws[name]=raw",
        "details[name]=blob_identity(item,raw,sources.get(name),package['native_review']);raws[name]=raw")
    remote=replace_once(remote,
        "if len(rows)<202 or regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:",
        "for name,expected in TEXTURES.items():\n  row=next(x for x in manifest['files'] if x['path']==name)\n  if (row['sha256'],row['size'],row.get('seed',False))!=(*expected[:2],False):raise RuntimeError('Hosted pinned source texture record changed')\n  value=state(LIVE/'blobs'/expected[0])\n  if value!=dict(sha256=expected[0],size=expected[1],uid=0,gid=0,mode=0o644):raise RuntimeError('Actual pinned source texture blob changed')\n  native[name]=value\n if len(rows)<202 or regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:")
    compile(remote,'legacy-navigation-client-publication','exec')
    base.REMOTE=remote
    base.VALIDATION=prefix+validation
    exec(base.VALIDATION,base.__dict__)
    base.load_package=load_package
    return base


PUBLISHER=None


def publisher():
    global PUBLISHER
    if PUBLISHER is None:
        PUBLISHER=configure()
    return PUBLISHER


def source_blob(name):
    return BASELINE.parent/('silver.dll' if name=='silver.dll' else 'assets/'+name)


def load_package(package_path,expected_sha=None,baseline=BASELINE):
    base=publisher();package_path=Path(package_path)
    if not regular(package_path) or not package_path.resolve().is_relative_to(CLIENT) or Path(baseline).resolve()!=BASELINE.resolve():
        raise ValueError('Use a regular immutable navigation release package/baseline')
    raw=package_path.read_bytes();package=base.package_identity(raw,expected_sha or sha(raw))
    if not regular(BASELINE) or sha(BASELINE.read_bytes())!=MANIFEST_SHA:
        raise ValueError('Exact actual published2 manifest required')
    payloads={}
    for item in package['files']:
        path=package_path.parent/item['source'];source=source_blob(item['path'])
        if not regular(path) or not path.resolve().is_relative_to(package_path.parent.resolve()) or not regular(source):
            raise ValueError('Candidate/prior blob exceeds its regular scoped directory')
        data=path.read_bytes()
        base.blob_identity(item,data,source.read_bytes(),package['native_review'])
        payloads[item['path']]=data
    return package,payloads


def baseline_snapshot():
    base=publisher() if INVENTORY_SHA and CONTRACT_SHA and NATIVE_REVIEW_SHA else foundation()
    report=base.baseline_snapshot()
    if INVENTORY_SHA:
        lookup={x['path']:x for x in json.loads(BASELINE.read_bytes())['files']}
        for row in pinned_inventory():
            expected=(row['original_sha256'],row['original_size']);record=lookup[row['path']]
            if (record['sha256'],record['size'],record.get('seed',False))!=(*expected,False):
                raise ValueError('Actual published2 prior texture record differs')
            raw=base.fetch('blobs/'+expected[0],expected[1]);path=source_blob(row['path'])
            if (sha(raw),len(raw))!=expected or not regular(path):
                raise ValueError('Actual published2 prior texture blob differs')
            path.parent.mkdir(parents=True,exist_ok=True)
            if path.exists():
                if path.read_bytes()!=raw:raise ValueError('Existing prior texture source differs')
            else:
                with path.open('xb') as out:out.write(raw)
        report.update(source_textures=13,texture_inventory_sha256=INVENTORY_SHA,texture_contract_sha256=CONTRACT_SHA)
    if base.fetch('manifest.json',4*1024*1024)!=BASELINE.read_bytes():
        raise ValueError('Actual baseline changed while saving sources')
    return dict(report,local_player_files_read=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('snapshot','inspect','publish','verify'))
    parser.add_argument('--package',type=Path,default=CLIENT/'package.json')
    parser.add_argument('--package-sha256')
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--inspect-report',type=Path)
    args=parser.parse_args();path=args.report.resolve()
    if path.exists() or not path.is_relative_to(CLIENT) or not regular(path):
        raise ValueError('Use a new regular scoped navigation release report')
    if args.action=='snapshot':
        result=baseline_snapshot()
    else:
        if not args.package_sha256:raise ValueError('Exact reviewed package SHA256 required')
        base=publisher()
        payload=base.make_payload(args.package,args.package_sha256,'apply' if args.action=='publish' else 'inspect',baseline=BASELINE,before_inspect=args.inspect_report)
        result=base.verify_https(payload) if args.action=='verify' else base.invoke(payload)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as out:json.dump(result,out,indent=2);out.write('\n')
    if args.action=='publish':
        https=base.verify_https(payload)
        with path.with_name(path.stem+'-https.json').open('x',encoding='utf-8') as out:json.dump(https,out,indent=2);out.write('\n')
    print(json.dumps({k:result.get(k) for k in ('passed','operation','version','backup','manifest_sha256')},indent=2))


if __name__=='__main__':
    main()
