"""Original wire25 merge and wire27 removal, executed at two real PE bases.

The actual25 numeric reader, getters, entire25 slot matching consumer and
entire27 removal consumer execute. Allocation/string storage, nested soldier
conversion and UI/event sinks are isolated. No native GUI process is driven.
"""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_legacy_lobbies_native import emulator,put,get,ret,run,DATA,STACK
from deploy.client_server_list_status import sha
from tio.protocol.battle_members import BattleMemberRecord,encode_battle_members
FOLDER=ROOT/'reports/gameplay-completion/legacy-status-20261011/member-leave-native'
SOURCE=FOLDER.parent/'client-availability-navigation/silver.dll'
A=1;D=268435463


def fixture(raw,base):
 u=emulator(raw,base);delta=base-0x400000
 slots,settings,marker=(DATA+i for i in (0x9000,0xb000,0xb100))
 for va,pointer in ((0xac62a4,slots),(0xac6008,settings),(0xac585c,marker),(0xac5834,marker+0x100)):
  put(u,va+delta,pointer)
 for index,identity in enumerate((A,D)):
  u.mem_write(slots+index*0x1c0,b'\1');put(u,slots+index*0x1c0+4,identity)
 return u,delta,slots


def state(u,slots):
 return [dict(slot=i,active=u.mem_read(slots+i*0x1c0,1)[0],identity=get(u,slots+i*0x1c0+4)) for i in range(8)]


def consume25(raw,base,flag,incoming):
 u,delta,slots=fixture(raw,base);root=DATA+0x2000;records=DATA+0x3000;flags=DATA+0x5000;strings=DATA+0x6000
 packet=encode_battle_members(1,flag,tuple(BattleMemberRecord(identity,b'qs3110ad96a' if identity==A else b'qs3110ad96d',0,bytes((1,1,0,0,0,1))) for identity in incoming))
 u.mem_write(DATA,packet[1:]);put(u,0xacd0e8+delta,DATA);phase='reader';selected=[]
 def hook(uc,address,size,_):
  va=address-delta;a,d,c=(uc.reg_read(r) for r in (UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX))
  if va==0x64ea6c:put(uc,a+4,records);put(uc,a+8,d);put(uc,a+12,flags);ret(uc)
  elif va==0x6297e0:
   cursor=get(uc,0xacd0e8+delta);value=bytes(uc.mem_read(cursor,256)).split(b'\0',1)[0]
   put(uc,0xacd0e8+delta,cursor+len(value)+1);put(uc,d,strings);uc.mem_write(strings,bytes((len(value),))+value);ret(uc)
  elif va==0x40c06c:
   n=uc.mem_read(d,1)[0];uc.mem_write(a,bytes(uc.mem_read(d,n+1)));ret(uc)
  elif va in (0x40b09c,0x40c8cc,0x40c9a4,0xa0ac58):ret(uc)
  elif va==0xa09b78:
   parent=get(uc,uc.reg_read(UC_X86_REG_ESP)+4);identity=get(uc,parent-0x138)
   selected.append((a,identity));uc.mem_write(slots+a*0x1c0,b'\1');put(uc,slots+a*0x1c0+4,identity);ret(uc)
  elif va==0x66754c:uc.reg_write(UC_X86_REG_EAX,0);ret(uc)
  elif va==0x7d0be8:raise AssertionError('Unexpected city transition with gate0')
 u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,root);run(u,0x64e6b4,base)
 assert get(u,0xacd0e8+delta)-DATA==len(packet)-1
 u.reg_write(UC_X86_REG_EAX,root);run(u,0xa0a29c,base)
 active=[row['identity'] for row in state(u,slots) if row['active']]
 assert active==[A,D],(flag,incoming,active)
 return dict(base=hex(base),packet_hex=packet.hex(),flag=flag,incoming=incoming,final_slots=state(u,slots),
             stale_member_retained=True,selected_updates=selected,actual_numeric_reader_and_slot_consumer=True)


def consume27(raw,base,target):
 u,delta,slots=fixture(raw,base);u.mem_write(DATA,target.to_bytes(4,'little'));before=state(u,slots);events=[]
 def hook(uc,address,size,_):
  va=address-delta
  if va in (0xa01bf4,0xa0ac58,0x40b0fc,0x40c9f4,0x435664):ret(uc)
  elif va==0xa0a424:
   # Internal application-event queue sink, after the actual slot clear.
   events.append(uc.reg_read(UC_X86_REG_EAX));ret(uc)
  elif va==0x66754c:uc.reg_write(UC_X86_REG_EAX,1);ret(uc)
 u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA);run(u,0xa0a44c,base)
 after=state(u,slots);active=[row['identity'] for row in after if row['active']]
 assert active==([A] if target==D else [A,D]),(target,after)
 return dict(base=hex(base),packet_hex=(b'\x27'+target.to_bytes(4,'little')).hex(),target=target,initial_slots=before,
             final_slots=after,actual_original_removal_consumer=True,remaining_member_preserved=True,removed_slot_cleared=target==D,
             city_gate=1,internal_removal_event_ids=events)


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=SOURCE);p.add_argument('--out',type=Path,default=FOLDER/'native-member-leave-proof.json');a=p.parse_args()
 raw=a.source.read_bytes();assert sha(raw)=='afaa457c06ba6223476bc6e53eeff9947e9291acbce19700bb10ed5c3b29bdad'
 merges=[consume25(raw,base,flag,incoming) for base in (0x400000,0x10400000) for flag in (0,1) for incoming in ((A,),())]
 removals=[consume27(raw,base,target) for base in (0x400000,0x10400000) for target in (D,99)]
 report=dict(passed=True,method=__doc__,native_sha256=sha(raw),merge_cases=merges,removal_cases=removals,
             conclusion='25flag0 and flag1 merge; absent members remain active. Send original27/u32 departed public member identity to remaining room viewers; keep survivor25 as update.',
             no_native_patch=True,no_gui_gameplay_auth_calls=True)
 a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print('PASS: 8 original25 merge and4 original27 removal cases; both PE bases')
if __name__=='__main__':main()
