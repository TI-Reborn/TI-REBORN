"""Three reserved real accounts over public TLS: allied party versus real opponent."""
import argparse,json,secrets,select,struct,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import tio
from tools import verify_area_fire_hosted_20261018 as qa
qa.OUT=ROOT/'reports/trueskill-invite-20261019';qa.PRIVATE=ROOT/'.secrets/trueskill-invite-20261019.json'
qa.PREPARE=qa.PREPARE.replace("'0x8c4aef':10","'0x8c4aef':4").replace('FLOORS[9]','FLOORS[3]').replace('level=10','level=4')
qa.STATE='''import json,sqlite3
from tio.rating_visibility import QA_LOGIN,excluded
from tio.battle_snapshot import loads
names=request['names'];assert len(names)==3 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 row=db.execute('SELECT c.match_id,c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m USING(match_id) WHERE m.account=?',(names[0],)).fetchone()
 if not row:print(json.dumps(None))
 else:
  b=loads(row[1])[0]['battle'];f=b['field']
  assert {r[0] for r in b['reward_roster'].values()}==set(names)
  print(json.dumps(dict(match=row[0],finished=b['finished'],faulted=b.get('faulted',False),mode=b['room'].request.mode,
   actors=[dict(id=a.actor_id,owner=a.owner_id,side=f.teams[a.owner_id],hp=a.health,bot=a.owner_id in b['bots']) for a in f._actors.values()],
   humans={str(o):r[0] for o,r in b['reward_roster'].items()},bots=sorted(b['bots']),ranking_excluded=all(excluded(db,n) for n in names))))
'''
base_command=qa.Network.command
def command(self,i,packet=b'\x70',expected=None):
    p=self.peers[i]
    while p.pending or p.sock.pending() or select.select([p.sock],[],[],.05)[0]:p.receive()
    return base_command(self,i,packet,expected)
qa.Network.command=command
base_init=qa.Network.__init__
def initialise(self,data):base_init(self,data);self.received[2]=[]
qa.Network.__init__=initialise

def provision():
    assert not qa.PRIVATE.exists();prefix='qt'+secrets.token_hex(4)
    data=dict(names=[prefix+c for c in 'abc'],passwords=[secrets.token_urlsafe(24) for _ in range(3)],matches=[])
    data['provision']=qa.remote(qa.CREATE,list(zip(data['names'],data['passwords'])));qa.save(data)
    result=qa.remote(qa.PREPARE,data['names']);(qa.OUT/'fixture-provisioning.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

def join():return b'\xc6\x21\0\0'+struct.pack('<III',1,1,0)+b'\0'
def leave(net,i,packet=b'\x2a\1'):
    p=net.peers[i];p.send(packet);deadline=time.monotonic()+1.5
    while time.monotonic()<deadline:
        if p.pending or p.sock.pending() or select.select([p.sock],[],[],.1)[0]:p.receive()

def run():
    data=qa.load();net=qa.Network(data);report=dict(passed=False,public_tls=True,real_accounts=3,graphical_clients=False)
    try:
        for i in (0,1,2):net.connect(i)
        request=b'\xc6\x32'+data['names'][1].encode()+b'\0\0\0'
        net.command(0,request,expected=b'\xc6\x36');net.command(1,expected=b'\xc6\x35')
        net.command(1,b'\xc6\x37\0');assert qa.state(data) is None;report['decline_does_not_start_battle']=True
        time.sleep(2.1);net.command(0,request);net.command(1,expected=b'\xc6\x35');net.command(1,b'\xc6\x37\1',expected=b'\xc6\x36')
        for i in (0,1):net.command(i,join(),expected=b'\xc6\x36')
        net.command(0,join());assert qa.state(data) is None;report['party_waits_for_other_real_side']=True
        net.command(1,b'\xc6\x23',expected=b'\xc6\x06');assert qa.state(data) is None;report['whole_party_cancelled']=True
        for i in (0,1):net.command(i,join(),expected=b'\xc6\x36')
        net.command(0,join());assert qa.state(data) is None
        net.command(2,join(),expected=b'\xc6\4')
        for i in (0,1,2):
            if not any(p[0]==0x41 for p in net.received[i]):net.command(i,expected=b'\x41')
        battle=qa.state(data);assert battle and battle['ranking_excluded'] and not battle['faulted']
        data['matches'].append(battle['match']);qa.save(data)
        owner={account:int(o) for o,account in battle['humans'].items()};side={a['owner']:a['side'] for a in battle['actors']}
        assert side[owner[data['names'][0]]]==side[owner[data['names'][1]]]!=side[owner[data['names'][2]]]
        assert len(battle['actors'])==8 and len(battle['bots'])==5
        for i in (0,1,2):net.command(i,b'\x36')
        leave(net,2)
        for i in (0,1):leave(net,i)
        assert qa.state(data) is None
        report.update(passed=True,accepted_invitation=True,party_remained_allied=True,real_opponent_required=True,bots=5,total_fighters=8,match=battle['match'],battle=battle)
    finally:
        for i in tuple(net.peers):
            try:leave(net,i);leave(net,i,b'\xc6\x33')
            except Exception:pass
        net.close();(qa.OUT/'hosted-three-account.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='battle'}))

def cleanup():
    data=qa.load();assert qa.state(data) is None
    old="condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)"
    new="\n  if 'match_id' in columns and request.get('matches'):\n   parts.append(quote('match_id')+' IN ('+','.join('?' for _ in request['matches'])+')');args+=request['matches']\n  "+old
    code=qa.CLEANUP.replace('len(names)==2','len(names)==3').replace(old,new)
    result=qa.remote(code,dict(names=data['names'],matches=data['matches'],protected_before=data['provision']['protected_before'],require_unchanged_players=False))
    (qa.OUT/'fixture-cleanup.json').write_text(json.dumps(result,indent=2));qa.PRIVATE.unlink();print(json.dumps(result))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','cleanup','state'));mode=p.parse_args().mode
    if mode=='state':print(json.dumps(qa.state(qa.load())))
    else:globals()[mode]()
