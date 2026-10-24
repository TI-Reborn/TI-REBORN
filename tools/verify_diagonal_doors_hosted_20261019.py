"""Two excluded QA accounts operate real map doors diagonally over public TLS.

Administrative reads inspect checkpoints; all movement and door changes use
ordinary game packets. No graphical client acceptance is claimed.
"""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import verify_area_fire_hosted_20261018 as qa
from tio.protocol.battle_door import DoorRequest,encode_door_request,encode_door_state
from tio.protocol.battle_move import BattleMove,encode_move_request
qa.OUT=ROOT/'reports/diagonal-doors-20261019'
qa.PRIVATE=ROOT/'.secrets/diagonal-doors-20261019.json'

qa.STATE=r'''
import json,sqlite3
from collections import deque
from tio.rating_visibility import QA_LOGIN,excluded
from tio.battle_snapshot import loads
names=request['names'];assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 assert all(excluded(db,n) for n in names)
 row=db.execute('SELECT c.match_id,c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m USING(match_id) WHERE m.account=?',(names[0],)).fetchone()
 if not row:print(json.dumps(None))
 else:
  b=loads(row[1])[0]['battle'];f=b['field'];turn=b['arena']._turns.get(b['room'].room_id)
  assert {r[0] for r in b['reward_roster'].values()}==set(names) and not b['bots']
  result=dict(match=row[0],finished=b['finished'],turn=turn[0] if turn else None,
   doors=[[x,y,s] for (x,y),s in f.doors.states.items()],
   actors=[dict(id=a.actor_id,owner=a.owner_id,account=b['reward_roster'][a.owner_id][0],x=a.x,y=a.y,ap=a.action_points,hp=a.health) for a in f._actors.values()])
  if request.get('plan') and not b['finished'] and turn:
   actor=next(a for a in f._actors.values() if a.owner_id==turn[0] and a.health)
   occupied={(a.x,a.y) for a in f._actors.values() if a.health and a.actor_id!=actor.actor_id}
   start=actor.x,actor.y;queue=deque([start]);prev={start:None};goal=None;door=None
   while queue and goal is None:
    p=queue.popleft()
    for d in f.doors.states:
     dx,dy=abs(p[0]-d[0]),abs(p[1]-d[1])
     if dx==dy==1 and ((p[0],d[1]) in f.blocked or (d[0],p[1]) in f.blocked):goal=p;door=d;break
    if goal is not None:break
    for n in ((p[0]-1,p[1]),(p[0]+1,p[1]),(p[0],p[1]-1),(p[0],p[1]+1)):
     if n in prev or n in f.blocked or n in occupied or not f.inside(*n):continue
     prev[n]=p;queue.append(n)
   assert goal is not None,'No reachable diagonal door with a wall corner'
   result['door']=door;result['wall_corner']=True
   route=[]
   while goal!=start:route.append(goal);goal=prev[goal]
   result['route']=list(reversed(route))[:max(0,min(6,(actor.action_points-2)//f.step_cost))]
   result['at_goal']=not route
  print(json.dumps(result))
'''

def denied(net,index,packet):
    peer=net.peers[index];peer.send(packet);peer.send(b'\x70');rows=[]
    for _ in range(4096):
        p=peer.receive();rows.append(p)
        if p==b'\x9e':break
    assert any(p.startswith(b'\xf0\x8a\1\0\0') for p in rows)

def run():
    data=qa.load();net=qa.Network(data)
    report=dict(passed=False,graphical_clients=False,humans=2,bots=0,public_tls=True,cases=[])
    try:
        for i in (0,1):net.connect(i)
        for i in (0,1):net.command(i,b'\xba\3\0\1')
        for i in (0,1):
            if not any(p[0]==0x41 for p in net.received[i]):net.peers[i].until(b'\x41',max_packets=4096)
        initial=qa.state(data);data['matches'].append(initial['match']);qa.save(data)
        for i in (0,1):net.command(i,b'\x36')
        completed=set();deadline=time.monotonic()+240
        while len(completed)<2 and time.monotonic()<deadline:
            frame=qa.state(data,True);assert frame and not frame['finished']
            a=next(a for a in frame['actors'] if a['owner']==frame['turn']);i=data['names'].index(a['account'])
            if i in completed or a['ap']<3 or (not frame['at_goal'] and not frame['route']):
                time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));continue
            if frame['route']:
                net.command(i,encode_move_request(BattleMove(a['id'],tuple(map(tuple,frame['route'])))),expected=b'\x3d');continue
            x,y=frame['door'];assert abs(a['x']-x)==abs(a['y']-y)==1
            request=DoorRequest(a['id'],True,x,y)
            denied(net,1-i,encode_door_request(request))
            assert qa.state(data)['actors']==frame['actors']
            # Ensure a closed starting state, retaining only this test's AP delta.
            if next(s for dx,dy,s in frame['doors'] if (dx,dy)==(x,y)):
                net.command(i,encode_door_request(DoorRequest(a['id'],False,x,y)),expected=b'\x3f')
            before=qa.state(data);ap=next(v['ap'] for v in before['actors'] if v['id']==a['id'])
            for opened in (True,True,False):
                req=DoorRequest(a['id'],opened,x,y)
                rows=net.command(i,encode_door_request(req),expected=b'\x3f')
                assert encode_door_state(req) in rows
                current=qa.state(data)
                assert next(s for dx,dy,s in current['doors'] if (dx,dy)==(x,y))==opened
                expected=ap-(1 if opened else 2)
                assert next(v['ap'] for v in current['actors'] if v['id']==a['id'])==expected
            net.command(1-i)
            report['cases'].append(dict(actor=a['id'],position=[a['x'],a['y']],door=[x,y],
                wall_corner=True,open_close=True,idempotent_open=True,total_ap=2,other_owner_rejected=True,
                checkpoint_roundtrip=True))
            completed.add(i)
        assert len(completed)==2
        report.update(passed=True,match=initial['match'])
    finally:
        for i in tuple(net.peers):
            try:net.command(i,b'\x2a\1')
            except (OSError,EOFError,AssertionError):pass
        net.close();(qa.OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','state','cleanup'));a=p.parse_args()
    if a.mode=='state':print(json.dumps(qa.state(qa.load(),True)))
    elif a.mode=='run':run()
    else:getattr(qa,a.mode)()
