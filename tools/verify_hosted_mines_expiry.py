"""One fresh owned TLS mine, then real 180-second offline expiry, read-only.

Requires a previously provisioned/setup trio and an active reviewed ingress
lease. Creates no accounts, fixtures, claims, clocks, restarts or DB writes.
After Loaded it sends no gameplay command or login; it only closes sockets
and observes the genuine server expiry. Gate release remains the operator's.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.verify_hosted_shared_mines import (
    MinesFixture,make_network,close_all,source_guard,validate_shared_snapshot,
    validate_wire_ground,safe_assertion_diagnostic,GATE_CHECK)
from tools.verify_hosted_arena_surroundings import OWNERSHIP,require

GRACE_SECONDS=180
WAIT_SECONDS=190
MAX_WAIT_SECONDS=215
POLL_SECONDS=10

EXPIRY_READ=OWNERSHIP+GATE_CHECK+r'''
import subprocess,time,re
from contextlib import closing
from tio.battle_snapshot import loads
properties=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','NRestarts',
 '-p','ActiveState','-p','SubState','-p','ExecMainStartTimestampMonotonic'],text=True)
service=dict(line.split('=',1) for line in properties.splitlines() if '=' in line)
service['MainPID']=int(service['MainPID']);service['NRestarts']=int(service['NRestarts'])
assert int(re.search(r'^RECONNECT_SECONDS=(\d+)$',pathlib.Path('server/battle_reconnect.py').read_text(),re.M)[1])==180
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 db.execute('BEGIN')
 counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs')}
 foreign=db.execute('SELECT count(*) FROM battle_checkpoint_members WHERE account NOT IN (?,?,?)',names).fetchone()[0]
 foreign+=db.execute('SELECT count(*) FROM battle_settlement_jobs WHERE account NOT IN (?,?,?)',names).fetchone()[0]
 assert foreign==0,'Foreign retained player; stop QA observation'
 rows=db.execute('SELECT match_id,payload FROM battle_checkpoints').fetchall();checkpoint=None
 assert len(rows)<=1,'Unexpected second checkpoint'
 if rows:
  identity,payload=rows[0];state,_=loads(payload,rebase=False);b=state['battle']
  roster={o:r[0] for o,r in b['reward_roster'].items()}
  assert b.get('kind')=='mine' and set(roster.values())==set(names),'Unexpected mine roster'
  if data['match'] is not None:assert identity==data['match'],'Owned expiry changed match'
  metadata=state['sessions'];cached=b.get('durable_sessions',{})
  assert set(metadata)==set(roster) and all(metadata[o]['account']==roster[o] for o in roster)
  assert set(cached)==set(roster) and all(cached[o]['account']==roster[o] for o in roster),'Joined-owner durable cache incomplete'
  checkpoint=dict(match=identity,retained_accounts=[metadata[o]['account'] for o in state['retained']],
   offline_remaining={metadata[o]['account']:round(deadline-time.monotonic(),3) for o,deadline in state['offline'].items()},
   round=b['field'].mining.round,cache_accounts=[cached[o]['account'] for o in cached])
 match=data['match']
 reward_rows=[];mining=[]
 if match is not None:
  reward_rows=[dict(account=a,result=r,credits=c,gross=g,rental_tax=t) for a,r,c,g,t in db.execute(
   'SELECT account,result,credits,gross,rental_tax FROM battle_rewards WHERE match_id=? ORDER BY account',(match,))]
  assert set(r['account'] for r in reward_rows)<=set(names),'Foreign reward receipt'
  mining=[json.loads(raw) for raw, in db.execute('SELECT receipt_json FROM mine_crystal_extractions WHERE match_id=? ORDER BY extractor',(match,))]
  assert set(r['extractor'] for r in mining)<=set(names),'Foreign mining receipt'
  failure_rows=db.execute('SELECT count(*) FROM battle_failure_audit WHERE match_id=?',(match,)).fetchone()[0]
 else:failure_rows=0
 print(json.dumps(dict(service=service,grace_seconds=180,durable=counts,checkpoint=checkpoint,
  rewards=reward_rows,mining_receipts=mining,failure_audit_rows=failure_rows)))
'''

def sample(fixture,match):
    return fixture.remote(EXPIRY_READ,{**fixture.ownership_payload(),'gate':fixture.gate,'match':match})

def validate_service(before,after):
    require(before['MainPID']>0 and before['ActiveState']=='active' and before['SubState']=='running',
            'Expiry QA requires a running service')
    require(all(before[k]==after[k] for k in ('MainPID','NRestarts','ExecMainStartTimestampMonotonic')) and
            after['ActiveState']=='active' and after['SubState']=='running',
            'Service restarted or stopped during actual reconnect expiry')

def validate_terminal(value,names,match,elapsed):
    require(elapsed>=WAIT_SECONDS,'Observe the real grace plus ten seconds before terminal acceptance')
    require(value['grace_seconds']==GRACE_SECONDS and value['checkpoint'] is None and
            not any(value['durable'].values()),'Expiry must clear all checkpoints/members/jobs')
    rewards=value['rewards'];receipts=value['mining_receipts']
    require(len(rewards)==3 and {r['account'] for r in rewards}==set(names),
            'Exactly three own terminal reward receipts required')
    require(len(receipts)==3 and {r['extractor'] for r in receipts}==set(names) and
            all(r['match_id']==match and r['gross']==r['tax']==0 and
                not any(r['payouts'].values()) for r in receipts),
            'Exactly three own zero-gross mining receipts required')
    require(all(r['result']==r['credits']==r['gross']==r['rental_tax']==0 for r in rewards),
            'Offline empty mine must settle once without credit income')
    require(value['failure_audit_rows']==0,'Expiry produced a battle failure audit')
    return dict(real_grace_seconds=GRACE_SECONDS,elapsed_seconds=round(elapsed,3),
                terminal_reward_receipts=3,zero_gross_mining_receipts=3,durable=value['durable'])

def validate_fresh(fixture,economy,status):
    require(not status['receipts'] and not any(status['durable'].values()) and status['clan'] and
            all(r['town']==13 for r in status['locations']),
            'Expiry accepts only a fresh once-prepared trio without prior missions')
    require({m['account'] for m in status['members']}=={fixture.names[0],fixture.names[2]} and
            not any(status['amounts'].values()),'Only the freshly owned miner/defender clan is allowed')
    for state in economy['states']:
        require(state['wallet']==[3050,0] and not state['receipts'] and len(state['pets'])==1,
                'Fresh setup wallet and empty battle history required')
        pet=state['pets'][0]
        require((pet['level'],pet['xp'],pet['hp'],pet['max_hp'],pet['rank_points'])==(4,7355,115,115,0),
                'Fresh ordinary-health Lv4 fixture required; old played trio refused')

def expiry_owned(fixture,args,report,*,clock=time.monotonic,sleep=time.sleep):
    economy=source_guard(fixture);fixture.guard_gate();fixture.guard_connections(0)
    validate_fresh(fixture,economy,fixture.status())
    lease_end=datetime.fromisoformat(fixture.gate['deadline_utc'])
    require((lease_end-datetime.now(timezone.utc)).total_seconds()>=450,
            'Need at least 450 seconds of unchanged maintenance lease before admission')
    baseline=sample(fixture,None);report['service_before']=baseline['service']
    validate_service(baseline['service'],baseline['service'])
    require(not any(baseline['durable'].values()),'Expiry starts only with empty retained state')
    net=make_network(fixture,args);dropped=False
    report['stage']='admission'
    try:
        for i in range(3):net.attach(i)
        for i,role in ((0,1),(2,3),(1,2)):
            net.command(i,bytes((0xb0,0x14,role)))
            require(b'\x41' in net.received[i],'Native mine scene missing during expiry admission')
        admitted=fixture.snapshot_mine();report['admission']=validate_shared_snapshot(admitted,fixture.names)
        require(admitted['claim']['owner_clan']==fixture.status()['clan'] and admitted['claim']['tax_percent']==10,
                'Expiry battle must freeze the owned QA claim')
        grounds=[next(p for p in net.received[i] if p[:1]==b'\x35') for i in range(3)]
        report['native_ground']=validate_wire_ground(grounds,admitted['ground_sha256'])
        for i in range(3):
            require(b'\xb2\x0a\1' in net.received[i],'Native mine flag missing during expiry admission')
            net.command(i,b'\x36')
        require(fixture.snapshot_mine()['loading_complete'],'All three native clients must complete Loaded')
        match=admitted['match'];report['match']=match
        loaded=sample(fixture,match);validate_service(baseline['service'],loaded['service'])
        report['loaded_checkpoint']=loaded['checkpoint']
        require(set(loaded['checkpoint']['cache_accounts'])==set(fixture.names),
                'Joined owners must be cached before the real disconnect')
        # Critical: no Leave/Finish, turn, movement, relogin or ping follows.
        close_all(net);dropped=True;start=clock()
        report['socket_drop_utc']=datetime.now(timezone.utc).isoformat()
        report['stage']='read_only_real_expiry';report['observations']=[]
        offline=sample(fixture,match)
        require(offline['checkpoint'] is not None and
                set(offline['checkpoint']['offline_remaining'])==set(fixture.names),
                'All three socket drops must become offline reconnect reservations')
        require(all(165<=v<=GRACE_SECONDS for v in offline['checkpoint']['offline_remaining'].values()),
                'Actual server reconnect deadlines must be the normal 180-second grace')
        final=None
        while True:
            elapsed=clock()-start
            value=sample(fixture,match);validate_service(baseline['service'],value['service'])
            report['observations'].append(dict(elapsed_seconds=round(elapsed,3),**value))
            print(json.dumps(dict(stage=report['stage'],elapsed_seconds=round(elapsed,1),
                pid=value['service']['MainPID'],restarts=value['service']['NRestarts'],durable=value['durable'])),flush=True)
            if elapsed>=WAIT_SECONDS and not any(value['durable'].values()):final=value;break
            require(elapsed<MAX_WAIT_SECONDS,'Real reconnect expiry did not finish within bounded 215 seconds')
            sleep(min(POLL_SECONDS,MAX_WAIT_SECONDS-elapsed))
        report['terminal']=validate_terminal(final,fixture.names,match,clock()-start)
        # Another read-only observation, with no reauthentication/replay call,
        # proves receipt immutability on later ordinary server ticks.
        sleep(5);stable=sample(fixture,match);validate_service(baseline['service'],stable['service'])
        require(stable['rewards']==final['rewards'] and stable['mining_receipts']==final['mining_receipts'] and
                not any(stable['durable'].values()),'Terminal receipt changed on later expiry ticks')
        report['terminal']['later_read_only_receipts_identical']=True
        report['service_after']=stable['service'];report['tls']=net.audit()
        fixture.guard_connections(0);report['post_expiry_economy']=source_guard(fixture)
        report['preservation']=fixture.preservation();report['passed']=True
        report['stage']='complete';report['cleanup']=dict(owned_sockets_closed=True,durable=stable['durable'],gate_left_closed=True)
    finally:
        net.close();net.peers.clear()
        report.setdefault('cleanup',dict(owned_sockets_closed=True,gate_left_closed=True,
                                          ordinary_disconnect_done=dropped,terminal_verified=False))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture',type=Path,required=True);p.add_argument('--gate',type=Path,required=True)
    p.add_argument('--server-name',default='ti-reborn.com');p.add_argument('--ca-file',type=Path)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();target=args.output.resolve()
    require(target.parent==ROOT/'reports/shared-mines' and not target.exists(),'Preserve existing expiry reports')
    require(args.server_name=='ti-reborn.com' or args.ca_file,'Strict production TLS hostname required')
    report=dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),passed=False,
                kind='Three real protocol TLS sessions and genuine offline expiry; no graphical-client claim')
    try:
        fixture=MinesFixture.load_private(args.fixture);fixture.gate=json.loads(args.gate.read_text())
        require(fixture.gate['version']==1 and fixture.gate['accounts']==fixture.names,
                'Maintenance lease must pin exactly this fresh trio')
        report.update(accounts=fixture.names,private_fixture=fixture.credential_path,
                      pre_provision_backup=fixture.backup,lease_id=fixture.gate['lease_id'])
        expiry_owned(fixture,args,report)
    except Exception as exc:
        report['error_type']=type(exc).__name__;report.update(safe_assertion_diagnostic(exc,public_source=Path(__file__)))
    finally:
        report['finished_utc']=datetime.now(timezone.utc).isoformat();target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('x',encoding='utf-8') as out:json.dump(report,out,indent=2)
    print(json.dumps(dict(passed=report['passed'],report=str(target))))
    if not report['passed']:raise SystemExit(1)

if __name__=='__main__':main()
