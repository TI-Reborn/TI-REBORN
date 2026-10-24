"""Own excluded hosted fixtures and one real native GUI acceptance client."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import secrets
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import area_fire_gui_20261018 as gui
from tools import hosted_graphical_qa_bridge as auth
from tools.verify_game_operations_hosted import remote,CREATE,CLEANUP
from tools.verify_area_fire_hosted_20261018 import PREPARE

WORK=ROOT/'work/personal-gui-20261020'
OUT=ROOT/'reports/personal-gui-20261020'
PRIVATE=ROOT/'.secrets/personal-gui-20261020.json'


def provision():
    if PRIVATE.exists():raise FileExistsError(PRIVATE)
    prefix='qg'+secrets.token_hex(4)
    data={'names':[prefix+'a',prefix+'b'],'passwords':[secrets.token_urlsafe(24) for _ in range(2)]}
    data['provision']=remote(CREATE,list(zip(data['names'],data['passwords'])))
    PRIVATE.write_text(json.dumps(data),encoding='utf-8')
    prepare=PREPARE.replace("'0x8c4aef':10", "'0x8c4aef':1").replace("'0x8c4b05':FLOORS[9]", "'0x8c4b05':0")
    prepare=prepare.replace('314+index','301').replace('locations,name,2','locations,name,3')
    prepare=prepare.replace('_save(db,name,2,*center(2))','_save(db,name,3,*center(3))')
    result=remote(prepare,data['names'])
    (OUT/'fixture-provisioning.json').write_text(json.dumps({'created':2,'rating_excluded':True,'town':3,'only_owned_fixtures':True}),encoding='utf-8')
    print(json.dumps({'created':2,'rating_excluded':True}))


def stage():
    root=WORK/'gui/game-a'
    assert (root/'.tio-owned-qa').is_file()
    overrides=json.loads((ROOT/'assets/personal-gui-v1/overrides.json').read_text())
    for name in overrides:
        target=root/name;temporary=target.with_name(target.name+'.personal-gui-new')
        temporary.write_bytes((ROOT/'assets/personal-gui-v1/runtime'/name).read_bytes())
        os.replace(temporary,target) # Break any immutable-resource hardlink.
    config=root/'base/autoexec.cfg'
    config.write_text('orange_addr 185.184.42.88\norange_port 28512\ng_language russian\nr_fullscreen 0\nr_width 1600\nr_height 900\nsound_enable 0\n',encoding='ascii')
    print(json.dumps({'staged':len(overrides),'own_qa_only':True}))


def launch():
    data=json.loads(PRIVATE.read_text(encoding='utf-8'))
    gui.WORK=WORK/'gui';gui.SILVER='717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'
    auth.static_guards=gui.guards
    launcher=WORK/'launcher/TIO Launcher.exe'
    bridge=auth.HostedGraphicalQaBridge(WORK/'gui/game-a',
        dict(login=data['names'][0],password=data['passwords'][0],fresh_qa=True),auto_select=True,
        launcher=launcher,launcher_sha256=hashlib.sha256(launcher.read_bytes()).hexdigest())
    (OUT/'gui-client.json').write_text(json.dumps({'pid':bridge.pid,'root':str(bridge.root),'launcher':str(launcher)},indent=2),encoding='utf-8')
    print(json.dumps({'started':True,'pid':bridge.pid}),flush=True)
    try:
        print(json.dumps(bridge.start_connect()),flush=True)
        for line in sys.stdin:
            command=line.strip()
            if command=='status':
                status=bridge.status();(OUT/'gui-status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
                print(json.dumps(status),flush=True)
            elif command=='stop':break
    finally:
        bridge.release(cleanup=True)
        (OUT/'gui-events.json').write_text(json.dumps(bridge.events,indent=2),encoding='utf-8')


def cleanup():
    data=json.loads(PRIVATE.read_text(encoding='utf-8'))
    result=remote(CLEANUP,dict(names=data['names'],protected_before=data['provision']['protected_before'],require_unchanged_players=False))
    (OUT/'fixture-cleanup.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    PRIVATE.unlink();print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('provision','stage','launch','cleanup'))
    globals()[parser.parse_args().mode]()
