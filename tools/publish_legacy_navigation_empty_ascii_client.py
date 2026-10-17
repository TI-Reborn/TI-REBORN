"""Scoped .2 -> .3 legacy arena navigation, occupied-state colours, thirteen HUD textures and help.

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
CLIENT = FOLDER/'client-navigation-empty-ascii-release'
BASELINE = CLIENT/'source/manifest.json'
PREVIOUS_VERSION = '2026.10.11.2'
VERSION = '2026.10.11.3'
MANIFEST_SHA = 'f28a1f36ed14414df565f47826ed522ea3db60e81dedb239ed6983351d2aea99'
SILVER_SHA = '853feb6a3803078ffaf1570969c8432bce37f8c20593acbadcdb5a68f798f3a1'
SILVER_BYTES = 8126976
BASELINE_RECORDS = 6567
FIX = 'legacy-arena-navigation-empty-roster-main-hud-and-ascii-help'
INVENTORY = FOLDER/'textures-main-hud/changed-files.json'
INVENTORY_SHA = '254ae0ab0cb268940e787fcdc66dd5db3ad30010af90ddbdd4cec9bc0ff5b37f'
CONTRACT = ROOT/'tools/native_texture_contract_hud.py'
CONTRACT_SHA = 'b49b43820b22a87c3658f34441b048268d35d0ce8b5cc49dde90582db8b8d6a1'
NATIVE = FOLDER/'client-empty-roster-navigation/silver.dll'
NATIVE_SHA = '8735e66a1495b124f935432bebaa413f94dbcc9d4f4f00cb502911656e3bbb0b'
NATIVE_BYTES = 8131072
NATIVE_REVIEW = NATIVE.parent/'combined-review.json'
NATIVE_REVIEW_SHA = 'b0d48ee0a678c5bd77c3a1306ff5e7972efb8cecd51eba5e5c91a5a0071ff963'
NATIVE_ARTIFACTS = {
    'final-freeze.json': 'd6a54491fa22c30cd7c9c175de7d40cb0d3a4326ce2dc96e7779df64ea93e0c3',
    'native-composition.json': 'a83e5c0358e60924f0f33aab0dbec143a522828e31326d765b5822279eac2369',
    'native-navigation-proof.json': '8e23fe551f59e3c0c2c5e6810a5672e49266d3843fcfcae0ef04feb32bdf5822',
    'actual-arena-entry-proof.json': '9510a279a204a9d53a277d3f333a4e7cb289589d4efd7d2900e282fecc59429a',
    'owned-d-selector-state-before-fix.json': '3c4857ce212059b497670b518698152acbb25e9a5eafbc084cf766774e7ebf43',
}
NATIVE_SOURCE_PINS = {
    'deploy/client_arena_lobby_navigation.py': '7cffe229c7da457e8981eab3eca43d86b2d7ea24ae1c5e207302176352965f4e',
    'deploy/client_arena_lobby_search_status.py': '7a7550a9cb992a30ccc5d7bd1692a84d47ab506d5951505a4739d148e7dbb3b0',
    'deploy/client_arena_empty_roster_navigation.py': 'f53ad42acc2d05af6fbdf2adcd99c05616b3e7cd13fb1ede26461c961e58b35d',
    'tools/build_arena_empty_roster_navigation_native.py': 'ad438999c5d28a303432f4efef47a4f4ff9bb234d12e5ea8361b7bebabd165c4',
    'tools/verify_arena_empty_roster_navigation_native.py': '4b646704cc89df02108df2442a1afb0fe7e36c5ebef672b6e72164c9687f7b61',
    'tools/verify_actual_arena_entry_native.py': 'c84bfbc7fbe72da469dc3b8083619978665f4550c8d5df5245a240e0d6d269ff',
    'tools/hosted_graphical_qa_bridge.py': '5b7c4e0f4e3e64fb921499782e2265cf199eb1cbb16f26774f88828d5704a618',
}
HELP_PATH = 'base/russian.lng'
HELP_IDENTITY = ('cd711d83be980858c8b205a3114e61c38a349f0a899c80a26ce5f0c8547e1403', 119420,
                 '7e2f5cb9712254935dcfad9f13c2e3b8b14d2437ca01827e8e9e527ad766afe2', 119405)
HELP_RANGE = (14404, 270)
HELP_TEXT = 'Зелёное лобби: свободно и у вас есть бойцы нужного уровня, включая резерв. Красное: подходящих бойцов нет. Серое: лобби занято. В графе "Игроки" показан состав группы: 2 человека для командного боя, 4 для стенки на стенку. Диапазон этой арены: 1-3.'
HELP_LINE = b'h2_3=' + HELP_TEXT.encode('cp1251') + b'\r\n'
HELP_VALIDATION = '''def validate_help(before,after):
 if (sha(before),len(before))!=HELP_IDENTITY[:2]:raise ValueError('Exact published Russian help source required')
 offset,size=HELP_RANGE
 prior=before[offset:offset+size]
 if not prior.startswith(b'h2_3=') or not prior.endswith(b'\\r\\n') or b'\\n' in prior[:-2]:raise ValueError('Pinned original native help line differs')
 if after!=before[:offset]+HELP_LINE+before[offset+size:]:raise ValueError('Only the exact h2_3 CP1251 line may change')
 if (sha(after),len(after))!=HELP_IDENTITY[2:]:raise ValueError('Exact reviewed Russian help replacement required')
 return dict(key='h2_3',encoding='cp1251',line_offset=offset,old_line_size=size,new_line_size=len(HELP_LINE),other_bytes_preserved=True,crlf_preserved=True,old_size=len(before),new_size=len(after))

'''


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
    spec=importlib.util.spec_from_file_location('_legacy_navigation_empty_ascii_transaction',ROOT/'tools/publish_mine_drill_ui_remote.py')
    base=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    remote=base.REMOTE
    for key,value in dict(MANIFEST_SHA=MANIFEST_SHA,PREVIOUS_VERSION=PREVIOUS_VERSION,
                          VERSION=VERSION,SILVER_SHA=SILVER_SHA,SILVER_BYTES=SILVER_BYTES,
                          BASELINE_RECORDS=BASELINE_RECORDS).items():
        remote=replace_once(remote,f'{key}={getattr(base,key)!r}\n',f'{key}={value!r}\n')
        setattr(base,key,value)
    base.REMOTE=replace_once(remote,"prefix='tio-before-mine-drill-ui-fix-'","prefix='tio-before-legacy-navigation-empty-ascii-client-'")
    base.REPORT_ROOT=FOLDER
    base.BASELINE=BASELINE
    base.REPORT_CLIENT=CLIENT
    payload_code=replace_once(inspect.getsource(base.make_payload),
        "package_path.resolve().is_relative_to(REPORT_ROOT/'client')",
        "package_path.resolve().is_relative_to(REPORT_CLIENT)")
    payload_code=replace_once(payload_code,
        'Use only a reviewed reports/mine-drill-ui-20261010/client package',
        'Use only the reviewed client-navigation-empty-ascii-release package')
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


def native_inputs():
    if not NATIVE_ARTIFACTS or not NATIVE_SOURCE_PINS:
        raise ValueError('Empty-selector native composition is not frozen yet')
    for name, expected in NATIVE_ARTIFACTS.items():
        path = NATIVE.parent/name
        if not regular(path) or sha(path.read_bytes()) != expected:
            raise ValueError('Immutable native proof changed: '+name)
    for name, expected in NATIVE_SOURCE_PINS.items():
        path = ROOT/name
        if not regular(path) or sha(path.read_bytes()) != expected:
            raise ValueError('Immutable native source/dependency changed: '+name)
    composition = json.loads((NATIVE.parent/'native-composition.json').read_bytes())
    if (composition['passed'], composition['source_sha256'], composition['source_bytes'],
            composition['candidate_sha256'], composition['candidate_bytes']) != (
            True, SILVER_SHA, SILVER_BYTES, NATIVE_SHA, NATIVE_BYTES):
        raise ValueError('Native composition is not the reviewed public2 transition')
    if composition['native_review'] != json.loads(NATIVE_REVIEW.read_bytes()):
        raise ValueError('Native composition and exact review differ')
    if not composition['preservation']['all_undeclared_native_bytes_preserved'] or composition['preservation']['auth_functions_preserved'] != 16:
        raise ValueError('Native preservation evidence is incomplete')
    return dict(artifact_sha256=NATIVE_ARTIFACTS, source_code_sha256=NATIVE_SOURCE_PINS,
                composition_passed=True, protected_auth_spans=16)


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
    native_inputs()
    contract=contract_raw.decode('utf-8').replace('from __future__ import annotations\n','')
    prefix=('TEXTURES='+repr(allowed)+'\nNATIVE_IDENTITY='+repr((NATIVE_SHA,NATIVE_BYTES))
            +'\nNATIVE_REVIEW=json.loads('+repr(review_raw.decode('utf-8'))+')\n'+contract+'\n'
            +'HELP_PATH='+repr(HELP_PATH)+'\nHELP_IDENTITY='+repr(HELP_IDENTITY)
            +'\nHELP_RANGE='+repr(HELP_RANGE)+'\nHELP_LINE='+repr(HELP_LINE)+'\n'+HELP_VALIDATION)
    validation=base.VALIDATION
    validation=replace_once(validation,"if p['selection']!={'fix':'battle-ui-quality-and-mine-hover'}:","if p['selection']!={'fix':"+repr(FIX)+"}:")
    validation=replace_once(validation,"native_review_identity(p['native_review'])","native_review_identity(p['native_review'])\n if not same_json(p['native_review'],NATIVE_REVIEW):raise ValueError('Native review differs from exact navigation freeze')")
    validation=replace_once(validation,"if not isinstance(p['files'],list) or not 1<=len(p['files'])<=256:","if not isinstance(p['files'],list) or len(p['files'])!=15 or {x.get('path') for x in p['files']}!=set(TEXTURES)|{'silver.dll',HELP_PATH}:")
    validation=replace_once(validation,"if name!='silver.dll':raise ValueError('Only Silver native client patch accepted')","if name!='silver.dll' or (item['sha256'],item['size'])!=NATIVE_IDENTITY:raise ValueError('Only the exact frozen navigation Silver accepted')")
    validation=replace_once(validation,
        "elif kind=='icon_image':\n   if not name.startswith('base/ui-hd/') or name.startswith('base/ui-hd/fonts/') or not name.endswith('.png'):raise ValueError('PNG path exceeds requested icon/button scope')",
        "elif kind=='native_texture':\n   if name not in TEXTURES or (item['sha256'],item['size'])!=TEXTURES[name][2:]:raise ValueError('Texture differs from exact main-HUD scope')\n  elif kind=='arena_help':\n   if name!=HELP_PATH or (item['sha256'],item['size'])!=HELP_IDENTITY[2:]:raise ValueError('Only the exact h2_3 help resource accepted')")
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
 if item['kind']=='arena_help':
  if item['path']!=HELP_PATH or (item['sha256'],item['size'])!=HELP_IDENTITY[2:] or source is None:raise ValueError('Unreviewed native arena help resource')
  return validate_help(source,raw)
 raise ValueError('Unreviewed resource kind')

'''+validation[end:]
    validation=replace_once(validation,
        "if len(prior)!=BASELINE_RECORDS or len({x['path'] for x in prior})!=BASELINE_RECORDS:",
        "if set(updates)!=set(TEXTURES)|{'silver.dll',HELP_PATH} or len(current)!=BASELINE_RECORDS or any(name not in {x['path'] for x in prior} for name in updates):raise ValueError('Only fifteen existing records may change; additions refused')\n if len(prior)!=BASELINE_RECORDS or len({x['path'] for x in prior})!=BASELINE_RECORDS:")
    validation=replace_once(validation,
        "lookup={x['path']:x for x in prior};folded={x['path'].casefold() for x in prior}",
        "lookup={x['path']:x for x in prior};folded={x['path'].casefold() for x in prior}\n for name,expected in dict(TEXTURES,**{HELP_PATH:HELP_IDENTITY}).items():\n  if (lookup[name]['sha256'],lookup[name]['size'],lookup[name].get('seed',False))!=(*expected[:2],False):raise ValueError('Pinned published2 source record changed')")
    remote=replace_once(base.REMOTE,base.VALIDATION,prefix+validation)
    remote=replace_once(remote,
        "details[name]=blob_identity(item,raw,sources.get(name) if item['kind']=='native' else None,package['native_review']);raws[name]=raw",
        "details[name]=blob_identity(item,raw,sources.get(name),package['native_review']);raws[name]=raw")
    remote=replace_once(remote,
        "if len(rows)<202 or regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:",
        "for name,expected in dict(TEXTURES,**{HELP_PATH:HELP_IDENTITY}).items():\n  row=next(x for x in manifest['files'] if x['path']==name)\n  if (row['sha256'],row['size'],row.get('seed',False))!=(*expected[:2],False):raise RuntimeError('Hosted pinned source record changed')\n  value=state(LIVE/'blobs'/expected[0])\n  if value!=dict(sha256=expected[0],size=expected[1],uid=0,gid=0,mode=0o644):raise RuntimeError('Actual pinned source blob changed')\n  native[name]=value\n if len(rows)<202 or regular(LIVE/'manifest.json').read_bytes()!=old or guards()!=before:")
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
    lookup={x['path']:x for x in json.loads(BASELINE.read_bytes())['files']}
    row=lookup[HELP_PATH]
    if (row['sha256'],row['size'],row.get('seed',False))!=(*HELP_IDENTITY[:2],False):
        raise ValueError('Actual published2 native help record differs')
    raw=base.fetch('blobs/'+HELP_IDENTITY[0],HELP_IDENTITY[1]);path=source_blob(HELP_PATH)
    if (sha(raw),len(raw))!=HELP_IDENTITY[:2] or not regular(path):
        raise ValueError('Actual published2 native help source differs')
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError('Existing native help source differs')
    else:
        with path.open('xb') as out:out.write(raw)
    report.update(native_help_source_sha256=HELP_IDENTITY[0],native_help_source_size=HELP_IDENTITY[1])
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
