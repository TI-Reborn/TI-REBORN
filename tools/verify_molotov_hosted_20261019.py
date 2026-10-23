"""Two excluded real accounts on authoritative public TLS, no bots."""
import argparse,json,select,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import tio
from tools import verify_area_fire_hosted_20261018 as qa
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
from tio.protocol.battle_move import BattleMove,encode_move_request
from tio.protocol.health import encode_health
qa.OUT=ROOT/'reports/molotov-fix-20261019';qa.PRIVATE=ROOT/'.secrets/molotov-fix-20261019.json'
qa.PREPARE=qa.PREPARE.replace('314+index,1','319,4').replace('weapons=[314,315]','weapons=[319,319]')
qa.STATE=qa.STATE.replace('not 1<=combat_distance','not 4<=combat_distance')
qa.STATE=qa.STATE.replace('(a.action_points-w.attack_ap)','(a.action_points-max(w.attack_ap,10))')
qa.STATE=qa.STATE.replace("  if request.get('plan')", """  from tio.battle_hazards import fire_areas,fire_cells
  result['fires']=[dict(center=a['center'],expiry=a['expiry'],cells=sorted(fire_cells(c,a))) for a in fire_areas(c).values()]
  result['remaining']=max(0,turn[2]-__import__('time').monotonic()) if turn else 0
  result['generations']=f._ability_turns
  if request.get('plan')""")
original=qa.Network.command
def command(self,i,packet=b'\x70',expected=None):
    peer=self.peers[i]
    while peer.pending or peer.sock.pending() or select.select([peer.sock],[],[],.08)[0]:peer.receive()
    return original(self,i,packet,expected)
qa.Network.command=command

def leave(net,i):
    peer=net.peers[i];peer.send(b'\x2a\1');deadline=time.monotonic()+2
    while time.monotonic()<deadline:
        if peer.pending or peer.sock.pending() or select.select([peer.sock],[],[],.15)[0]:peer.receive()

def start(net,data):
    heal(data)
    for i in (0,1):net.connect(i)
    for i in (0,1):net.command(i,b'\xba\3\0\1')
    for i in (0,1):
        if not any(p[0]==0x41 for p in net.received[i]):net.peers[i].until(b'\x41',max_packets=4096)
    f=qa.state(data);data['matches'].append(f['match']);qa.save(data)
    for i in (0,1):net.command(i,b'\x36')

def heal(data):
    qa.remote('''import sqlite3,json
from dataclasses import replace
from tio.rating_visibility import QA_LOGIN,excluded
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for name in request:
  assert QA_LOGIN.fullmatch(name) and excluded(db,name)
  assert not db.execute('select 1 from battle_checkpoint_members where account=?',(name,)).fetchone()
  human,raw=db.execute('select human,pet_packet from owned_pets where account=? and pet_id=1',(name,)).fetchone()
  pet=decode_pet_info(raw,human_equipment=bool(human))
  db.execute('update owned_pets set pet_packet=? where account=? and pet_id=1',(encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4a07':1000,'0x8c4ab1':1000})),name))
print(json.dumps(dict(owned_fixtures_only=True,healed=2)))
''',data['names'])

def throw(net,data,source=None):
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        f=qa.state(data,True);assert not f['finished']
        a=next(v for v in f['actors'] if v['owner']==f['turn']);i=data['names'].index(a['account'])
        if (source is not None and i!=source) or a['ap']<10:
            time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));continue
        if f.get('route'):
            net.command(i,encode_move_request(BattleMove(a['id'],tuple(map(tuple,f['route'])))),expected=b'\x3d');continue
        if not f.get('aim'):time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));continue
        rows=net.command(i,encode_attack_request(AttackRequest(a['id'],*f['aim'])),expected=b'\x4b')
        result=decode_attack_result(next(p for p in rows if p[0]==0x4b));assert result.weapon_id==319
        after=qa.state(data);enemy=next(v for v in after['actors'] if v['id']!=a['id'])
        assert any([enemy['x'],enemy['y']] in fire['cells'] for fire in after['fires']),after
        return i,f,after,result
    raise AssertionError('No legal Molotov throw')

def run():
    data=qa.load();net=qa.Network(data);report=dict(passed=False,humans=2,bots=0,graphical_clients=False)
    try:
        start(net,data);i,before,after,attack=throw(net,data)
        source=next(a for a in after['actors'] if a['account']==data['names'][i]);victim=next(a for a in after['actors'] if a['id']!=source['id'])
        initial=next(a for a in before['actors'] if a['id']==source['id'])
        assert source['ap']==initial['ap']-7
        assert source['items'][0]['count']==initial['items'][0]['count']-1
        for j in (0,1):net.command(j)
        cuts={j:len(net.received[j]) for j in (0,1)}
        time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));time.sleep(.4)
        for j in (0,1):net.command(j)
        tick=qa.state(data);target=next(a for a in tick['actors'] if a['id']==victim['id'])
        assert target['hp']==victim['hp']-10,(after,tick)
        for j in (0,1):
            rows=net.received[j][cuts[j]:]
            assert not any(p[0]==0x4b for p in rows),'Periodic tick replays weapon animation'
        assert encode_health(target['id'],target['hp']) in net.received[1-i][cuts[1-i]:]
        current_source=next(a for a in tick['actors'] if a['id']==source['id'])
        assert current_source['items']==source['items']
        net.peers[1-i].sock.close();net.connect(1-i);net.command(1-i,b'\x36')
        recovered=qa.state(data);assert recovered['actors']==tick['actors'],'Reconnect repeated damage'
        report.update(passed=True,match=after['match'],initial_throw_count=1,periodic_raw_damage=10,periodic_attack_packets=0,
                      source_items_unchanged=True,reconnect_no_duplicate_damage=True,absolute_hp_delivered=True,before=before,after_throw=after,after_tick=tick)
    finally:
        for j in tuple(net.peers):
            try:leave(net,j)
            except Exception:pass
        net.close();(qa.OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(passed=report['passed'],periodic_damage=10,rethrow_packets=0,reconnect_no_duplicate=True)))

def hold():
    data=qa.load();net=qa.Network(data)
    try:
        start(net,data);i,before,after,attack=throw(net,data,source=0)
        net.peers[0].sock.close()
        for connection in net.case.clients[:2]:connection.close()
        (qa.OUT/'gui-ready.json').write_text(json.dumps(after,indent=2))
        print(json.dumps(dict(ready_for_native_reconnect=True,state=after)),flush=True)
        for line in sys.stdin:
            if line.strip()=='stop':break
            if line.strip()=='turn':net.command(1,b'\x3a'+bytes(4))
            print(json.dumps(qa.state(data)),flush=True)
    finally:
        try:leave(net,1)
        except Exception:pass
        net.close()

def finish():
    data=qa.load()
    for i in (0,1):
        net=qa.Network(data)
        try:net.connect(i);leave(net,i)
        finally:net.close()
    print(json.dumps(qa.state(data)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','hold','state','cleanup','finish'));a=p.parse_args()
    if a.mode=='state':print(json.dumps(qa.state(qa.load(),True)))
    elif a.mode in ('provision','cleanup'):getattr(qa,a.mode)()
    else:globals()[a.mode]()
