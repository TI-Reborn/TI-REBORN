"""Real x86 selector, BA02 parser/colour path, full lobby draw and numeric formatter.

Allocation, managed-string storage, UI sinks and collection enumeration are
isolated. No actual game process is started or driven. The concrete control
Enabled fields, original callbacks, roster scans, BA01 writers, decoded fields,
complete877158 renderer and actual4244B4 integer formatter execute natively.
"""
from __future__ import annotations
import argparse,hashlib,json,struct,sys
from pathlib import Path
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_legacy_lobbies_native import emulator,put,get,ret,restart,run,DATA,ACTORS,STACK,STOP,read_and_project
from tools.verify_legacy_server_status_native import read_string
from deploy import client_arena_lobby_search_status as patcher
from tio.protocol.arena import ArenaRoom,encode_room_list
from tio.protocol.wagers import WagerRoomRecord
FOLDER=ROOT/'reports/gameplay-completion/legacy-status-20261011/client-search-availability'
SOURCE=FOLDER.parent/'client-freshness/silver.dll'


def selector(raw,base,mode,after_setup=False):
 u=emulator(raw,base);delta=base-0x400000
 tabs=[DATA+0x2000,DATA+0x2400,DATA+0x2800]
 for global_va,pointer in zip((0xad0428,0xad0430,0xad042c),tabs):put(u,global_va+delta,pointer);u.mem_write(pointer+0x4a,b'\x01')
 put(u,0xac4a64+delta,DATA+0x2c00);u.mem_write(DATA+0x2c4a,b'\x01')
 u.mem_write(0xac4a84+delta,bytes((mode,)))
 def hook(uc,address,size,_):
  va=address-delta;a=uc.reg_read(UC_X86_REG_EAX);d=uc.reg_read(UC_X86_REG_EDX)
  if va==0x4092ac:uc.reg_write(UC_X86_REG_EAX,DATA+0x4000);ret(uc)
  elif va==0x40eca8:put(uc,a,d);ret(uc)
  elif va in (0x674708,0x40ec90):ret(uc)
  elif va==0x9406e3 and after_setup:uc.emu_stop()
 u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA+0x1000)
 try:run(u,0x944290,base)
 except Exception:
  print('Selector stopped',hex(u.reg_read(UC_X86_REG_EIP)-delta),'mode',mode,'sp',hex(u.reg_read(UC_X86_REG_ESP)),file=sys.stderr);raise
 initial=[u.mem_read(pointer+0x4a,1)[0] for pointer in tabs]
 if after_setup:
  u.mem_write(DATA+0x100d,b'\x04');u.reg_write(UC_X86_REG_ESI,DATA+0x1000);restart(u)
  u.emu_start(0x9406da+delta,STOP,count=1000)
  assert u.reg_read(UC_X86_REG_EIP)==0x9406e3+delta
  assert u.mem_read(0xac4a84+delta,1)==b'\x04'
 result=[u.mem_read(pointer+0x4a,1)[0] for pointer in tabs]
 expected=[0,int(mode==4),int(mode==4)] if patcher.sha(raw)!=patcher.BASE_SHA else [0,0,0]
 if after_setup:expected=[0,1,1] if patcher.sha(raw)!=patcher.BASE_SHA else [0,0,0]
 assert result==expected,(mode,result,expected)
 return dict(base=hex(base),mode=mode,after_completed_setup=after_setup,initial_enabled=initial,final_enabled=result,
             survival_disabled=result[0]==0,ok_enabled=u.mem_read(DATA+0x2c4a,1)[0])


def navigation(raw,base,mode):
 u=emulator(raw,base);delta=base-0x400000;captured=[]
 manager=DATA+0x1000;event=DATA+0x2000;control=DATA+0x2500;vtable=DATA+0x3000
 put(u,0xac622c+delta,manager);put(u,manager,control);put(u,control+0x280,0xffffffff)
 for va in (0xacf3d0,0xacf3d4,0xacf3d8):put(u,va+delta,event)
 for va in (0xacf3bc,0xacf3b8):put(u,va+delta,control)
 put(u,control,vtable);put(u,vtable,DATA+0x3100);u.mem_write(DATA+0x3100,b'\xc3')
 put(u,0xac489c+delta,0xffffffff);put(u,0xac5fa0+delta,manager)
 obj,handle,transport_vtable,flush=DATA+0x4000,DATA+0x5200,DATA+0x5300,DATA+0x5400
 put(u,handle,obj);put(u,obj,transport_vtable);put(u,transport_vtable,flush);put(u,0xac600c+delta,handle)
 def hook(uc,address,size,_):
  va=address-delta;a=uc.reg_read(UC_X86_REG_EAX);d=uc.reg_read(UC_X86_REG_EDX)
  if va in (0xa6a114,0xa6a2a4,0xa69ab0):captured.append(hex(va));ret(uc)
  elif va==0xa3fca8:uc.reg_write(UC_X86_REG_EAX,0xffffffff);ret(uc)
  elif va==0xa54980:assert a==event+0x2a0;uc.reg_write(UC_X86_REG_EIP,(0x8756f0 if mode==1 else 0x875714)+delta)
  elif va in (0x87b43c,0x87b4c0):uc.reg_write(UC_X86_REG_EAX,0);ret(uc)
  elif va in (0x87b170,0x8723e4,0x8605b8):ret(uc)
  elif va==0x6748b0:uc.reg_write(UC_X86_REG_EAX,handle);ret(uc)
  elif address in (flush,DATA+0x3100):ret(uc)
  elif va in (0xa089f0,0x85f954,0x85e488):raise AssertionError('Browsing invoked a gameplay request')
 u.hook_add(UC_HOOK_CODE,hook);run(u,0x9443d0 if mode==1 else 0x944434,base)
 packet=bytes(u.mem_read(obj+4,get(u,obj+0x1004)))
 assert packet==b'\xba\x01',packet.hex()
 assert get(u,0xac48a0+delta)==mode
 return dict(base=hex(base),mode=mode,original_callback_executed=True,original_mode_handler_executed=True,
             browse_request_hex=packet.hex(),gui_sinks=captured,create_search_join_invoked=False)


def insert_typed_row(u,base,row):
 """Execute original872f7c, including its real48-byte stack copy and branches."""
 delta=base-0x400000;target=DATA+0x4400;before=bytes(u.mem_read(row,0x30));calls=[]
 def hook(uc,address,size,_):
  va=address-delta;a=uc.reg_read(UC_X86_REG_EAX);d=uc.reg_read(UC_X86_REG_EDX)
  if va in (0x40cb10,0x40c9a4,0x87251c,0x8725d8,0x8731cc):ret(uc)
  elif va in (0x87b43c,0x87b4c0):uc.reg_write(UC_X86_REG_EAX,0);ret(uc)
  elif va==0x40ce98:assert a==0x30;uc.reg_write(UC_X86_REG_EAX,target);ret(uc)
  elif va==0x40cc38:uc.mem_write(a,bytes(uc.mem_read(d,0x30)));calls.append('managed48_copy');ret(uc)
  elif va==0x87a980:assert d==target;calls.append('original_collection_insert');ret(uc)
 token=u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,row);run(u,0x872f7c,base);u.hook_del(token)
 assert bytes(u.mem_read(target,0x30))==before and calls==['managed48_copy','original_collection_insert']
 return target


def selected_count(raw,base,roster):
 u=emulator(raw,base);delta=base-0x400000;slots=DATA+0x1000;put(u,0xac618c+delta,slots)
 before=[]
 for index,(level,selected) in enumerate(roster):
  actor=ACTORS+index*0x7000;put(u,slots+4*index,actor);put(u,actor+0x5ffc,level);u.mem_write(actor+0x5ff1,bytes((selected,)))
  before.append((actor,bytes(u.mem_read(actor,0x6100))))
 run(u,0x87969c,base);count=u.reg_read(UC_X86_REG_EAX)
 assert count==sum(bool(selected) for level,selected in roster)
 for actor,value in before:assert bytes(u.mem_read(actor,0x6100))==value
 return dict(base=hex(base),roster=roster,actual_original_selected_count=count,selection_not_changed=True)


def lobby(raw,base,mode,members,capacity,roster,*,typed=False,stake=0,status=0):
 delta=base-0x400000
 if typed:
  record=WagerRoomRecord(73,b'qs3110ad96a',2,mode,capacity,members,status,1,2,1,0,stake)
  u,row,projection=read_and_project(raw,base,record)
  row=insert_typed_row(u,base,row)
 else:
  u=emulator(raw,base);row=DATA+0x4000;projection={}
 control,parent,listing,filtered,flags,slots=(DATA+i for i in (0x1000,0x1800,0x2000,0x2500,0x2800,0x3000))
 for va,pointer in ((0xacf398 if not typed else 0xacf394,listing),(0xac5900,flags),(0xac618c,slots),
                    (0xac5d58,DATA+0x2a00),(0xac5fa0,DATA+0x2b00),(0xac55a4,DATA+0x2c00)):
  put(u,va+delta,pointer)
 put(u,flags,0x3c);put(u,listing+8,0);put(u,DATA+0x2c00,mode)
 put(u,0xac5b7c+delta,parent);put(u,control+0x4c,parent);put(u,control+0x38,1000);put(u,control+0x3c,120)
 put(u,control+0x280,0xffffffff);put(u,control+0x284,18);put(u,control+0x2a8,filtered)
 u.mem_write(control+0x2ac,b'\x01')
 before=[]
 for index,(level,selected) in enumerate(roster):
  actor=ACTORS+index*0x7000;put(u,slots+index*4,actor);u.mem_write(actor+0x41,b'\x01')
  put(u,actor+0x5ffc,level);u.mem_write(actor+0x5ff1,bytes((selected,)));before.append((actor,bytes(u.mem_read(actor,0x6100))))
 heap=DATA+0x6000;iterator_calls=0;phase='parser';draws=[];numbers=[];trace=[]
 def allocate(uc,text=None,length=None):
  nonlocal heap
  if text is not None:length=len(text)
  target=heap+12;heap+=0x100;assert heap<DATA+0xf000
  uc.mem_write(target-12,struct.pack('<HHii',1200,2,1,length))
  uc.mem_write(target,(text.encode('utf-16-le') if text is not None else bytes(length*2))+b'\0\0');return target
 def hook(uc,address,size,_):
  nonlocal iterator_calls
  va=address-delta;a,d,c=(uc.reg_read(r) for r in (UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX))
  if va>=0x400000:trace.append(hex(va));del trace[:-18]
  if va==0x4244b4:numbers.append(a);return
  if va==0x40ce98:uc.reg_write(UC_X86_REG_EAX,row);ret(uc)
  elif va==0x605f1c:
   cursor=get(uc,a);value=bytes(uc.mem_read(cursor,255)).split(b'\0',1)[0];put(uc,a,cursor+len(value)+1);put(uc,d,allocate(uc,value.decode('cp1251')));ret(uc)
  elif va==0x85fb8e and phase=='parser':uc.emu_stop()
  elif va==0x68a094:ret(uc)
  elif va in (0x40b47c,0x40b4c4,0x40b4f0):put(uc,a,d);ret(uc)
  elif va==0x40c0e4:put(uc,a,allocate(uc,length=d));ret(uc)
  elif va==0x40bf68:uc.reg_write(UC_X86_REG_EAX,a);ret(uc)
  elif va==0x40c1bc:put(uc,a,allocate(uc,read_string(uc,d)+read_string(uc,c)));ret(uc)
  elif va==0x40c244:
   sp=uc.reg_read(UC_X86_REG_ESP);text=''.join(read_string(uc,get(uc,sp+4+i*4)) for i in reversed(range(d)))
   put(uc,a,allocate(uc,text));ret(uc,d*4)
  elif va==0x6675e0:put(uc,d,allocate(uc,read_string(uc,a)));ret(uc)
  elif va in (0xa4211c,0xa42140,0x87b43c,0x87b1fc):uc.reg_write(UC_X86_REG_EAX,0);ret(uc)
  elif va==0x87b450:uc.reg_write(UC_X86_REG_EAX,row);ret(uc)
  elif va==0x87b4c0:uc.reg_write(UC_X86_REG_EAX,int(iterator_calls==0));iterator_calls+=1;ret(uc)
  elif va in (0x876c44,0x424f2c,0x4f26f4):uc.reg_write(UC_X86_REG_EAX,0);ret(uc)
  elif va==0x4f29a8:
   sp=uc.reg_read(UC_X86_REG_ESP);draws.append(dict(text=read_string(uc,d),colour=hex(get(uc,sp+4))));ret(uc,8)
  elif va==0x4f2ba8:uc.reg_write(UC_X86_REG_EAX,len(read_string(uc,d))*8);ret(uc)
  elif va in (0xa3dcc0,0xa3e0c0):ret(uc)
  elif va==0x4f2888:ret(uc,16)
  elif va==0x4f2950:ret(uc,20)
  elif va==0x4f2978:ret(uc,16)
  elif va==0x4f27fc:ret(uc,12)
  elif va==0x40c06c:ret(uc)
  elif va in (0x40b09c,0x40b0fc,0x40c9a4,0x4f2eb4,0x4f2ee8):ret(uc)
 u.hook_add(UC_HOOK_CODE,hook)
 if not typed:
  name=b'qs3110ad96a \xb7 '+(b'\xe7\xe0\xed\xff\xf2\xee' if members>=capacity else b'\xf1\xe2\xee\xe1\xee\xe4\xed\xee')+f' {members}/{capacity}'.encode()
  packet=encode_room_list((ArenaRoom(73,0,mode,status,0,members,capacity,name,1,1,3,1,0),))
  u.mem_write(DATA,packet[4:]);put(u,DATA+0x800,DATA)
  restart(u);put(u,STACK+0x8004,DATA+0x900);u.reg_write(UC_X86_REG_EAX,DATA+0x800)
  u.emu_start(0x85fa88+delta,STOP,count=10000)
  assert u.reg_read(UC_X86_REG_EIP)==0x85fb8e+delta
  assert get(u,DATA+0x800)-DATA==len(packet)-4
 assert (u.mem_read(row+0x1d,1)[0],u.mem_read(row+0x1c,1)[0])==(members,capacity)
 phase='colour';iterator_calls=0;run(u,0x872bf4 if typed else 0x872a4c,base)
 eligible=any(1<=level<=3 for level,selected in roster)
 colour=get(u,row+0x24)
 if mode in (1,4) and stake==0:assert colour==(0xff6060ff if not eligible else patcher.GRAY if members>=capacity or status else patcher.GREEN),(mode,roster,hex(colour))
 phase='draw';iterator_calls=0;before_row=bytes(u.mem_read(row,0x30));u.reg_write(UC_X86_REG_EAX,control)
 try:run(u,0x877158,base,count=100000)
 except Exception:
  print('Full lobby renderer stopped at',hex(u.reg_read(UC_X86_REG_EIP)-delta),trace,file=sys.stderr);raise
 assert bytes(u.mem_read(row,0x30))==before_row
 expected=f'{members}/{capacity}';draw=next(d for d in draws if d['text']==expected)
 assert draw['colour']==hex(colour),(draw,hex(colour))
 for actor,value in before:assert bytes(u.mem_read(actor,0x6100))==value
 return dict(base=hex(base),wire='C82C' if typed else 'BA02',mode=mode,members=members,capacity=capacity,
             roster=roster,eligible=eligible,status=status,colour_hex=f'{colour:08x}',displayed_players=expected,
             actual_integer_formatter_inputs=numbers,full_renderer_executed=True,row_unchanged_by_draw=True,owned_fighters_unchanged=True,draws=draws)


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=SOURCE);p.add_argument('--candidate',type=Path,default=FOLDER/'silver.dll');p.add_argument('--out',type=Path,default=FOLDER/'native-navigation-proof.json');a=p.parse_args()
 source=a.source.read_bytes();raw=a.candidate.read_bytes();review=patcher.review(source,raw)
 selectors=[selector(raw,base,mode) for base in (0x400000,0x10400000) for mode in range(9)]
 selectors.extend(selector(raw,base,0,True) for base in (0x400000,0x10400000))
 regressions=[selector(source,base,4) for base in (0x400000,0x10400000)]
 navigations=[navigation(raw,base,mode) for base in (0x400000,0x10400000) for mode in (1,4)]
 rosters=[[],[(4,1)],[(1,1)],[(1,1),(4,2)],[(4,1),(1,0)]]
 cases=[lobby(raw,base,mode,members,capacity,roster,typed=typed)
        for base in (0x400000,0x10400000) for typed in (False,True) for mode,capacity in ((1,2),(4,4))
        for members in (1,capacity) for roster in rosters]
 cases.extend(lobby(raw,base,mode,1,capacity,roster,typed=typed,status=2)
        for base in (0x400000,0x10400000) for typed in (False,True) for mode,capacity in ((1,2),(4,4))
        for roster in rosters)
 counts=[selected_count(raw,base,roster) for base in (0x400000,0x10400000) for roster in rosters]
 unchanged=[]
 for base in (0x400000,0x10400000):
  for typed,mode,stake in ((False,0,0),(False,8,0),(True,0,0),(True,8,0),(True,1,99),(True,4,99)):
   original=lobby(source,base,mode,1,2,[(1,1)],typed=typed,stake=stake)
   candidate=lobby(raw,base,mode,1,2,[(1,1)],typed=typed,stake=stake)
   assert original['colour_hex']==candidate['colour_hex']
   assert original['draws']==candidate['draws']
   unchanged.append(dict(base=hex(base),wire='C82C' if typed else 'BA02',mode=mode,stake=stake,colour_and_draws_original=True))
 report=dict(passed=True,method=__doc__,source_sha256=patcher.sha(source),candidate_sha256=patcher.sha(raw),review=review,
             selector_cases=selectors,original_disabled_regression=regressions,navigation_cases=navigations,lobby_case_count=len(cases),lobby_cases=cases,
             selected_roster_count_cases=counts,other_modes_and_stakes_unchanged=unchanged,real_graphical_clients=0)
 a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print('PASS: original selectors/callbacks and '+str(len(cases))+' native BA02/C82C full-row render cases')
if __name__=='__main__':main()
