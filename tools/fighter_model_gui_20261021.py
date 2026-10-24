"""Own hosted QA only: stage native meshes in a private copy, restore after QA."""
import argparse,hashlib,json,os,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import verify_launcher_required_hosted_20261020 as fixture
from tools import hosted_graphical_qa_bridge as auth
OUT=ROOT/'reports/fighter-model-20261020'
ASSET=ROOT/'assets/fighter-model-v1'
fixture.OUT=OUT;fixture.PRIVATE=ROOT/'.secrets/fighter-model-20261021.json'
GAME=ROOT/'work/launcher-required-20261020/native-client'
LAUNCHER=ROOT/'work/launcher-required-20261020/launcher/TIO Launcher.exe'
MAPPING={
 'base/models/chr_man_head.mdjx':'native/tio_vet_head.mdjx',
 'base/models/chr_man_body.mdjx':'native/tio_vet_torso.mdjx',
 'base/models/chr_man_hands.mdjx':'native/tio_vet_hands.mdjx',
 'base/models/chr_man_legs.mdjx':'native/tio_vet_legs.mdjx',
 'base/models/chr_man_head.jpg':'textures/tio_vet_head.jpg',
 'base/models/chr_man_body.jpg':'textures/tio_vet_body.jpg',
}
sha=lambda b:hashlib.sha256(b).hexdigest()


def atomic(target,raw):
    pending=target.with_name(target.name+'.fighter-stage')
    pending.write_bytes(raw);os.replace(pending,target)


def stage():
    assert (GAME/'.tio-owned-qa').is_file()
    manifest=json.loads(urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=20).read())
    rows={r['path']:r for r in manifest['files']};backup=OUT/'qa-original-files'
    assert not (OUT/'qa-stage.json').exists(),'Restore previous stage before staging again'
    records=[]
    for name,source in MAPPING.items():
        target=GAME/name;raw=target.read_bytes();assert sha(raw)==rows[name]['sha256'],name
        saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True)
        if saved.exists():assert saved.read_bytes()==raw
        else:saved.write_bytes(raw)
        candidate=(ASSET/source).read_bytes()
        records.append(dict(path=name,before=sha(raw),after=sha(candidate),source=source))
    (OUT/'qa-stage.json').write_text(json.dumps(dict(manifest_version=manifest['version'],files=records),indent=2))
    for r in records:atomic(GAME/r['path'],(ASSET/r['source']).read_bytes())
    print(json.dumps(dict(staged_private_client=True,files=len(records),published_client_changed=False)))


def restore():
    report=json.loads((OUT/'qa-stage.json').read_text())
    for r in report['files']:
        target=GAME/r['path'];assert sha(target.read_bytes())==r['after'],r['path']
        before=(OUT/'qa-original-files'/r['path']).read_bytes();assert sha(before)==r['before']
    for r in report['files']:atomic(GAME/r['path'],(OUT/'qa-original-files'/r['path']).read_bytes())
    (OUT/'qa-restored.json').write_text(json.dumps(dict(passed=True,files=len(report['files']),all_original_bytes_restored=True),indent=2))
    (OUT/'qa-stage.json').unlink()
    print(json.dumps(dict(restored=True,files=len(report['files']))))


def launch():
    rows={r['path']:r for r in json.loads(urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=20).read())['files']}
    for name in ('ti.exe','orange.dll','silver.dll'):assert sha((GAME/name).read_bytes())==rows[name]['sha256']
    staged=json.loads((OUT/'qa-stage.json').read_text())
    for r in staged['files']:assert sha((GAME/r['path']).read_bytes()) in (r['before'],r['after'])
    auth.HASHES={name:rows[name]['sha256'] for name in ('ti.exe','orange.dll','silver.dll')}
    data=json.loads(fixture.PRIVATE.read_text())
    bridge=auth.HostedGraphicalQaBridge(GAME,dict(login=data['names'][0],password=data['passwords'][0],fresh_qa=True),
        auto_select=True,launcher=LAUNCHER,launcher_sha256='52f29d6376dc6d5fc96ab13672bb05c4ca2802ff85236313ba06df7ca2533cc2')
    # Public launch validates/restores published art. Stage candidate resources
    # only in this exact-owned process's copy, before its first character load.
    for name,source in MAPPING.items():atomic(GAME/name,(ASSET/source).read_bytes())
    print(json.dumps(dict(started=True,pid=bridge.pid)),flush=True)
    (OUT/'gui-client.json').write_text(json.dumps(dict(pid=bridge.pid,root=str(GAME)),indent=2))
    try:
        print(json.dumps(bridge.start_connect()),flush=True)
        for line in sys.stdin:
            if line.strip()=='status':
                status=bridge.status();(OUT/'gui-status.json').write_text(json.dumps(status,indent=2));print(json.dumps(status),flush=True)
            elif line.strip()=='stop':break
    finally:
        bridge.release(cleanup=True);(OUT/'gui-events.json').write_text(json.dumps(bridge.events,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','stage','launch','restore','cleanup'));mode=p.parse_args().mode
    if mode=='provision':fixture.provision()
    elif mode=='cleanup':fixture.cleanup()
    else:globals()[mode]()
