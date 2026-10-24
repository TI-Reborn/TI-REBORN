"""Own isolated hosted GUI fixtures and native client copies for all-window QA."""
from pathlib import Path
import argparse
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import personal_gui_qa_20261020 as qa
from tools import prepare_hosted_graphical_qa as prepare
from tools import area_fire_gui_20261018 as gui

WORK=ROOT/'work/personal-gui-all-20261020'
OUT=ROOT/'reports/personal-gui-all-20261020'
qa.WORK=WORK;qa.OUT=OUT;qa.PRIVATE=ROOT/'.secrets/personal-gui-all-20261020.json'


def guards(root):
    import hashlib, pefile
    root=Path(root).resolve()
    assert root in tuple((WORK/'gui'/('game-'+n)).resolve() for n in ('a','b'))
    assert (root/prepare.MARKER).is_file()
    pins={**qa.auth.HASHES,'silver.dll':'717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625',
          'tio_crest.dll':'d05b94f6707b7e139ceede957012a419b0a0cc46f16eb4be538514c04d6a3222'}
    for name,expected in pins.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected,name
    rows=[]
    with pefile.PE(str(root/'silver.dll')) as pe:
        for name,va,size,expected in qa.auth.SPANS:
            raw=pe.get_data(va-0x400000,size);assert hashlib.sha256(raw).hexdigest()==expected,name
            offsets=[entry.rva-(va-0x400000) for block in pe.DIRECTORY_ENTRY_BASERELOC for entry in block.entries
                     if entry.type==3 and 0<=entry.rva-(va-0x400000)<=8]
            rows.append(dict(name=name,va=va,entry12=raw[:12].hex(),entry_relocations=offsets))
    return rows


def prepare_copies():
    prepare.QA_BASE=WORK/'gui'
    prepare.INSTALLED=ROOT/'work/personal-gui-20261020/gui/game-a'
    prepare.BINARIES.add('tio_crest.dll')
    prepare.static_guards=guards
    gui.SILVER='717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'
    accepted=prepare.accepted_native_hashes
    prepare.accepted_native_hashes=lambda name: ({gui.SILVER} if name=='silver.dll' else accepted(name))
    raw=(WORK/'previous-manifest.json').read_bytes()
    manifest=json.loads(raw);records=prepare.validate_manifest(manifest)
    verified={}
    proofs=[prepare.prepare_copy(WORK/'gui'/('game-'+letter),manifest,records,
                                prepare.hashlib.sha256(raw).hexdigest(),verified) for letter in ('a','b')]
    (OUT/'prepared-copies.json').write_text(json.dumps([{
        k:p[k] for k in ('game_root','manifest_files','methods','personal_files_copied')
    } for p in proofs],indent=2)+'\n',encoding='utf-8')


def stage():
    import os
    overrides=json.loads((ROOT/'assets/personal-gui-all-v1/overrides.json').read_text())
    for letter in ('a','b'):
        root=WORK/'gui'/('game-'+letter); assert (root/'.tio-owned-qa').is_file()
        for name in overrides:
            target=root/name;temporary=target.with_name(target.name+'.gui-all-new')
            temporary.write_bytes((ROOT/'assets/personal-gui-all-v1/runtime'/name).read_bytes())
            os.replace(temporary,target)
        (root/'base/autoexec.cfg').write_text('orange_addr 185.184.42.88\norange_port 28512\ng_language russian\nr_fullscreen 0\nr_width 1600\nr_height 900\nsound_enable 0\n',encoding='ascii')
    print(json.dumps({'staged':len(overrides),'copies':2,'personal_files_modified':False}))


def launch():
    # Use the already published launcher; the main-frame hash activating its
    # guarded chat palette remains exact in this resource-only release.
    import hashlib,shutil
    launcher=WORK/'launcher/TIO Launcher.exe'
    if not launcher.exists():
        source=ROOT/'work/personal-gui-20261020/launcher/TIO Launcher.exe'
        assert hashlib.sha256(source.read_bytes()).hexdigest()=='496a083cb6624d906d91503d517d507f4c2246ca74b9341b12abe4768aa53f1c'
        launcher.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,launcher)
    gui.guards=guards
    qa.launch()


def cleanup():
    from tools.verify_game_operations_hosted import remote,CLEANUP
    from tools.verify_area_fire_hosted_20261018 import STATE
    data=json.loads(qa.PRIVATE.read_text())
    assert remote(STATE,dict(names=data['names'],plan=False)) is None,'Leave own battle normally first'
    frame=json.loads((OUT/'hosted-battle-state.json').read_text())
    assert frame['bots']==0 and {a['account'] for a in frame['actors']}==set(data['names'])
    old="condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)"
    new="\n  if 'match_id' in columns and request.get('matches'):\n   parts.append(quote('match_id')+' IN ('+','.join('?' for _ in request['matches'])+')');args+=request['matches']\n  "+old
    code=CLEANUP.replace(old,new);assert code!=CLEANUP
    result=remote(code,dict(names=data['names'],matches=[frame['match']],
        protected_before=data['provision']['protected_before'],require_unchanged_players=False))
    (OUT/'fixture-cleanup.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    qa.PRIVATE.unlink();print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('prepare','provision','stage','launch','cleanup'))
    mode=parser.parse_args().mode
    {'prepare':prepare_copies,'provision':qa.provision,'stage':stage,'launch':launch,'cleanup':cleanup}[mode]()
