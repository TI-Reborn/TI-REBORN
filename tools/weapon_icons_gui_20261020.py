"""Own excluded hosted fixtures; genuine native client for candidate/published art."""
import argparse,hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import verify_launcher_required_hosted_20261020 as fixture
from tools import hosted_graphical_qa_bridge as auth
OUT=ROOT/'reports/weapon-icons-20261020'
fixture.OUT=OUT;fixture.PRIVATE=ROOT/'.secrets/weapon-icons-20261020.json'
GAME=ROOT/'work/launcher-required-20261020/native-client'
LAUNCHER=ROOT/'work/launcher-required-20261020/launcher/TIO Launcher.exe'
XML='base/shared config/items.xml'

FILL=r'''
import json,sqlite3
from tio.rating_visibility import QA_LOGIN,excluded
from tio.protocol.item_list import ItemRecord,encode_item_list
path='/var/lib/tio-server/reservation.sqlite3'
assert len(request['ids'])==len(set(request['ids']))==45
for name in request['names']:
 assert QA_LOGIN.fullmatch(name)
 with sqlite3.connect(path) as db:
  assert excluded(db,name)
  assert db.execute('SELECT count(*) FROM accounts WHERE login=?',(name,)).fetchone()[0]==1
  db.execute('DELETE FROM warehouse_places WHERE account=?',(name,))
  db.execute('DELETE FROM warehouse_items WHERE account=?',(name,))
  for index,template in enumerate(request['ids']):
   item=ItemRecord(60001+index,template,bytes(2),1,0,0,(350,350,350),bytes(4),None,bytes(3))
   db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',(name,item.instance_id,encode_item_list(0,(item,))))
   db.execute('INSERT INTO warehouse_places VALUES (?,?,?,?,?)',(name,item.instance_id,'city',3,'owned-weapon-icon-qa'))
print(json.dumps(dict(owned_fixtures_only=True,ranking_excluded=True,weapon_templates=45)))
'''


def launch():
    manifest=json.loads(urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=20).read())
    expected='2026.10.20.5';assert manifest['version']==expected
    rows={r['path']:r for r in manifest['files']}
    build=json.loads((OUT/'build.json').read_text(encoding='utf-8'))
    for name in ('ti.exe','orange.dll','silver.dll'):
        assert hashlib.sha256((GAME/name).read_bytes()).hexdigest()==rows[name]['sha256'],name
    assert hashlib.sha256((GAME/XML).read_bytes()).hexdigest() in (build['xml_sha256'],build['server_sha256'])
    for r in build['new_files']:assert hashlib.sha256((GAME/r['path']).read_bytes()).hexdigest()==r['sha256']
    auth.HASHES={name:rows[name]['sha256'] for name in ('ti.exe','orange.dll','silver.dll')}
    data=json.loads(fixture.PRIVATE.read_text());tag='published'
    bridge=auth.HostedGraphicalQaBridge(GAME,dict(login=data['names'][0],password=data['passwords'][0],fresh_qa=True),
        auto_select=True,launcher=LAUNCHER,launcher_sha256='52f29d6376dc6d5fc96ab13672bb05c4ca2802ff85236313ba06df7ca2533cc2')
    (OUT/f'gui-{tag}-client.json').write_text(json.dumps(dict(pid=bridge.pid,root=str(GAME),manifest_version=expected,candidate_art=False),indent=2))
    print(json.dumps(dict(started=True,pid=bridge.pid,mode=tag)),flush=True)
    try:
        print(json.dumps(bridge.start_connect()),flush=True)
        for line in sys.stdin:
            if line.strip()=='status':
                status=bridge.status();(OUT/f'gui-{tag}-status.json').write_text(json.dumps(status,indent=2));print(json.dumps(status),flush=True)
            elif line.strip()=='stop':break
    finally:
        bridge.release(cleanup=True);(OUT/f'gui-{tag}-events.json').write_text(json.dumps(bridge.events,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','published','cleanup'));a=p.parse_args()
    if a.mode=='provision':
        fixture.provision();data=json.loads(fixture.PRIVATE.read_text())
        build=json.loads((OUT/'build.json').read_text(encoding='utf-8'))
        result=fixture.v.remote(FILL,dict(names=data['names'],ids=build['changed_item_ids']))
        (OUT/'fixture-weapons.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    elif a.mode=='published':launch()
    else:fixture.cleanup()
