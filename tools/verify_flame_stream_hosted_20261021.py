"""Two excluded accounts on current verified public TLS; no graphical claims."""
import argparse,json,select,socket,ssl,struct,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import tio
from tools import verify_area_fire_hosted_20261018 as qa
from tools.verify_launcher_required_hosted_20261020 import identity
from tio.protocol.flame_stream import decode_flame_stream
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
from tio.protocol.battle_move import BattleMove,encode_move_request

qa.OUT=ROOT/'reports/flamethrower-implementation-20261021'
qa.PRIVATE=ROOT/'.secrets/flamethrower-implementation-20261021.json'
qa.PREPARE=qa.PREPARE.replace('314+index,1','324,1').replace('weapons=[314,315]','weapons=[324,324]')
start=qa.STATE.index('   def aim_at(actor):');end=qa.STATE.index('   aim=aim_at(a);',start)
qa.STATE=qa.STATE[:start]+'''   def aim_at(actor):
    vx,vy=enemy.x-actor.x,enemy.y-actor.y
    if not 1<=combat_distance((actor.x,actor.y),(enemy.x,enemy.y))<=5 or not field_sight(f,(actor.x,actor.y),(enemy.x,enemy.y)):return None
    for py in range(max(0,actor.y-5),min(f.height,actor.y+6)):
     for px in range(max(0,actor.x-5),min(f.width,actor.x+6)):
      if (px,py) in occupied or not 1<=combat_distance((actor.x,actor.y),(px,py))<=5:continue
      dx,dy=px-actor.x,py-actor.y;dot=vx*dx+vy*dy;cross=vx*dy-vy*dx
      if dot>0 and cross*cross*25<=dot*dot:return px,py
''' +qa.STATE[end:]


class Network(qa.Network):
 def __init__(self,data):
  super().__init__(data);proof=identity();context=ssl.create_default_context()
  def connect(kind,*,preface=None,**kwargs):
   raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
   channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');self.case.clients.append(channel)
   port=int.from_bytes(preface[6:8],'big') if preface else 37001;flags=preface[5] if preface else 0
   channel.sendall(struct.pack('!4sBBH',b'TIOT',2,flags,port)+proof);return channel
  self.tls.connect=connect
 def command(self,i,packet=b'\x70',expected=None):
  peer=self.peers[i]
  while peer.pending or peer.sock.pending() or select.select([peer.sock],[],[],.03)[0]:peer.receive()
  return super().command(i,packet,expected)


def run():
 data=qa.load();net=Network(data)
 report=dict(passed=False,public_tls=True,real_accounts=2,bots=0,graphical_clients=False,shots=[])
 try:
  for i in (0,1):net.connect(i)
  for i in (0,1):net.command(i,b'\xba\3\0\1')
  for i in (0,1):
   if not any(p[0]==0x41 for p in net.received[i]):net.peers[i].until(b'\x41',max_packets=4096)
  battle=qa.state(data);data['matches'].append(battle['match']);qa.save(data)
  for i in (0,1):net.command(i,b'\x36')
  fired=set();deadline=time.monotonic()+240
  while time.monotonic()<deadline and len(fired)<2:
   before=qa.state(data,True);assert before and not before['finished']
   a=next(v for v in before['actors'] if v['owner']==before['turn']);i=data['names'].index(a['account'])
   if i in fired or a['ap']<10:time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));continue
   if before.get('route'):
    net.command(i,encode_move_request(BattleMove(a['id'],tuple(map(tuple,before['route'])))),b'\x3d');continue
   if not before.get('aim'):time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));continue
   marks={j:len(net.received[j]) for j in (0,1)}
   rows=net.command(i,encode_attack_request(AttackRequest(a['id'],*before['aim'])),b'\x4b')
   for _ in range(2):net.command(1-i)
   attack=decode_attack_result(next(p for p in rows if p[0]==0x4b));assert attack.weapon_id==324
   after=qa.state(data);own=next(v for v in after['actors'] if v['id']==a['id'])
   enemy=next(v for v in after['actors'] if v['id']!=a['id']);old_enemy=next(v for v in before['actors'] if v['id']==enemy['id'])
   assert tuple(before['aim'])!=(enemy['x'],enemy['y'])
   assert own['ap']==a['ap']-9
   old_fuel=next(v['wear'] for v in a['items'] if v['template']==324)
   fuel=next(v['wear'] for v in own['items'] if v['template']==324);assert fuel==old_fuel-9
   counts=[]
   for j in (i,1-i):
    packets=net.received[j][marks[j]:];events=[p for p in packets if p[:2]==b'\xf7\2']
    assert len(events)==1,(j,len(events));actor,token,points=decode_flame_stream(events[0]);assert actor==a['id']
    visible_attack=next(p for p in packets if p[0]==0x4b and decode_attack_result(p).actor_id==a['id'])
    assert packets.index(events[0])<packets.index(visible_attack)
    counts.append(len(points))
   if enemy['hp']<old_enemy['hp']:fired.add(i)
   report['shots'].append(dict(actor=a['id'],aim=attack.target,empty_aim=True,damage=old_enemy['hp']-enemy['hp'],
     ap_spent=9,fuel_spent=9,visual_points_both_accounts=counts,events_precede_native_animation=True))
  assert len(fired)==2
  saved=qa.state(data);net.peers[0].sock.close();mark=len(net.received[0]);net.connect(0);net.command(0)
  assert not any(p[:2]==b'\xf7\2' for p in net.received[0][mark:]),'Reconnect replayed transient flame'
  restored=qa.state(data)
  assert [(v['id'],v['hp'],v['items']) for v in restored['actors']]==[(v['id'],v['hp'],v['items']) for v in saved['actors']]
  report.update(passed=True,match=battle['match'],reconnect_no_replay=True,persisted_hp_and_fuel=True)
 finally:
  for i in tuple(net.peers):
   try:net.command(i,b'\x2a\1')
   except (OSError,EOFError,AssertionError):pass
  net.close();(qa.OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2))
 print(json.dumps(report))


if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','state','cleanup'));mode=p.parse_args().mode
 if mode=='state':print(json.dumps(qa.state(qa.load(),True)))
 elif mode in ('provision','cleanup'):getattr(qa,mode)()
 else:run()
