"""Send one normal outbound QA command through the own native ORANGE route.

No server reply or client render state is injected. The hosted service validates
ownership, turn, movement, cost, damage and visibility as for any real client.
"""
import argparse,json,sys,time
from pathlib import Path
import frida
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.flame_fire_gui_20261021 import OUT,GAME,flame
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.protocol.battle_move import BattleMove,encode_move_request

SCRIPT=r'''
const expected=OPTIONS;
if(Process.mainModule.path.replace(/\\/g,'/').toLowerCase()!==expected.path.toLowerCase())throw Error('Only own QA process permitted');
const silver=Process.getModuleByName('silver.dll').base,at=n=>silver.add(n-0x400000);
const u32=n=>[n&255,(n>>>8)&255,(n>>>16)&255,(n>>>24)&255];
const payload=Memory.alloc(expected.packet.length);payload.writeByteArray(expected.packet);
const code=Memory.alloc(4096);code.writeByteArray([0x9c,0x60,0xb8,...u32(payload.toUInt32()),0xba,...u32(expected.packet.length),0xb9,...u32(at(0x6060f0).toUInt32()),0xff,0xd1,0x61,0x9d,0xc3]);Memory.protect(code,4096,'r-x');
const call=new NativeFunction(code,'void',[],'stdcall');let sent=false;
Interceptor.attach(at(0x814608),{onEnter(){if(sent)return;sent=true;call();send({outbound_sent:true});}});
'''
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('own','end','fire'));p.add_argument('--delay',type=float,default=0);p.add_argument('--axis',choices=('x','y','route'),default='y');p.add_argument('--natural',action='store_true');p.add_argument('--blender',action='store_true');a=p.parse_args()
 if a.natural:
  OUT=ROOT/'reports/flame-natural-20261021';flame.qa.OUT=OUT;flame.qa.PRIVATE=ROOT/'.secrets/flame-natural-20261021.json'
 if a.blender:
  OUT=ROOT/'reports/flame-blender-20261021';flame.qa.OUT=OUT;flame.qa.PRIVATE=ROOT/'.secrets/flame-blender-20261021.json'
 data=flame.qa.load();battle=flame.qa.state(data,True);assert battle and not battle['finished']
 actor=next(v for v in battle['actors'] if v['account']==data['names'][0]);assert actor['owner']==battle['turn'],'Own native turn required'
 if a.mode=='end':packet=b'\x3a'+bytes(4)
 elif battle.get('route') and a.mode=='own':packet=encode_move_request(BattleMove(actor['id'],tuple(map(tuple,battle['route']))))
 elif battle.get('aim') and actor['ap']>=9:packet=encode_attack_request(AttackRequest(actor['id'],*battle['aim']))
 elif a.mode=='fire':
  x,y=actor['x'],actor['y']
  if a.axis=='x':x=x+3 if x<32 else x-3
  elif a.axis=='route' and battle.get('route'):x,y=battle['route'][0]
  else:y=y+3 if y<32 else y-3
  packet=encode_attack_request(AttackRequest(actor['id'],x,y))
 else:packet=b'\x3a'+bytes(4)
 status=json.loads((OUT/'native-trace.json').read_text());pid=status['native']['pid']
 session=frida.get_local_device().attach(pid);events=[]
 try:
  if a.delay:time.sleep(a.delay)
  script=session.create_script(SCRIPT.replace('OPTIONS',json.dumps(dict(path=str(GAME/'ti.exe').replace('\\','/'),packet=list(packet)))))
  script.on('message',lambda m,d:events.append(m));script.load()
  deadline=time.monotonic()+8
  while time.monotonic()<deadline and not events:time.sleep(.03)
  assert any(m.get('payload',{}).get('outbound_sent') for m in events),events
  print(json.dumps(dict(sent=True,opcode=packet[0],actor=actor['id'],aim=battle.get('aim'),route=battle.get('route'))))
 finally:session.detach()
