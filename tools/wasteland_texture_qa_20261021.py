"""Private current-release native client; excluded disposable hosted accounts."""
import argparse,hashlib,json,shutil,sys,urllib.request,concurrent.futures
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import verify_launcher_required_hosted_20261020 as fixture
from tools import hosted_graphical_qa_bridge as auth
OUT=ROOT/'reports/remaining-textures-20261021';ASSET=ROOT/'assets/wasteland-materials-v1'
GAME=ROOT/'work/remaining-textures-20261021/native-client';LAUNCHER=GAME.parent/'TIO Launcher.exe'
fixture.OUT=OUT;fixture.PRIVATE=ROOT/'.secrets/remaining-textures-20261021.json'
fixture.v.PREPARE+=r'''
for name in request:
 with sqlite3.connect(path) as db:
  assert excluded(db,name)
  packet,inventory=db.execute('SELECT pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=1',(name,)).fetchone()
  from tio.protocol.item_list import decode_item_list
  entries=list(decode_item_list(inventory)[1])+[item(42000+i,t,current=600) for i,t in enumerate((5003,5004,5005,5006,5007,5008,5002,35))]
  db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',(encode_item_list(1,tuple(entries)),name))
'''
sha=lambda b:hashlib.sha256(b).hexdigest()

def setup():
    if not GAME.exists():
        old=ROOT/'work/launcher-required-20261020/native-client';assert (old/'.tio-owned-qa').exists()
        shutil.copytree(old,GAME);(GAME/'.tio-owned-qa').write_text('Private texture QA 2026-10-21\n')
    assert (GAME/'.tio-owned-qa').exists()
    raw=urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=30).read();assert raw==(OUT/'manifest-before.json').read_bytes()
    m=json.loads(raw)
    def one(r):
        p=GAME/r['path']
        if p.exists() and (r.get('seed') or sha(p.read_bytes())==r['sha256']):return 0
        b=urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+r['sha256'],timeout=40).read();assert sha(b)==r['sha256'] and len(b)==r['size'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b);return 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:changed=sum(pool.map(one,m['files']))
    lm=json.loads(urllib.request.urlopen('https://185.184.42.88/downloads/launcher-manifest.json',timeout=30).read())
    if not LAUNCHER.exists() or sha(LAUNCHER.read_bytes())!=lm['sha256']:
        b=urllib.request.urlopen('https://185.184.42.88/downloads/TIO-Launcher.exe',timeout=60).read();assert sha(b)==lm['sha256'] and len(b)==lm['size'];LAUNCHER.write_bytes(b)
    (OUT/'qa-launcher.json').write_text(json.dumps(lm,indent=2));print(json.dumps(dict(passed=True,private_client=str(GAME),updated_public_files=changed,launcher=lm['version'])))

def stage(restore=False):
    proof=json.loads((OUT/'texture-proof.json').read_text(encoding='utf-8'));rows={r['path']:r for r in json.loads((OUT/'manifest-before.json').read_bytes())['files']}
    for t in proof:
        p=GAME/t['path'];saved=OUT/'qa-before'/t['path'];candidate=(ASSET/'native'/t['path']).read_bytes()
        if restore:
            assert sha(p.read_bytes())==t['sha256'];assert sha(saved.read_bytes())==rows[t['path']]['sha256'];p.write_bytes(saved.read_bytes())
        else:
            assert sha(p.read_bytes())==rows[t['path']]['sha256'];saved.parent.mkdir(parents=True,exist_ok=True)
            if saved.exists():assert saved.read_bytes()==p.read_bytes()
            else:saved.write_bytes(p.read_bytes())
            assert sha(candidate)==t['sha256'];p.write_bytes(candidate)
    print(json.dumps(dict(passed=True,private_files=len(proof),restored=restore)))

def launch(index,baseline=False,published=False):
    rows={r['path']:r for r in json.loads((OUT/'manifest-before.json').read_bytes())['files']};auth.HASHES={n:rows[n]['sha256'] for n in ('ti.exe','orange.dll','silver.dll')}
    data=json.loads(fixture.PRIVATE.read_text());lm=json.loads((OUT/'qa-launcher.json').read_text())
    bridge=auth.HostedGraphicalQaBridge(GAME,dict(login=data['names'][index],password=data['passwords'][index],fresh_qa=True),auto_select=True,launcher=LAUNCHER,launcher_sha256=lm['sha256'])
    try:
        # The genuine launcher has now verified/restored the public release.
        # Stage art only in this owned, not-yet-authenticated native process's
        # private directory, as the existing model QA bridge does.
        proof=json.loads((OUT/'texture-proof.json').read_text(encoding='utf-8'))
        for t in proof:
            p=GAME/t['path']
            if published:assert sha(p.read_bytes())==t['sha256']
            else:
                assert sha(p.read_bytes())==rows[t['path']]['sha256']
                if not baseline:
                    raw=(ASSET/'native'/t['path']).read_bytes();assert sha(raw)==t['sha256'];p.write_bytes(raw)
        variant='baseline' if baseline else 'published' if published else 'candidate'
        (OUT/f'gui-staged-{variant}-{index}.json').write_text(json.dumps(dict(passed=True,pid=bridge.pid,files=len(proof),variant=variant,staged_after_launcher_verification=variant=='candidate'),indent=2))
        print(json.dumps(dict(started=True,pid=bridge.pid,account=index,variant=variant,checked_files=len(proof))),flush=True)
        print(json.dumps(bridge.start_connect()),flush=True)
        for line in sys.stdin:
            if line.strip()=='stop':break
            s=bridge.status();(OUT/f'gui-status-{variant}-{index}.json').write_text(json.dumps(s,indent=2));print(json.dumps(s),flush=True)
    finally:bridge.release(cleanup=True);(OUT/f'gui-events-{variant}-{index}.json').write_text(json.dumps(bridge.events,indent=2))

def battle(finish=False):
    data=json.loads(fixture.PRIVATE.read_text());net=fixture.Network(data)
    try:
        for i in (0,1):net.connect(i)
        if finish:
            for i in (0,1):
                try:net.command(i,b'\x2a\x01')
                except (EOFError,ConnectionError):pass
        else:
            for i in (0,1):net.command(i,b'\xba\3\0\1')
            for i in (0,1):
                if not any(p[:1]==b'\x41' for p in net.received[i]):net.peers[i].until(b'\x41',max_packets=4096)
                net.command(i,b'\x36')
            from tio.protocol.battle_ground import decode_battle_ground
            packets=[next(p for p in net.received[i] if p[:1]==b'\x35') for i in (0,1)];assert packets[0]==packets[1]
            g=decode_battle_ground(packets[0]);r=dict(passed=True,two_accounts=True,graphical=False,shared_ground=True,dimensions=[g.width,g.height],objects=[e.name.decode() for e in g.entries]);(OUT/'hosted-shared-map.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
    finally:net.close()

def town(identity):
    data=json.loads(fixture.PRIVATE.read_text())
    code=r'''
import json,sqlite3
from tio.rating_visibility import QA_LOGIN,excluded
from tio.locations import LocationStore,center
path='/var/lib/tio-server/reservation.sqlite3'
with sqlite3.connect(path) as db:
 for name in request['names']:
  assert QA_LOGIN.fullmatch(name) and excluded(db,name)
  assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account=?',(name,)).fetchone()
  LocationStore._save(db,name,request['town'],*center(request['town']))
print(json.dumps(dict(passed=True,excluded_fixtures_only=True,town=request['town'])))
'''
    print(json.dumps(fixture.v.remote(code,dict(names=data['names'],town=identity))))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('setup','provision','stage','restore','launch','battle','finish','town','cleanup'));p.add_argument('--account',type=int,default=0,choices=(0,1));p.add_argument('--town',type=int,default=2,choices=(2,3,5,8));p.add_argument('--baseline',action='store_true');p.add_argument('--published',action='store_true');a=p.parse_args()
    if a.mode=='setup':setup()
    elif a.mode=='provision':fixture.provision()
    elif a.mode=='stage':stage()
    elif a.mode=='restore':stage(True)
    elif a.mode=='launch':
        assert not (a.baseline and a.published);launch(a.account,a.baseline,a.published)
    elif a.mode=='battle':battle()
    elif a.mode=='finish':battle(True)
    elif a.mode=='town':town(a.town)
    else:
        data=json.loads(fixture.PRIVATE.read_text())
        fixture.v.remote("import sqlite3,json\nfrom tio.rating_visibility import QA_LOGIN,excluded\nwith sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:\n for n in request:\n  assert QA_LOGIN.fullmatch(n) and excluded(db,n)\n  assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account=?',(n,)).fetchone(),'Finish owned match before cleanup'\nprint(json.dumps(dict(passed=True,no_owned_checkpoints=True)))",data['names'])
        fixture.cleanup()
