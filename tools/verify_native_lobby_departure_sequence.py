"""Execute actual native25 merge and27 clear for decoded two-account TCP streams.

Real hosted-source Team/Wager candidate packets are decoded including soldiers;
their ID order enters the original25 numeric reader/managed records/slot router.
Nested soldier conversion and UI/event sinks are isolated, as in the prior
native-member-leave proof. The original27 numeric reader/clear loop executes.
"""
from pathlib import Path
import json,sys
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_legacy_member_leave_native import fixture,state,SOURCE
from tools.verify_legacy_lobbies_native import DATA,STACK,put,get,ret,run
from tio.protocol.battle_members import BattleMemberRecord,encode_battle_members,decode_battle_members
from deploy.client_server_list_status import sha
FOLDER=ROOT/'reports/gameplay-completion/legacy-status-20261011/runtime-native-lobby-departure'

def sequence(raw,base,case):
 u,delta,slots=fixture(raw,base);u.mem_write(slots,bytes(8*0x1c0));root,records,flags,strings=(DATA+x for x in (0x2000,0x3000,0x5000,0x6000))
 phase='members';target_ids=[];events=[]
 def hook(uc,address,size,_):
  va=address-delta;a,d,c=(uc.reg_read(r) for r in (UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX))
  if va==0x64ea6c:put(uc,a+4,records);put(uc,a+8,d);put(uc,a+12,flags);ret(uc)
  elif va==0x6297e0:
   cursor=get(uc,0xacd0e8+delta);value=bytes(uc.mem_read(cursor,256)).split(b'\0',1)[0]
   put(uc,0xacd0e8+delta,cursor+len(value)+1);put(uc,d,strings);uc.mem_write(strings,bytes((len(value),))+value);ret(uc)
  elif va==0x40c06c:
   n=uc.mem_read(d,1)[0];uc.mem_write(a,bytes(uc.mem_read(d,n+1)));ret(uc)
  elif va in (0x40b09c,0x40c8cc,0x40c9a4,0xa0ac58,0xa01bf4,0x40b0fc,0x40c9f4,0x435664):ret(uc)
  elif va==0xa09b78:
   parent=get(uc,uc.reg_read(UC_X86_REG_ESP)+4);identity=get(uc,parent-0x138)
   uc.mem_write(slots+a*0x1c0,b'\1');put(uc,slots+a*0x1c0+4,identity);ret(uc)
  elif va==0xa0a424:events.append(a);ret(uc)
  elif va==0x66754c:uc.reg_write(UC_X86_REG_EAX,int(phase=='remove'));ret(uc)
 u.hook_add(UC_HOOK_CODE,hook)
 history=[]
 packets=[bytes.fromhex(case['initial_member_packet_hex'])]+[bytes.fromhex(x) for x in case['native_sequence_hex']]
 for actual in packets:
  if actual[0]==0x25:
   phase='members';mode,flag,decoded=decode_battle_members(actual)
   # Isolate the already separately-tested nested soldier codec, preserving
   # every authentic member identity/name/level/order/readiness field.
   compact=encode_battle_members(mode,flag,tuple(BattleMemberRecord(r.character_id,r.name,r.unknown_u32,r.unknown_bytes) for r in decoded))
   u.mem_write(DATA,compact[1:]);put(u,0xacd0e8+delta,DATA);u.reg_write(UC_X86_REG_EAX,root);run(u,0x64e6b4,base)
   assert get(u,0xacd0e8+delta)-DATA==len(compact)-1
   u.reg_write(UC_X86_REG_EAX,root);run(u,0xa0a29c,base)
  elif actual[0]==0x27:
   phase='remove';assert len(actual)==5;u.mem_write(DATA,actual[1:]);u.reg_write(UC_X86_REG_EAX,DATA);run(u,0xa0a44c,base)
  else:raise AssertionError(actual.hex())
  history.append(dict(opcode=actual[0],active_ids=[r['identity'] for r in state(u,slots) if r['active']]))
 assert history[0]['active_ids']==case['initial_ids']
 assert [h['active_ids'] for h in history[1:]]==[[1],[1]],history
 assert events==[case['initial_ids'][1]]
 return dict(base=hex(base),kind=case['kind'],mode=case['mode'],action=case['action'],history=history,original27_removed_public_id=events[0],final_slots=state(u,slots),actual_original_slot_consumers=True)

def main():
 raw=SOURCE.read_bytes();report=json.loads((FOLDER/'tcp-cases.json').read_text())
 cases=[sequence(raw,b,c) for c in report['cases'] if c['native_sequence_hex'] for b in (0x400000,0x10400000)]
 assert len(cases)==24
 out=dict(passed=True,method=__doc__,native_sha256=sha(raw),tcp_cases_sha256=sha((FOLDER/'tcp-cases.json').read_bytes()),cases=cases,real_gui_driven=False,published=False)
 (FOLDER/'native-tcp-sequence-proof.json').write_text(json.dumps(out,indent=2)+'\n');print('PASS 24 authentic TCP ->25/27 -> native slot sequences, two PE bases')
if __name__=='__main__':main()
