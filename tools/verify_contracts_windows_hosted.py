"""Owned two-client native acceptance. Credentials stay in a private fixture file."""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
saved=list(sys.path)
from tools.verify_game_operations_hosted import remote,CREATE,CLEANUP
sys.path[:]=saved
from tools import hosted_graphical_qa_bridge as auth
from tools.verify_area_fire_hosted_20261018 import PREPARE
sys.path[:]=saved

OUT=ROOT/'reports/contracts-interface-20261022'
PRIVATE=ROOT/'.secrets/contracts-interface-20261022.json'
WORK=ROOT/'work/contracts-interface-20261022'


def provision():
    if PRIVATE.exists():raise RuntimeError('Owned fixture receipt already exists')
    prefix='qc'+secrets.token_hex(4)
    data=dict(names=[prefix+'a',prefix+'b'],passwords=[secrets.token_urlsafe(24) for _ in range(2)])
    data['provision']=remote(CREATE,list(zip(data['names'],data['passwords'])))
    PRIVATE.write_text(json.dumps(data),encoding='utf-8')
    result=remote(PREPARE,data['names'])
    (OUT/'graphical-provision.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(dict(created=2,ranking_excluded=True)))


STATE=r'''
import json,sqlite3
from tio.rating_visibility import QA_LOGIN,excluded
from tio.battle_snapshot import loads
names=request['names'];assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 assert all(excluded(db,n) for n in names)
 result={'ranking_excluded':True,'groups':[],'contracts':[],'battles':[]}
 for p,leader,state,revision in db.execute('SELECT id,leader,state,revision FROM travel_party_groups WHERE leader IN (?,?)',names):
  members=list(db.execute('SELECT owner,ready,online FROM travel_party_members WHERE party_id=?',(p,)))
  assert {m[0] for m in members}<=set(names)
  result['groups'].append(dict(id=p,leader=names.index(leader),state=state,revision=revision,members=[dict(index=names.index(n),ready=r,online=o) for n,r,o in members]))
 for identity,state,outcome in db.execute('SELECT id,state,outcome FROM pve_contract_instances WHERE leader IN (?,?) ORDER BY accepted_at',names):
  assert {r[0] for r in db.execute('SELECT owner FROM pve_contract_members WHERE instance_id=?',(identity,))}<=set(names)
  result['contracts'].append(dict(id=identity,state=state,outcome=outcome))
 for match,payload in db.execute('SELECT DISTINCT c.match_id,c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m USING(match_id) WHERE m.account IN (?,?)',names):
  b=loads(payload)[0]['battle'];assert {r[0] for r in b['reward_roster'].values()}<=set(names)
  turn=b['arena']._turns.get(b['room'].room_id)
  result['battles'].append(dict(match=match,kind=b['kind'],finished=b['finished'],turn=turn[0] if turn else None,
   actors=[dict(id=a.actor_id,owner=a.owner_id,hp=a.health,ap=a.action_points,x=a.x,y=a.y) for a in b['field']._actors.values()]))
 print(json.dumps(result))
'''


def launch(count=2,first=0):
    data=json.loads(PRIVATE.read_text());manifest=json.loads((WORK/'client-manifest-current.json').read_text())
    auth.HASHES={n:next(r['sha256'] for r in manifest['files'] if r['path']==n) for n in ('ti.exe','orange.dll','silver.dll')}
    launcher=WORK/'release/TIO Launcher.exe';bridges=[]
    try:
        for i in range(first,first+count):
            bridge=auth.HostedGraphicalQaBridge(WORK/f'clients/game-{chr(97+i)}',dict(login=data['names'][i],password=data['passwords'][i],fresh_qa=True),
                auto_select=True,launcher=launcher,launcher_sha256=hashlib.sha256(launcher.read_bytes()).hexdigest())
            bridges.append(bridge);bridge.start_connect()
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                status=bridge.status()
                if status.get('worldStartSent'):break
                time.sleep(.2)
            else:raise RuntimeError('Native client did not enter the world')
            print(json.dumps(dict(native_client=i,pid=bridge.pid,world_entered=True)),flush=True)
        (OUT/'graphical-start.json').write_text(json.dumps(dict(pids=[b.pid for b in bridges],real_native_clients=count,gameplay_on_host=True)))
        for line in sys.stdin:
            action=line.strip()
            if action=='stop':break
            if action=='status':
                value=remote(STATE,data);(OUT/'graphical-state.json').write_text(json.dumps(value,indent=2));print(json.dumps(value),flush=True)
    finally:
        for b in bridges:
            try:b.release(cleanup=True)
            except Exception:pass


def cleanup():
    data=json.loads(PRIVATE.read_text())
    # Close/disconnect clients before invoking cleanup. Checkpoints must have
    # completed normally; this never deletes a retained live battle.
    script=r'''
import json,sqlite3
from tio.rating_visibility import QA_LOGIN
names=request['names'];assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
db=sqlite3.connect('/var/lib/tio-server/reservation.sqlite3');db.execute('BEGIN IMMEDIATE')
assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account IN (?,?)',names).fetchone()
assert not db.execute('SELECT 1 FROM travel_party_members WHERE owner IN (?,?) AND online=1',names).fetchone()
partyids={r[0] for r in db.execute('SELECT id FROM travel_party_groups WHERE leader IN (?,?)',names)}
instances=list(db.execute('SELECT id,party_id FROM pve_contract_instances WHERE leader IN (?,?)',names))
for identity,party in instances:
 assert {r[0] for r in db.execute('SELECT owner FROM pve_contract_members WHERE instance_id=?',(identity,))}<=set(names)
 partyids.add(int(party))
 for table in ('pve_contract_events','pve_contract_members','pve_contract_awards','pve_contract_locks'):
  db.execute('DELETE FROM '+table+' WHERE instance_id=?',(identity,))
 db.execute('DELETE FROM pve_contract_requests WHERE instance_id=?',(identity,))
 db.execute('DELETE FROM pve_contract_instances WHERE id=?',(identity,))
for p in partyids:
 assert {r[0] for r in db.execute('SELECT owner FROM travel_party_members WHERE party_id=?',(p,))}<=set(names)
 db.execute('DELETE FROM travel_party_journeys WHERE party_id=?',(str(p),))
 db.execute('DELETE FROM travel_party_invitations WHERE party_id=?',(p,))
 db.execute('DELETE FROM travel_party_groups WHERE id=?',(p,))
db.commit();db.close();print(json.dumps(dict(owned_instances=len(instances),owned_parties=len(partyids))))
'''
    first=remote(script,data)
    # Ordinary players may have progressed since yesterday. CLEANUP still checks
    # every unrelated row and the entire schema inside its deletion transaction.
    result=remote(CLEANUP,dict(names=data['names'],protected_before=data['provision']['protected_before'],require_unchanged_players=False))
    (OUT/'cleanup.json').write_text(json.dumps(dict(contracts=first,accounts=result),indent=2))
    PRIVATE.unlink();print(json.dumps(dict(cleaned=True,unrelated_rows_preserved=True)))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','launch','status','cleanup'));p.add_argument('--clients',type=int,choices=(1,2),default=2);p.add_argument('--first',type=int,choices=(0,1),default=0);a=p.parse_args();assert a.first+a.clients<=2
    if a.mode=='provision':provision()
    elif a.mode=='launch':launch(a.clients,a.first)
    elif a.mode=='cleanup':cleanup()
    else:print(json.dumps(remote(STATE,json.loads(PRIVATE.read_text()))))
