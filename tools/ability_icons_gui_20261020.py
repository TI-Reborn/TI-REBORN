"""Real updated client on an exact-owned, ranking-excluded hosted fixture."""
import argparse,hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import verify_launcher_required_hosted_20261020 as fixture
from tools import hosted_graphical_qa_bridge as auth
OUT=ROOT/'reports/ability-icons-20261020'
fixture.OUT=OUT;fixture.PRIVATE=ROOT/'.secrets/ability-icons-20261020.json'
GAME=ROOT/'work/launcher-required-20261020/native-client'
LAUNCHER=ROOT/'work/launcher-required-20261020/launcher/TIO Launcher.exe'

def launch():
    manifest=json.loads(urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=20).read())
    assert manifest['version']=='2026.10.20.4'
    rows={r['path']:r for r in manifest['files']}
    for name in ('ti.exe','orange.dll','silver.dll','base/pda/skills.png'):
        assert hashlib.sha256((GAME/name).read_bytes()).hexdigest()==rows[name]['sha256'],name
    auth.HASHES={name:rows[name]['sha256'] for name in ('ti.exe','orange.dll','silver.dll')}
    data=json.loads(fixture.PRIVATE.read_text())
    assert hashlib.sha256(LAUNCHER.read_bytes()).hexdigest()=='52f29d6376dc6d5fc96ab13672bb05c4ca2802ff85236313ba06df7ca2533cc2'
    bridge=auth.HostedGraphicalQaBridge(GAME,dict(login=data['names'][0],password=data['passwords'][0],fresh_qa=True),
        auto_select=True,launcher=LAUNCHER,launcher_sha256='52f29d6376dc6d5fc96ab13672bb05c4ca2802ff85236313ba06df7ca2533cc2')
    (OUT/'gui-client.json').write_text(json.dumps(dict(pid=bridge.pid,root=str(GAME),version=manifest['version'],atlas_sha256=rows['base/pda/skills.png']['sha256']),indent=2))
    print(json.dumps(dict(started=True,pid=bridge.pid)),flush=True)
    try:
        print(json.dumps(bridge.start_connect()),flush=True)
        for line in sys.stdin:
            command=line.strip()
            if command=='status':
                status=bridge.status();(OUT/'gui-status.json').write_text(json.dumps(status,indent=2));print(json.dumps(status),flush=True)
            elif command=='stop':break
    finally:
        bridge.release(cleanup=True)
        (OUT/'gui-events.json').write_text(json.dumps(bridge.events,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','launch','cleanup'));a=p.parse_args()
    if a.mode=='launch':launch()
    elif a.mode=='provision':fixture.provision()
    else:fixture.cleanup()
