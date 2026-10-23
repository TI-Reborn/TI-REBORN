"""Owned, ranking-excluded pair; authoritative Groza ground fire over public TLS."""
import argparse,json,secrets,struct,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
saved=list(sys.path)
from tools.verify_game_operations_hosted import CREATE,CLEANUP,remote
sys.path[:]=saved
from tools.clan_icons_hosted_20261018 import Clients
sys.path[:]=saved
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
from tio.protocol.item_list import decode_item_list
from tio.protocol.battle_move import BattleMove,encode_move_request
from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
OUT=ROOT/'reports/groza-20261019'
PRIVATE=ROOT/'.secrets/groza-20261019.json'

PREPARE=r'''
import json,sqlite3
from pathlib import Path
from dataclasses import replace
from tio.rating_visibility import QA_LOGIN,excluded
from tio.owned_pets import OwnedPetStore
from tio.squad import SquadStore
from tio.locations import LocationStore,center
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list
from tio.level_progression import FLOORS
path='/var/lib/tio-server/reservation.sqlite3'
pet=decode_pet_info(bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex']),human_equipment=True)
for index,name in enumerate(request):
 assert QA_LOGIN.fullmatch(name)
 with sqlite3.connect(path) as db:
  assert excluded(db,name)
  assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account=?',(name,)).fetchone()
  assert not db.execute('SELECT 1 FROM owned_pets WHERE account=?',(name,)).fetchone()
 raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':10,'0x8c4b05':FLOORS[9],'0x8c4a07':1000,'0x8c4ab1':1000}))
 def item(i,t,n,e,s):return ItemRecord(i,t,bytes(2),n,e,s,(300,300,300),bytes(4),None,bytes(3))
 inv=encode_item_list(1,(item(91001,339,1,1,16),item(91002,340,4,0,0),item(91003,36,20,0,0)))
 OwnedPetStore(path).ensure(name,raw,inv,human=True)
 SquadStore(path).assign(name,1,1)
 locations=LocationStore(path)
 with sqlite3.connect(path) as db:LocationStore._save(db,name,2,*center(2))
print(json.dumps(dict(only_owned_fixtures=True,ranking_excluded=True,level=10,health=1000,weapons=[339,339],town=2)))
'''

STATE=r'''
import json,sqlite3
from tio.rating_visibility import QA_LOGIN
from tio.battle_snapshot import loads
from tio.protocol.item_list import decode_item_list
names=request['names'];assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 row=db.execute('SELECT c.match_id,c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m USING(match_id) WHERE m.account=?',(names[0],)).fetchone()
 if not row:print(json.dumps(None))
 else:
  b=loads(row[1])[0]['battle'];f=b['field'];c=f.combat
  assert {r[0] for r in b['reward_roster'].values()}==set(names) and not b['bots']
  turn=b['arena']._turns.get(b['room'].room_id)
  result=dict(match=row[0],finished=b['finished'],bots=0,turn=turn[0] if turn else None,
   actors=[dict(id=a.actor_id,owner=a.owner_id,account=b['reward_roster'][a.owner_id][0],x=a.x,y=a.y,ap=a.action_points,hp=a.health,
    items=[dict(template=i.template_id,count=i.count,wear=i.unknown_words[0]) for i in decode_item_list(c.inventories[a.actor_id])[1]]) for a in f._actors.values()])
  if request.get('plan') and not b['finished'] and turn:
   from collections import deque
   from dataclasses import replace
   from tio.combat_distance import combat_distance
   from tio.combat_rolls import area_victims
   from tio.visibility import field_sight,visible_actors
   a=next(a for a in f._actors.values() if a.owner_id==turn[0] and a.health)
   enemy=next(a2 for a2 in f._actors.values() if not f.allied(a2.owner_id,a.owner_id) and a2.health)
   weapon=next(i.template_id for i in decode_item_list(c.inventories[a.actor_id])[1] if i.equipped and i.client_slot==16)
   w=c.catalog.weapons[340];occupied={(v.x,v.y) for v in f._actors.values() if v.health}
   def aim_at(actor):
    # Aim at an empty cell beside the enemy, proving this is ground fire.
    for dx,dy in ((0,1),(0,-1),(1,0),(-1,0)):
     p=enemy.x+dx,enemy.y+dy
     if p in occupied or p in f.blocked or not f.inside(*p) or not 4<=combat_distance((actor.x,actor.y),p)<=8:continue
     if (p[0]-enemy.x)**2+(p[1]-enemy.y)**2<=1 and field_sight(f,p,(enemy.x,enemy.y)) and field_sight(f,(actor.x,actor.y),(enemy.x,enemy.y)):return p
   aim=aim_at(a);result['aim']=aim
   result['enemy_visible']=enemy.actor_id in visible_actors(f,a.owner_id)
   if not aim:
    start=a.x,a.y;queue=deque([start]);prev={start:None};goal=None
    while queue:
     p=queue.popleft()
     if aim_at(replace(a,x=p[0],y=p[1])):goal=p;break
     for nxt in ((p[0]-1,p[1]),(p[0]+1,p[1]),(p[0],p[1]-1),(p[0],p[1]+1)):
      if nxt in prev or nxt in f.blocked or nxt in occupied or not f.inside(*nxt):continue
      prev[nxt]=p;queue.append(nxt)
    assert goal,'No legal route for owned fixture'
    route=[]
    while goal!=start:route.append(goal);goal=prev[goal]
    result['route']=list(reversed(route))[:max(0,min(5,(a.action_points-w.attack_ap)//f.step_cost))]
  print(json.dumps(result))
'''

def load():return json.loads(PRIVATE.read_text(encoding='utf-8'))
def save(data):PRIVATE.write_text(json.dumps(data),encoding='utf-8')
def state(data,plan=False):return remote(STATE,dict(names=data['names'],plan=plan))

def provision():
 assert not PRIVATE.exists()
 prefix='qt'+secrets.token_hex(4)
 data=dict(names=[prefix+'a',prefix+'b'],passwords=[secrets.token_urlsafe(24) for _ in range(2)],matches=[])
 data['provision']=remote(CREATE,list(zip(data['names'],data['passwords'])));save(data)
 result=remote(PREPARE,data['names']);(OUT/'fixture-provisioning.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

class Network(Clients):
 def __init__(self,data):super().__init__(data);self.received={0:[],1:[]}
 def connect(self,i):
  p=super().connect(i);receive=p.receive
  def record():
   row=receive();self.received[i].append(row);return row
  p.receive=record;return p
 def command(self,i,packet=b'\x70',expected=None):
  peer=self.peers[i]
  if packet!=b'\x70':peer.send(packet)
  peer.send(b'\x70');rows=[];fence=False
  for _ in range(4096):
   row=peer.receive();rows.append(row)
   if row.startswith(b'\xf0\x8a\x01\0\0'):raise AssertionError('Native request rejected: '+row[13:-2].decode('utf-16-le',errors='replace'))
   if row==b'\x9e':fence=True
   if fence and (expected is None or any(r.startswith(expected) for r in rows)):return rows
  raise AssertionError('Missing native response')

def run():
 data=load();net=Network(data);report=dict(passed=False,graphical_clients=False,humans=2,bots=0,shots=[])
 try:
  for i in (0,1):net.connect(i)
  check=remote("import subprocess,json; n=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines());assert n==2;print(json.dumps(n))",None)
  report['isolated_connected_pair']=check==2
  for i in (0,1):net.command(i,b'\xba\3\0\1')
  for i in (0,1):
   if not any(p[0]==0x41 for p in net.received[i]):net.peers[i].until(b'\x41',max_packets=4096)
  b=state(data);data['matches'].append(b['match']);save(data)
  for i in (0,1):net.command(i,b'\x36')
  fired=set();deadline=time.monotonic()+180
  while time.monotonic()<deadline and len(fired)<2:
   frame=state(data,True);assert frame and not frame['finished']
   a=next(a for a in frame['actors'] if a['owner']==frame['turn']);i=data['names'].index(a['account'])
   if i in fired or a['ap']<6:time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));continue
   if frame.get('route'):
    net.command(i,encode_move_request(BattleMove(a['id'],tuple(map(tuple,frame['route'])))),expected=b'\x3d');continue
   if not frame.get('aim'):time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));continue
   before=frame;rows=net.command(i,encode_ability_cast(AbilityCast(27,a['id'],0,*frame['aim'])),expected=b'\x4b')
   attack=decode_attack_result(next(r for r in rows if r[0]==0x4b));after=state(data)
   own=next(v for v in after['actors'] if v['id']==a['id']);enemy=next(v for v in after['actors'] if v['id']!=a['id'])
   prior=next(v for v in before['actors'] if v['id']==enemy['id'])
   assert attack.target==tuple(frame['aim']) and (attack.weapon_id,attack.skill_id)==(340,27)
   assert (enemy['x'],enemy['y'])!=attack.target and enemy['hp']<prior['hp']
   assert own['ap']==a['ap']-6
   assert next(v['count'] for v in own['items'] if v['template']==340)==next(v['count'] for v in a['items'] if v['template']==340)-1
   from tio.protocol.health import encode_health
   for _ in range(3):net.command(1-i)
   observed=[decode_attack_result(r) for r in net.received[1-i] if r[0]==0x4b and decode_attack_result(r).actor_id==a['id']]
   absolute=encode_health(enemy['id'],enemy['hp']) in net.received[1-i]
   animated=any(h.actor_id==enemy['id'] and h.left_hp==enemy['hp'] for v in observed for h in v.hits)
   report['shots'].append(dict(weapon=attack.weapon_id,actor=a['id'],aim=attack.target,enemy=enemy['id'],damage=prior['hp']-enemy['hp'],enemy_visible=frame['enemy_visible'],ap_spent=6,ammo_spent=1,opponent_hp_verified=absolute or animated,animation_visible_to_opponent=bool(observed)))
   assert absolute or animated,report['shots'][-1]
   fired.add(i)
  assert len(fired)==2
  net.command(0,b'\x2a\1');net.command(1,b'\x2a\1')
  for i in (0,1):net.command(i)
  report.update(passed=True,match=b['match'])
 finally:
  for i in tuple(net.peers):
   try:net.command(i,b'\x2a\1')
   except (OSError,EOFError,AssertionError):pass
  net.close();(OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2))
 print(json.dumps(report))

def cleanup():
 data=load();assert not state(data),'Leave own battle normally before cleanup'
 old="condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)"
 new="\n  if 'match_id' in columns and request.get('matches'):\n   parts.append(quote('match_id')+' IN ('+','.join('?' for _ in request['matches'])+')');args+=request['matches']\n  "+old
 code=CLEANUP.replace(old,new);assert code!=CLEANUP
 result=remote(code,dict(names=data['names'],matches=data['matches'],protected_before=data['provision']['protected_before'],require_unchanged_players=False))
 (OUT/'fixture-cleanup.json').write_text(json.dumps(result,indent=2));PRIVATE.unlink();print(json.dumps(result))

def hold():
 data=load();net=Network(data)
 try:
  for i in (0,1):net.connect(i)
  for i in (0,1):net.command(i,b'\xba\3\0\1')
  for i in (0,1):
   if not any(p[0]==0x41 for p in net.received[i]):net.peers[i].until(b'\x41',max_packets=4096)
  b=state(data);data['matches'].append(b['match']);save(data)
  for i in (0,1):net.command(i,b'\x36')
  net.peers[0].sock.close() if hasattr(net.peers[0],'sock') else None
  for connection in net.case.clients[:2]:connection.close()
  print(json.dumps(dict(ready_for_native_reconnect=True,state=state(data))),flush=True)
  for line in sys.stdin:
   if line.strip()=='stop':break
   if line.strip()=='turn':net.command(1,b'\x3a'+bytes(4))
   print(json.dumps(state(data,True)),flush=True)
 finally:
  try:net.command(1,b'\x2a\1')
  except Exception:pass
  net.close()

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','state','cleanup','hold'));a=p.parse_args()
 if a.mode=='state':print(json.dumps(state(load(),True)))
 else:globals()[a.mode]()
