"""Two excluded hosted accounts; one native client and one protocol peer.

Native rendering is observed, never substituted. Gameplay stays on the hosted
authoritative service. The peer can move/end its turn/fire using normal packets.
"""
import argparse,hashlib,json,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import verify_flame_stream_hosted_20261021 as flame
from tools import hosted_graphical_qa_bridge as auth
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.protocol.battle_move import BattleMove,encode_move_request
OUT=ROOT/'reports/flamethrower-fire-20261021-v2';OUT.mkdir(exist_ok=True)
flame.qa.OUT=OUT;flame.qa.PRIVATE=ROOT/'.secrets/flamethrower-fire-20261021-v2.json'
GAME=ROOT/'work/groza-20261019/gui/game-a'
LAUNCHER=ROOT/'work/flamethrower-fire-20261021-v2/qa-launcher/TIO Launcher.exe'

TRACE=r'''
const silver=Process.getModuleByName('silver.dll').base;
const at=n=>silver.add(n-0x400000);
const target=p=>p.add(5).add(p.add(1).readS32());
const allocation=target(at(0x95f960)).sub(0xc00);
const rows=allocation.add(0x8000);
const state={read:[],attacks:[],draws:0,lastDraws:[],allocation:String(allocation)};
function slots(){const out=[];for(let i=0;i<16;i++){const p=rows.add(i*512);if(p.readU32())out.push({slot:i,state:p.readU32(),tick:p.add(4).readU32(),actor:p.add(8).readU32(),token:p.add(12).readU32(),points:p.add(16).readU32()});}return out;}
Interceptor.attach(allocation,{onEnter(){this.flame=(this.context.eax.toUInt32()&255)===247&&this.context.edx.readU8()===2;if(this.flame)this.event={length:this.context.ecx.toUInt32(),actor:this.context.edx.add(1).readU32(),points:this.context.edx.add(9).readU8()};},onLeave(){if(this.flame){state.read.push({...this.event,slots:slots()});if(state.read.length>50)state.read.shift();}}});
Interceptor.attach(allocation.add(0xc00),{onEnter(){const p=this.context.eax;this.event={actor:p.readU32(),weapon:p.add(0x2e).readU16(),slots:slots()};},onLeave(){state.attacks.push({...this.event,after:slots()});if(state.attacks.length>50)state.attacks.shift();}});
Interceptor.attach(at(0x4f2910),{onEnter(){if(!this.context.eax.equals(silver.add(0x87a080)))return;state.draws++;const sp=this.context.esp;state.lastDraws.push({x:this.context.edx.toInt32(),y:this.context.ecx.toInt32(),flags:sp.add(4).readU32(),tint:sp.add(8).readU32(),frame:sp.add(12).readU32(),size:sp.add(20).readU32()});if(state.lastDraws.length>100)state.lastDraws.shift();}});
const keep=[];let queued=null;
Interceptor.attach(at(0x814608),{onEnter(){if(queued){const call=queued;queued=null;call();}}});
rpc.exports={status(){return {...state,slots:slots(),battle:at(0xac64a0).readPointer().readU8()};},submit(raw){
 if(![0x3a,0x3c,0x49].includes(raw[0])||raw.length>512)throw Error('Only bounded owned battle requests');
 if(raw[0]!==0x3a && new DataView(Uint8Array.from(raw).buffer).getUint32(1,true)!==0x40000001)throw Error('Only own QA actor');
 const u32=n=>[n&255,(n>>>8)&255,(n>>>16)&255,(n>>>24)&255];
 const payload=Memory.alloc(raw.length);payload.writeByteArray(raw);
 const code=Memory.alloc(4096);code.writeByteArray([0x9c,0x60,0xb8,...u32(payload.toUInt32()),0xba,...u32(raw.length),0xb9,...u32(at(0x6060f0).toUInt32()),0xff,0xd1,0x61,0x9d,0xc3]);Memory.protect(code,4096,'r-x');
 keep.push(payload,code);queued=new NativeFunction(code,'void',[],'stdcall');return true;
}};
'''

def launch(auto=False):
 data=flame.qa.load();net=flame.Network(data);bridge=None;trace=None
 try:
  for i in (0,1):net.connect(i)
  if flame.qa.state(data):
   for i in (0,1):net.command(i,b'\x2a\1')
   for i in (0,1):net.command(i)
   assert not flame.qa.state(data),'Previous own result must be left before a new QA match'
  for i in (0,1):net.command(i,b'\xba\3\0\1')
  for i in (0,1):
   if not any(p[0]==0x41 for p in net.received[i]):net.peers[i].until(b'\x41',max_packets=4096)
  match=flame.qa.state(data);assert match and match['bots']==0
  data['matches'].append(match['match']);flame.qa.save(data)
  net.command(1,b'\x36');net.peers[0].sock.close()
  rows={r['path']:r for r in json.loads(urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=30).read())['files']}
  auth.HASHES={n:rows[n]['sha256'] for n in ('ti.exe','orange.dll','silver.dll')}
  bridge=auth.HostedGraphicalQaBridge(GAME,dict(login=data['names'][0],password=data['passwords'][0],fresh_qa=True),auto_select=True,launcher=LAUNCHER,launcher_sha256=hashlib.sha256(LAUNCHER.read_bytes()).hexdigest())
  trace=bridge.session.create_script(TRACE);trace.load();bridge.start_connect()
  print(json.dumps(dict(started=True,pid=bridge.pid,match=match['match'],bots=0)),flush=True)
  if auto:
   deadline=time.monotonic()+45
   while time.monotonic()<deadline:
    net.command(1)
    native=bridge.status();before=flame.qa.state(data,bool(globals().get('AUTO_ROUTE')))
    if trace.exports_sync.status()['battle']==1 and native.get('worldStartSent') and before and not before['finished']:
     actor=next(v for v in before['actors'] if v['account']==data['names'][0])
     if before['turn']!=actor['owner']:
      net.command(1,b'\x3a'+bytes(4));time.sleep(1.1);continue
     if actor['ap']<9:trace.exports_sync.submit(list(b'\x3a'+bytes(4)));time.sleep(1.1);continue
     x,y=actor['x'],actor['y'];target=(x,y+3 if y<32 else y-3)
     if globals().get('AUTO_ROUTE') and before.get('route'):target=tuple(before['route'][0])
     trace.exports_sync.submit(list(encode_attack_request(AttackRequest(actor['id'],*target))))
     for i in range(12):
      time.sleep(.15);result=dict(native=native,effects=trace.exports_sync.status(),battle=flame.qa.state(data))
      (OUT/f'auto-trace-{i:02}.json').write_text(json.dumps(result,indent=2))
     print(json.dumps(dict(auto_fired=True,effects=result['effects'])),flush=True);break
    time.sleep(.2)
  for line in sys.stdin:
   action=line.strip()
   if action=='stop':break
   if action=='advance':
    deadline=time.monotonic()+210;shots=0
    while time.monotonic()<deadline and shots<2:
     before=flame.qa.state(data,True)
     if not before or before['finished']:break
     actor=next(v for v in before['actors'] if v['owner']==before['turn']);i=data['names'].index(actor['account'])
     if before.get('route'):packet=encode_move_request(BattleMove(actor['id'],tuple(map(tuple,before['route']))))
     elif before.get('aim') and actor['ap']>=9:packet=encode_attack_request(AttackRequest(actor['id'],*before['aim']));shots+=1
     else:packet=b'\x3a'+bytes(4)
     try:
      if i==0:trace.exports_sync.submit(list(packet))
      else:net.command(1,packet)
      print(json.dumps(dict(action=packet[0],account=i,aim=before.get('aim'),route=before.get('route'),shots=shots)),flush=True)
     except Exception as e:print(json.dumps(dict(retry=type(e).__name__)),flush=True)
     time.sleep(1.5)
     result=dict(effects=trace.exports_sync.status(),battle=flame.qa.state(data));(OUT/'advance-trace.json').write_text(json.dumps(result,indent=2))
    print('advance completed',flush=True);continue
   if action=='status':
    result=dict(native=bridge.status(),effects=trace.exports_sync.status(),battle=flame.qa.state(data,True));(OUT/'native-trace.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
   elif action=='peer':
    before=flame.qa.state(data,True);actor=next(v for v in before['actors'] if v['account']==data['names'][1])
    if actor['owner']!=before['turn']:print('Native client turn',flush=True);continue
    if before.get('route'):net.command(1,encode_move_request(BattleMove(actor['id'],tuple(map(tuple,before['route'])))))
    elif before.get('aim') and actor['ap']>=9:net.command(1,encode_attack_request(AttackRequest(actor['id'],*before['aim'])))
    else:net.command(1,b'\x3a'+bytes(4))
    print(json.dumps(dict(peer_action=True,route=before.get('route'),aim=before.get('aim'))),flush=True)
   elif action=='end_peer':
    before=flame.qa.state(data);actor=next(v for v in before['actors'] if v['account']==data['names'][1])
    if actor['owner']==before['turn']:net.command(1,b'\x3a'+bytes(4));print('peer ended turn',flush=True)
    else:print('Native client turn',flush=True)
   else:net.command(1);print('peer ping',flush=True)
 finally:
  if trace:
   try:(OUT/'native-trace-final.json').write_text(json.dumps(trace.exports_sync.status(),indent=2))
   except Exception:pass
  if bridge:bridge.release(cleanup=True)
  try:
   net.connect(0);net.command(0,b'\x2a\1')
  except Exception:pass
  try:net.command(1,b'\x2a\1')
  except Exception:pass
  net.close()

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','launch','cleanup'));p.add_argument('--auto',action='store_true');a=p.parse_args()
 if a.mode=='launch':launch(a.auto)
 elif a.mode=='provision':flame.qa.provision()
 else:flame.qa.cleanup()
