"""Publish exactly one RPG HUD atlas using the existing guarded resource publisher."""
import argparse,hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import publish_battle_icon_centering_remote as pub
OUT=ROOT/'reports/rpg-action-icon-20261019';WORK=ROOT/'work/rpg-action-icon-20261019'
sha=lambda raw:hashlib.sha256(raw).hexdigest()

def configure():
    old=(WORK/'manifest-before.json').read_bytes();manifest=json.loads(old);by={r['path']:r for r in manifest['files']}
    values=dict(MANIFEST_SHA=sha(old),PREVIOUS_VERSION=manifest['version'],VERSION='2026.10.19.6',
                BASELINE_RECORDS=len(manifest['files']),SILVER_SHA=by['silver.dll']['sha256'],SILVER_BYTES=by['silver.dll']['size'])
    for key,value in values.items():
        anchor=f'{key}={getattr(pub,key)!r}\n';assert anchor in pub.REMOTE,key
        pub.REMOTE=pub.REMOTE.replace(anchor,f'{key}={value!r}\n');setattr(pub,key,value)
    pub.REMOTE=pub.REMOTE.replace('battle-icon-centering','rpg-action-icon').replace('len(ids)<202','len(ids)<22').replace('len(rows)<202','len(rows)<22')
    pub.VALIDATION=pub.VALIDATION.replace('battle-icon-centering','rpg-action-icon')
    exec(pub.VALIDATION,pub.__dict__)
    pub.REPORT_ROOT=OUT;pub.DEPLOYMENT=OUT/'deployment';pub.BASELINE=OUT/'baseline/manifest.json'
    pub.BASELINE.parent.mkdir(exist_ok=True)
    for name in ('silver.dll','hd4-bui-glyphs.png','manifest-before.json'):
        target=pub.BASELINE if name=='manifest-before.json' else pub.BASELINE.parent/name
        raw=(WORK/name).read_bytes()
        if target.exists():assert target.read_bytes()==raw
        else:target.write_bytes(raw)
    return old

def package():
    proof=json.loads((OUT/'asset-proof.json').read_text());native=json.loads((OUT/'native-icon-routing.json').read_text())
    path=OUT/'client'/pub.ATLAS_PATH;raw=path.read_bytes()
    assert proof['passed'] and proof['other_35_cells_pixel_identical'] and proof['candidate_sha256']==sha(raw)
    assert native['passed'] and native['silver_sha256']==pub.SILVER_SHA
    p=dict(schema=1,previous_version=pub.PREVIOUS_VERSION,version=pub.VERSION,
           baseline_manifest_sha256=pub.MANIFEST_SHA,selection={'fix':'rpg-action-icon'},native_review=None,
           files=[dict(path=pub.ATLAS_PATH,source=pub.ATLAS_PATH,sha256=sha(raw),size=len(raw),kind='icon_image')])
    target=OUT/'client/package.json';data=(json.dumps(p,indent=2)+'\n').encode()
    if target.exists():assert target.read_bytes()==data
    else:target.write_bytes(data)
    return target,sha(data)

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('inspect','apply','verify'));args=p.parse_args()
    configure();path,digest=package();pub.DEPLOYMENT.mkdir(exist_ok=True)
    target=pub.DEPLOYMENT/(args.mode+'.json');assert not target.exists()
    # Pass the current baseline explicitly: the reused function has a historical default.
    inspected=pub.DEPLOYMENT/'inspect.json'
    original=pub.load_package
    pub.load_package=lambda package_path,expected_sha=None,baseline=None:original(package_path,expected_sha,pub.BASELINE)
    payload=pub.make_payload(path,digest,'apply' if args.mode=='apply' else 'inspect',baseline=pub.BASELINE,
                             before_inspect=inspected if args.mode=='apply' else None)
    result=pub.verify_https(payload) if args.mode=='verify' else pub.invoke(payload)
    target.write_text(json.dumps(result,indent=2))
    if args.mode=='apply':
        proof=pub.verify_https(payload);(pub.DEPLOYMENT/'https-verification.json').write_text(json.dumps(proof,indent=2))
    print(json.dumps(dict(passed=True,mode=args.mode,version=result.get('version'),backup=result.get('backup'),
                         report=str(target),health=result.get('health'),patch_scope=result.get('patch_scope'))))
if __name__=='__main__':main()
