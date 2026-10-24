"""Execute launcher-generated x86 adapter at two image/allocation addresses.

GPU, audio and host clock are isolated. Reader validation, copying, dedup,
native animation trigger, finite frame draws, scene clear and ABI execute.
"""
import hashlib,json,struct,sys
from pathlib import Path
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE,UC_HOOK_MEM_INVALID
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from deploy import client_flame_stream as fx
from deploy import client_throwable_effects as terrain
from deploy import client_rain_weather as rain
from tio.protocol.flame_stream import encode_flame_stream
from tio.protocol.battle_item_visuals import encode_item_visuals


def run(silver,allocation):
 source=(ROOT/'work/groza-20261019/gui/game-a/silver.dll').read_bytes()
 assert hashlib.sha256(source).hexdigest()==fx.SHA
 pe=pefile.PE(data=source);pe.relocate_image(silver)
 u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(0,4096)
 u.mem_map(silver,(pe.OPTIONAL_HEADER.SizeOfImage+4095)&~4095);u.mem_write(silver,pe.get_memory_mapped_image())
 u.mem_map(allocation,fx.SIZE);u.mem_write(allocation,fx.build(allocation,silver))
 data,stack,stop=0x3000000,0x3100000,0x3100100
 u.mem_map(data,0x10000);u.mem_map(stack,0x10000)
 put=lambda a,v:u.mem_write(a,struct.pack('<I',v&0xffffffff))
 get=lambda a:struct.unpack('<I',u.mem_read(a,4))[0]
 put(allocation+fx.SILVER,silver)
 put(allocation+fx.TEXTURE,1) # Resource decoding isolated in this ABI fixture.
 put(silver+0xac64a0-0x400000,data);u.mem_write(data,b'\1')
 for i,rva in enumerate((0xac61b0-0x400000,0xac6068-0x400000)):
  put(silver+rva,data+4+i*4);put(data+4+i*4,50+i*50)
 clock=data+0x100;put(silver+0xb79b10-0x400000,clock)
 state=dict(tick=10000,draws=[],stock_reads=0,stock_draws=0,native_draws=0,animation_entries=0,area_fallbacks=0)
 def ret(extra=0,result=None):
  sp=u.reg_read(UC_X86_REG_ESP);target=get(sp);u.reg_write(UC_X86_REG_ESP,sp+4+extra);u.reg_write(UC_X86_REG_EIP,target)
  if result is not None:u.reg_write(UC_X86_REG_EAX,result)
 def hook(uc,at,size,_):
  if at==clock:ret(result=state['tick'])
  elif at==silver+terrain.DRAW+5-0x400000:state['stock_draws']+=1;ret()
  elif at==silver+0x814608-0x400000:state['native_draws']+=1;ret()
  elif at==silver+terrain.LOAD-0x400000:ret()
  elif at==silver+terrain.READER-0x400000:state['stock_reads']+=1;ret(result=77)
  elif at==silver+0xa896f0-0x400000:ret()
  elif at==silver+0x4f2910-0x400000:
   sp=uc.reg_read(UC_X86_REG_ESP);flags,tint,frame,h,w=[get(sp+4+i*4) for i in range(5)]
   assert flags==0 and frame<64 and 4<=w<=32 and h==w
   assert uc.reg_read(UC_X86_REG_EAX)==allocation+fx.TEXTURE
   state['draws'].append(dict(frame=frame,tint=tint,x=uc.reg_read(UC_X86_REG_EDX),y=uc.reg_read(UC_X86_REG_ECX),width=w))
   ret(20)
  elif at==silver+0x95f968-0x400000:
   # Original callback prolog has executed (EBP is frame, ECX=58).
   assert uc.reg_read(UC_X86_REG_ECX)==58
   state['animation_entries']+=1;uc.emu_stop()
  elif at==silver+0xa7a94e-0x400000:state['area_fallbacks']+=1;uc.emu_stop()
 u.hook_add(UC_HOOK_CODE,hook)
 def invalid(uc,access,address,size,value,_):raise AssertionError(('unmapped',hex(address),hex(uc.reg_read(UC_X86_REG_EIP))))
 u.hook_add(UC_HOOK_MEM_INVALID,invalid)
 def execute(offset,eax=0,edx=0,ecx=0,complete=True):
  sp=stack+0x8000;put(sp,stop);u.reg_write(UC_X86_REG_ESP,sp)
  for reg,value in ((UC_X86_REG_EAX,eax),(UC_X86_REG_EDX,edx),(UC_X86_REG_ECX,ecx)):u.reg_write(reg,value)
  u.emu_start(allocation+offset,stop,count=100000)
  if complete:
   assert u.reg_read(UC_X86_REG_EIP)==stop,hex(u.reg_read(UC_X86_REG_EIP))
   assert u.reg_read(UC_X86_REG_ESP)==sp+4,'Stack imbalance'
 def read(packet):
  u.mem_write(data+0x1000,packet[1:]);execute(fx.READER,packet[0],data+0x1000,len(packet))
 def active():return sum(get(allocation+fx.ROWS+i*512)==2 for i in range(16))
 def pending():return sum(get(allocation+fx.ROWS+i*512)==1 for i in range(16))
 def trigger(actor=17,weapon=324):
  obj=data+0x2000;put(obj,actor);u.mem_write(obj+0x2e,struct.pack('<H',weapon));execute(fx.ATTACK,obj,complete=False)
 p=encode_flame_stream(17,42,((120,160,12,4),(152,160,16,12),(184,160,20,24)))
 read(p);assert pending()==1,(hex(get(allocation+fx.SILVER)),get(allocation+fx.NEXT),bytes(u.mem_read(allocation+fx.ROWS,40)).hex(),bytes(u.mem_read(data+0x1000,30)).hex())
 execute(fx.DRAW);assert not state['draws'],'Pending stream cannot draw before native animation'
 trigger(18);assert active()==0
 trigger(17);assert active()==1
 # Execute the actual published rain wrapper, shared terrain hook, then the
 # flame draw. The old adapter patched an unused trampoline and failed here.
 site=silver+terrain.DRAW-0x400000
 u.mem_write(site,b'\xe9'+struct.pack('<i',allocation+fx.DRAW-site-5))
 n=state['stock_draws'];native=state['native_draws']
 execute(silver+rain.DRAW-0x400000-allocation)
 assert state['stock_draws']==n+1 and state['native_draws']==native+1
 state['tick']+=100;execute(fx.DRAW);assert len(state['draws'])==2
 state['tick']+=200;execute(fx.DRAW);assert len(state['draws'])==8
 frames={v['frame'] for v in state['draws']}
 eddies=[]
 for _ in range(6):
  state['tick']+=16;n=len(state['draws']);execute(fx.DRAW);current=state['draws'][n:];assert len(current)==6
  assert all(v['tint']&0xffffff==0xffffff for v in current)
  body=current[::2];current=current[1::2]
  eddies.append((current[0]['x'],current[0]['y']))
  for row,(x,y,envelope,_) in zip(body+current,((120,160,12,4),(152,160,16,12),(184,160,20,24))*2):
   # Stubbed projection is identity plus camera. Motion and animated sprite
   # together must fit the server's envelope, including its near-wall minimum.
   assert row['x']>=x+50-envelope/2 and row['x']+row['width']<=x+50+envelope/2
   assert row['y']>=y+100-16-envelope/2 and row['y']+row['width']<=y+100-16+envelope/2
 assert len(set(eddies))>1,'Particles must actually move between frames'
 state['tick']+=800;execute(fx.DRAW);assert any(v['tint']>>24<176 for v in state['draws'])
 assert len({v['frame'] for v in state['draws']})>len(frames)
 read(p);assert pending()==0 and active()==1,'Duplicate must not restart event'
 state['tick']+=300;n=len(state['draws']);execute(fx.DRAW);assert len(state['draws'])==n and active()==0
 read(p);assert pending()==0,'Expired duplicate must not restart event'
 for packet in (p[:-1],p+b'\0',p[:10]+b'\xff'+p[11:],p[:11]+b'\xff\xff'+p[13:]):
  read(packet);assert pending()==0 and active()==0
 read(encode_item_visuals(((2,3,4),)));assert state['stock_reads']==1
 read(b'\x70');assert state['stock_reads']==2
 for token in range(50,70):read(encode_flame_stream(17,token,((120,160,12,4),)))
 assert pending()==16
 trigger();assert active()==1 and pending()==15
 state['tick']+=6000;execute(fx.DRAW);assert pending()==active()==0
 read(encode_flame_stream(17,99,((120,160,12,4),)));assert pending()==1
 u.mem_write(data,b'\0');execute(fx.DRAW);assert not pending() and get(allocation+fx.NEXT)==0
 obj=data+0x3000;put(obj+8,324);execute(fx.AREA,obj);assert u.reg_read(UC_X86_REG_EAX)&255==1
 put(obj+8,302);execute(fx.AREA,obj,complete=False);assert state['area_fallbacks']==1
 u.mem_write(data,b'\1')
 read(encode_flame_stream(17,190,((120,160,5,1),(152,160,21,1))))
 trigger();state['tick']+=100;n=len(state['draws']);execute(fx.DRAW)
 for row,envelope,x in zip(state['draws'][n:],(5,5,21,21),(120,120,152,152)):
  assert row['width']%2==0
  assert x+50-envelope/2<=row['x'] and row['x']+row['width']<=x+50+envelope/2
 # All world directions must select their own bank, including negative
 # deltas; otherwise the horizontal texture still points the wrong way.
 for bank,(dx,dy) in enumerate(((1,0),(1,1),(0,1),(-1,1),(-1,0),(-1,-1),(0,-1),(1,-1))):
  read(encode_flame_stream(17,200+bank,((500,500,28,1),(500+dx*160,500+dy*160,28,24))))
  index=(get(allocation+fx.NEXT)-1)&15
  assert get(allocation+fx.ROWS+index*512+0x1f0)==bank*8,bank
 return dict(passed=True,silver=hex(silver),allocation=hex(allocation),draws=len(state['draws']),frames=sorted({v['frame'] for v in state['draws']}),finite_lifetime=True,
             duplicate_rejected=True,malformed_rejected=True,scene_clear=True,original_terrain_dispatch=True,published_rain_chain=True,animated_eddies=True,motion_inside_server_envelope=True,directional_banks=8,area_targeting=True,stack_balanced=True,graphical_client=False)


def render_pipeline():
 from tools.verify_molotov_native_20261019 import Fixture
 from tools.verify_ui_hd_icons_native import DATA as D,put,get
 from tools.build_throwable_runtime_fix_20261019 import plan as resource_fix
 from PIL import Image
 root=ROOT/'work/groza-20261019/gui/game-a'
 source=bytearray((root/'silver.dll').read_bytes());pe=pefile.PE(data=source)
 for row in resource_fix()['patches']:
  at=pe.get_offset_from_rva(row['rva']);before=bytes.fromhex(row['before']);after=bytes.fromhex(row['after'])
  assert source[at:at+len(before)]==before;source[at:at+len(after)]=after
 f=Fixture(bytes(source),(root/'ti.exe').read_bytes(),0x10000000,0x400000)
 put(f.u,f.va(0xacc424),f.tva(0x71bd8c))
 for name,_,_,_ in terrain.RESOURCES:f.asset_dimensions['base\\'+name]=Image.open(root/'base'/name.replace('\\','/')).size
 f.asset_dimensions['base\\'+fx.ASSET]=Image.open(ROOT/'assets/flame-jet-v1/tio-flame-jet.png').size
 allocation=0x21000000;f.u.mem_map(allocation,fx.SIZE);f.u.mem_write(allocation,fx.build(allocation,f.base));put(f.u,allocation+fx.SILVER,f.base)
 put(f.u,f.va(0xac64a0),D+0x8000);put(f.u,D+0x8000,1)
 for off,va in ((4,0xac61b0),(8,0xac6068)):
  put(f.u,f.va(va),D+0x8000+off);put(f.u,D+0x8000+off,0)
 clock=D+0x8100;put(f.u,f.va(0xb79b10),clock)
 row=allocation+fx.ROWS;put(f.u,row,2);put(f.u,row+4,10000);put(f.u,row+16,1)
 f.u.mem_write(row+20,struct.pack('<HHBB',120,160,24,6))
 def hook(u,at,size,_):
  if at==f.va(terrain.DRAW+5) or at==f.va(0x814608):f.ret()
  elif at==clock:u.reg_write(UC_X86_REG_EAX,10350);f.ret()
  elif at==f.va(0xa896f0):f.ret()
 f.u.hook_add(UC_HOOK_CODE,hook)
 f.run(allocation+fx.DRAW-f.base+0x400000)
 assert len(f.quads)==2 and len(f.loads)==5
 assert all(v[4]==0x70ffffff for v in f.quads[0]['vertices'])
 b=f.quads[0]['vertices'];assert min(v[0] for v in b)>=108 and max(v[0] for v in b)<=132
 assert min(v[1] for v in b)>=132 and max(v[1] for v in b)<=156
 quad=f.quads[1];vertices=quad['vertices']
 assert all(v[4]==0xe0ffffff for v in vertices)
 xs=[v[0] for v in vertices];ys=[v[1] for v in vertices]
 assert abs(max(xs)-min(xs)-20)<.001 and abs(max(ys)-min(ys)-20)<.001
 assert min(xs)>=120-12 and max(xs)<=120+12
 assert min(ys)>=160-16-12 and max(ys)<=160-16+12
 return dict(passed=True,actual_unicode_loader=True,actual_uv_quad_pipeline=True,
             native_loader_entries=sorted(f.loader_executed),native_renderer_entries=sorted(f.executed),
             quad=quad,decoding_and_gpu_submission_isolated=True)


if __name__=='__main__':
 value=dict(passed=True,cases=[run(0x400000,0x20000000),run(0x1400000,0x21000000)],render_pipeline=render_pipeline(),gpu_submission_isolated=True)
 out=ROOT/'reports/flamethrower-implementation-20261021';out.mkdir(exist_ok=True,parents=True)
 (out/'native-client.json').write_text(json.dumps(value,indent=2));print(json.dumps(value))
