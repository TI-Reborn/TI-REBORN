"""Eight excluded disposable hosted TLS accounts, native training requests.

Credentials stay in memory unless --keep-fixtures explicitly keeps a private
file for the owned graphical harness. No real-player rows or clocks are edited.
"""
import argparse
import json
from pathlib import Path
import secrets
import socket
import ssl
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE=ROOT/'work/training-base-20261018/candidate'
sys.path[:0]=[str(CANDIDATE),str(CANDIDATE/'tests'),str(ROOT)]
from test_game_tls import GameTLSTests
from test_multi_account import MultiAccountTests
saved_path=list(sys.path)
from tools.verify_game_operations_hosted import CREATE,CLEANUP,remote
sys.path[:]=saved_path
from tio.protocol.assault import encode_request,CREATE_ROOM,JOIN_ROOM,SET_READY,START_ROOM,REQUEST_ROOMS
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.battle_move import BattleMove,encode_move_request
from tio.rating_visibility import QA_LOGIN
from tio.protocol.binary import Reader
REPORT=ROOT/'reports/training-base-20261018'
PRIVATE=ROOT/'.secrets/training-base-20261018.json'


def room_state(packet):
    if packet[:2]!=b'\xc8\x24':return None
    r=Reader(packet);r.read(2);identity=r.u32();count=r.u32();ready={}
    def string():
        r.read(r.u16()).decode('utf-8')
    for _ in range(count):
        player=r.u32();string();r.u8();r.u32();r.u8()
        for _ in range(r.u32()):
            r.u8();r.u32();r.u32();string()
            for _ in range(5):r.u32()
        ready[player]=r.u8()
    started=r.u8();r.finish()
    return dict(id=identity,count=count,ready=ready,started=started)

PREPARE=r'''
from dataclasses import replace
import json,sqlite3
from pathlib import Path
from tio.rating_visibility import QA_LOGIN,excluded
from tio.owned_pets import OwnedPetStore
from tio.squad import SquadStore
from tio.locations import LocationStore,center
from tio.level_progression import FLOORS
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
path='/var/lib/tio-server/reservation.sqlite3'
pet=decode_pet_info(bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex']),human_equipment=True)
raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':4,'0x8c4b05':FLOORS[3],'0x8c4a07':115,'0x8c4ab1':115}))
for name in request:
 assert QA_LOGIN.fullmatch(name)
 with sqlite3.connect(path) as db:
  assert excluded(db,name)
  assert not db.execute('SELECT 1 FROM owned_pets WHERE account=?',(name,)).fetchone()
 OwnedPetStore(path).ensure(name,raw,encode_item_list(1,()),human=True)
 SquadStore(path).assign(name,1,1)
 locations=LocationStore(path)
 with sqlite3.connect(path) as db:LocationStore._save(db,name,19,*center(19))
print(json.dumps(dict(only_owned_fixtures=True,level=4,town=19,ranking_excluded=True)))
'''

STATE=r'''
import json,sqlite3
from tio.rating_visibility import QA_LOGIN
from tio.battle_snapshot import loads
assert all(QA_LOGIN.fullmatch(n) for n in request)
marks=','.join('?' for n in request)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows=db.execute('SELECT DISTINCT c.match_id,c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m ON c.match_id=m.match_id WHERE m.account IN ('+marks+')',request).fetchall()
 result=[]
 for match,payload in rows:
  b=loads(payload)[0]['battle'];assert b['kind']=='training' and {r[0] for r in b['reward_roster'].values()}==set(request)
  arena=b['arena'];room=arena.rooms.snapshot()[0];field=b['field'];turn=arena._turns.get(room.room_id)
  result.append(dict(match=match,humans={str(o):r[0] for o,r in b['reward_roster'].items()},bots=len(b['bots']),
   turn=turn[0] if turn else None,loaded=len(arena._loading[room.room_id]),finished=b['finished'],
   ends=b['training_ends'],event=b['training_event'],scores=b['assault_points'].scores,flags=b['assault_points'].owners,
   actors=[dict(id=a.actor_id,owner=a.owner_id,x=a.x,y=a.y,ap=a.action_points,hp=a.health) for a in field._actors.values()]))
 rewards=db.execute('SELECT count(*) FROM battle_rewards WHERE account IN ('+marks+')',request).fetchone()[0]
print(json.dumps(dict(battles=result,rewards=rewards)))
'''

PLAN=r'''
import json,sqlite3
from collections import deque
from tio.battle_snapshot import loads
from tio.rating_visibility import QA_LOGIN
assert all(QA_LOGIN.fullmatch(n) for n in request['names'])
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 payload=db.execute('SELECT payload FROM battle_checkpoints WHERE match_id=?',(request['match'],)).fetchone()[0]
b=loads(payload)[0]['battle'];assert {r[0] for r in b['reward_roster'].values()}==set(request['names'])
arena=b['arena'];field=b['field'];turn=arena._turns.get(arena.rooms.snapshot()[0].room_id)
if turn is None:print(json.dumps(None))
else:
 owner=turn[0];a=field.actor(field.living_actor_ids(owner)[0]);start=a.x,a.y
 occupied={(p.x,p.y) for p in field._actors.values() if p.health and p.actor_id!=a.actor_id}
 goals=sorted(b['assault_points'].positions,key=lambda p:abs(p[0]-a.x)+abs(p[1]-a.y))
 frontier=deque([start]);previous={start:None};goal=None
 while frontier:
  p=frontier.popleft()
  if any(abs(p[0]-f[0])+abs(p[1]-f[1])<=2 for f in goals):goal=p;break
  for cell in ((p[0]-1,p[1]),(p[0]+1,p[1]),(p[0],p[1]-1),(p[0],p[1]+1)):
   if cell in previous or not field.inside(*cell) or cell in field.blocked or cell in occupied:continue
   door=field.doors.states.get(cell)
   if door is not None and not door:continue
   previous[cell]=p;frontier.append(cell)
 path=[]
 if goal is not None:
  while previous[goal] is not None:path.append(goal);goal=previous[goal]
  path=list(reversed(path))[:a.action_points]
 print(json.dumps(dict(owner=owner,actor=a.actor_id,path=path)))
'''


def cleanup(names,provision,matches):
    # Extend the existing transaction's ownership predicates to our exact
    # all-QA match IDs, so match-only admission/outbox records also disappear.
    code=CLEANUP.replace('len(names)==2','len(names)==8')
    code=code.replace("condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)",
        "\n  if 'match_id' in columns and request.get('matches'):\n   parts.append(quote('match_id')+' IN ('+','.join('?' for _ in request['matches'])+')');args+=request['matches']\n  condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)")
    assert code!=CLEANUP and "args+=request['matches']" in code
    return remote(code,dict(names=names,matches=matches,protected_before=provision['protected_before'],require_unchanged_players=False))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--keep-fixtures',action='store_true');parser.add_argument('--cleanup-only',action='store_true');parser.add_argument('--reuse',action='store_true');args=parser.parse_args()
    if args.cleanup_only:
        data=json.loads(PRIVATE.read_text());value=cleanup(data['names'],data['provision'],data['matches']);PRIVATE.unlink()
        (REPORT/'fixture-cleanup.json').write_text(json.dumps(value,indent=2));print(json.dumps(value));return
    names=['qt'+secrets.token_hex(4)+'a' for _ in range(8)]
    assert len(set(names))==8 and all(QA_LOGIN.fullmatch(n) for n in names)
    passwords=[secrets.token_urlsafe(24) for _ in names]
    saved=json.loads(PRIVATE.read_text()) if args.reuse else None
    if saved:names,passwords=saved['names'],saved['passwords']
    case=MultiAccountTests();case.clients=[];tls=GameTLSTests();tls.case=case
    context=ssl.create_default_context();peers=[];provision=None;matches=list(saved.get('matches',())) if saved else []
    report=dict(passed=False,graphical_clients=False,fixtures=names,checks={})
    def connect(kind,*,preface=None,**kwargs):
        raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
        channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');case.clients.append(channel)
        if preface is not None:channel.sendall(preface)
        return channel
    tls.connect=connect
    cleared_counts=set();completed_counts=set()
    def command(index,packet=None,expected=None):
        peer=peers[index]
        if packet is not None:peer.send(packet)
        peer.send(b'\x70');received=[];fenced=False;deadline=time.monotonic()+20
        if packet and packet[0]==0x79:expected=b'\xc8\x2d'+struct.pack('<H',packet[1])
        elif packet and packet[:2]==b'\xc8\x1d':expected=b'\xc8\x24'
        for _ in range(4096):
            if time.monotonic()>deadline:raise AssertionError('Native request response deadline')
            reply=peer.receive()
            if reply==b'\xc8\x38'+bytes(8):cleared_counts.add(index)
            if reply==b'\xc8\x38'+struct.pack('<II',1,1):completed_counts.add(index)
            if reply==b'\x9e':fenced=True
            received.append(reply)
            if reply.startswith(b'\xf0\x8a\x01\0\0'):
                raise AssertionError('Training request rejected: '+reply[13:-2].decode('utf-16-le',errors='replace'))
            if fenced and (expected is None or any(expected(p) if callable(expected) else p.startswith(expected) for p in received)):return received
        raise AssertionError('Missing native ping fence')
    def read_remote(code,data):
        for attempt in range(3):
            try:return remote(code,data)
            except RuntimeError:
                if attempt==2:raise
                time.sleep(.5)
    def state():return read_remote(STATE,names)
    def wait(predicate,seconds=15):
        deadline=time.monotonic()+seconds
        while True:
            value=state()
            if predicate(value):return value
            if time.monotonic()>=deadline:raise AssertionError('Hosted training state timeout')
            for i in range(len(peers)):command(i)
            time.sleep(.15)
    try:
        provision=saved['provision'] if saved else remote(CREATE,list(zip(names,passwords)))
        if not saved:report['fixture_setup']=remote(PREPARE,names)
        if args.keep_fixtures:PRIVATE.write_text(json.dumps(dict(names=names,passwords=passwords,provision=provision,matches=matches)))
        for i in range(8):
            peer=tls.handoff(tls.begin(names[i],36001+i,password=passwords[i]));case.enter(peer,names[i]);peers.append(peer)
        report['checks']['eight_distinct_tls_logins']=True
        print(json.dumps(dict(stage='eight TLS logins accepted')),flush=True)
        existing=state()['battles']
        for town in (() if existing else (19,20,21,22)):
            replies=command(0,bytes((0x79,town)))
            p=next(p for p in replies if p[:4]==b'\xc8\x2d'+struct.pack('<H',town))
            assert len(p)>50 and p[37]==1 and int.from_bytes(p[38:42],'little')==1
        report['checks']['map_poll_keeps_registration_all_four_bases']=not bool(existing)
        print(json.dumps(dict(stage='four map replies preserve training state')),flush=True)
        groups=[];started=time.monotonic()
        for offset in (() if existing else (0,4)):
            replies=command(offset,encode_request(CREATE_ROOM))
            room=next(p for p in replies if p[:2]==b'\xc8\x24');identity=int.from_bytes(room[2:6],'little');groups.append(identity)
            if offset==0:
                assert any(p[:2]==b'\xc8\x26' and identity.to_bytes(4,'little') in p for p in command(7,expected=b'\xc8\x26'))
            for i in range(offset+1,offset+4):
                command(i,encode_request(JOIN_ROOM,identity),expected=lambda p:bool((r:=room_state(p)) and r['id']==identity and r['count']==i-offset+1))
            for i in range(offset,offset+4):
                command(i,encode_request(SET_READY,1),expected=lambda p:bool((r:=room_state(p)) and r['id']==identity and r['ready'].get(1)==1))
            command(offset,encode_request(START_ROOM),expected=lambda p:bool((r:=room_state(p)) and r['id']==identity and r['started']==1))
            if offset==0:assert not state()['battles']
        b=wait(lambda s:len(s['battles'])==1)['battles'][0]
        if b['match'] not in matches:matches.append(b['match'])
        report['elapsed_to_match_seconds']=round(time.monotonic()-started,3)
        assert b['bots']==0 and len(b['humans'])==8 and b['event']['on_demand']
        assert (60 if existing else 850)<b['ends']-time.time()<=900
        report['resumed_prior_qa_match']=bool(existing)
        report['checks']['one_group_waits_two_groups_start_without_schedule']=not bool(existing)
        print(json.dumps(dict(stage='shared eight-account training started',elapsed=report['elapsed_to_match_seconds'])),flush=True)
        for i in range(8):command(i,b'\x36')
        b=wait(lambda s:s['battles'] and s['battles'][0]['turn'] is not None)['battles'][0]
        owners={int(o):names.index(n) for o,n in b['humans'].items()}
        report['moves']=0
        for _ in range(32):
            plan=read_remote(PLAN,dict(names=names,match=b['match']))
            if plan is None:time.sleep(.2);continue
            index=owners[plan['owner']]
            if plan['path']:
                replies=command(index,encode_move_request(BattleMove(plan['actor'],tuple(map(tuple,plan['path'])))),expected=lambda p:p[:5]==b'\x3d'+plan['actor'].to_bytes(4,'little'))
                assert any(p[0]==0x3d for p in replies);report['moves']+=1
            current=state()['battles'][0]
            if current['turn']==plan['owner']:command(index,encode_end_turn())
            b=wait(lambda s:s['battles'] and s['battles'][0]['turn']!=plan['owner'])['battles'][0]
            if max(b['scores'])>0:break
        assert (report['moves']>0 or existing) and max(b['scores'])>0,(report['moves'],b['scores'])
        report['scores']=b['scores'];report['checks']['native_movement_flag_capture_whole_round_score']=True
        # A genuine reconnect must retain this shared field and flag scores.
        peers[7].sock.close();time.sleep(.5)
        peer=tls.handoff(tls.begin(names[7],36107,password=passwords[7]));case.enter(peer,names[7]);peers[7]=peer
        assert state()['battles'][0]['match']==b['match'];command(7,b'\x36')
        report['checks']['reconnect_preserves_shared_match']=True
        for i in range(4):command(i,b'\x2a\x01',expected=b'\xc8\x38'+bytes(8))
        final=wait(lambda s:s['rewards']==8)
        assert final['rewards']==8
        report['checks']['all_eight_results_settle']=True
        for i in range(8):command(i,b'\x2a\x01',expected=None if i<4 else b'\xc8\x38'+bytes(8))
        time.sleep(.5)
        assert state()['rewards']==8
        report['checks']['results_not_duplicated']=True
        assert len(cleared_counts)==8 and len(completed_counts)>=4
        report['checks']['native_unfinished_counter_clears_for_all_eight']=True
        report['passed']=True
    finally:
        for channel in case.clients:
            try:channel.close()
            except OSError:pass
        if provision is not None:
            data=dict(names=names,passwords=passwords,provision=provision,matches=matches)
            if args.keep_fixtures:
                PRIVATE.write_text(json.dumps(data));report['fixtures_kept_for_owned_gui']=True
            else:
                time.sleep(1)
                # Failed scenarios may still be journaled. Never delete a live
                # checkpoint: leave explicit private ownership for recovery.
                remaining=state()
                if any(not b['finished'] for b in remaining['battles']):
                    PRIVATE.write_text(json.dumps(data));report['cleanup_pending']=True
                else:report['cleanup']=cleanup(names,provision,matches)
        (REPORT/'hosted-verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':main()
