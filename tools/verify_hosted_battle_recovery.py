"""Public two-account gameplay plus read-only durable-state checks on the VPS."""
from verify_hosted_rewards import reward_run,ROOT
from verify_hosted_player_statistics import profiles
from pathlib import Path
import json,shlex,subprocess,sys


def query(names,*,active):
    code='''from contextlib import closing
import sys,json,sqlite3,time
sys.path.insert(0,'/opt/tio-emulator')
from tio import battle_checkpoints,battle_snapshot
names=json.load(sys.stdin)
rows=[r for r in battle_checkpoints.read('/var/lib/tio-server/reservation.sqlite3') if set(r[4])&set(names)]
out=[]
for match,payload,checksum,status,members in rows:
 state,_=battle_snapshot.loads(payload);b=state['battle'];field=b['field']
 out.append(dict(match_id=match,accounts=sorted(members),status=status,ground_sha=__import__('hashlib').sha256(b['ground']).hexdigest(),
  actors={a:field.actor_ids(o) for a,o in members.items()},positions={a:[(field.actor(i).x,field.actor(i).y) for i in field.actor_ids(o)] for a,o in members.items()}))
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 revisions={r[0]:r[1] for r in db.execute('SELECT match_id,revision FROM battle_checkpoints')}
 rewards={n:db.execute('SELECT count(*) FROM battle_rewards WHERE account=?',(n,)).fetchone()[0] for n in names}
 pending={n:db.execute('SELECT count(*) FROM battle_settlement_jobs WHERE account=?',(n,)).fetchone()[0] for n in names}
for r in out:r['revision']=revisions[r['match_id']]
print(json.dumps(dict(checkpoints=out,rewards=rewards,pending=pending)))'''
    p=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+sys.argv[1],
        '/opt/tio-emulator/.venv/bin/python -c '+shlex.quote(code)],input=json.dumps(names),capture_output=True,text=True,check=True,timeout=30)
    return json.loads(p.stdout)


def active_check(names,actors,result):
    data=query(names,active=True);result['active_checkpoint']=data
    assert len(data['checkpoints'])==1,data
    row=data['checkpoints'][0]
    assert row['accounts']==sorted(names) and row['status']=='active' and row['revision']>=3,row
    for name,actor in zip(names,actors):
        assert row['actors'][name]==[actor.soldier_id],row
        assert row['positions'][name]==[[actor.fields['0x8c519b'],actor.fields['0x8c51af']]],row
    assert not any(data['rewards'].values()) and not any(data['pending'].values()),data
    result['checks'].append('Hosted active snapshot binds both authenticated QA accounts and the exact native actor IDs/positions')


def finish_check(peers,names,summaries,result,case):
    profiles(peers,names,summaries,result,case)
    data=query(names,active=False);result['completed_checkpoint']=data
    assert not data['checkpoints'] and all(v==1 for v in data['rewards'].values()) and not any(data['pending'].values()),data
    result['checks'].append('Hosted completion deletes checkpoints; one reward receipt per account; no pending settlement')


if __name__=='__main__':
    result=reward_run(sys.argv[1],profile_check=finish_check,battle_check=active_check)
    result['kind']='two authenticated QA accounts over native public TCP; read-only hosted SQLite verification; no graphical clients or production fault injection'
    (ROOT/'reports/stage3-battle-recovery/hosted-verification.json').write_text(json.dumps(result,indent=2)+'\n')
