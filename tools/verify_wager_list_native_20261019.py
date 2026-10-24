"""Published x86 opcode dispatch and row-ID deletion; collections/UI isolated."""
import hashlib,json,sys
from pathlib import Path
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_legacy_lobbies_native import emulator,put,get,ret,run,DATA,STOP
from tio.protocol.wagers import encode_room_removed,encode_room_list_clear

def verify(base):
    raw=(ROOT/'work/groza-20261019/gui/game-a/silver.dll').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'
    u=emulator(raw,base);delta=base-0x400000;a=lambda va:va+delta
    collection=DATA+0x1000;iterator=DATA+0x2000;vtable=DATA+0x2400;destroy=DATA+0x2500
    put(u,a(0xacf394),collection);put(u,iterator,vtable);put(u,vtable-4,destroy)
    pointers={identity:DATA+0x4000+n*0x100 for n,identity in enumerate((42,73,999999))}
    for identity,pointer in pointers.items():put(u,pointer,identity)
    state=dict(rows=list(pointers.values()),snapshot=[],index=-1,removed=[],clear_calls=0)
    def hook(uc,address,size,_):
        va=address-delta
        if va==0x87b43c:
            state['snapshot']=list(state['rows']);state['index']=-1;uc.reg_write(UC_X86_REG_EAX,iterator);ret(uc)
        elif va==0x87b4c0:
            state['index']+=1;uc.reg_write(UC_X86_REG_EAX,int(state['index']<len(state['snapshot'])));ret(uc)
        elif va==0x87b450:
            uc.reg_write(UC_X86_REG_EAX,state['snapshot'][state['index']]);ret(uc)
        elif va==0x87b1fc:
            pointer=uc.reg_read(UC_X86_REG_EDX);uc.reg_write(UC_X86_REG_EAX,state['rows'].index(pointer));ret(uc)
        elif va==0x87ae74:
            index=uc.reg_read(UC_X86_REG_EDX);pointer=state['rows'].pop(index);state['removed'].append(get(uc,pointer));ret(uc)
        elif va==0x873134:state['clear_calls']+=1
        elif va==0x87b170:state['rows'].clear();ret(uc)
        elif va in (0x87251c,0x8725d8,0x8731cc,0x872e84,0x40ceac,0x9cfa38):ret(uc)
        elif address==destroy:ret(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    def execute(packet):
        u.mem_write(DATA,packet[1:] or b'\0')
        u.reg_write(UC_X86_REG_EAX,packet[0]);u.reg_write(UC_X86_REG_EDX,DATA);u.reg_write(UC_X86_REG_ECX,len(packet))
        run(u,0xa0b234,base)
        assert u.reg_read(UC_X86_REG_EAX)&255==1
    execute(encode_room_removed(73));assert [get(u,p) for p in state['rows']]==[42,999999]
    execute(encode_room_removed(12345));assert [get(u,p) for p in state['rows']]==[42,999999]
    execute(encode_room_list_clear());assert not state['rows'] and state['clear_calls']==1
    execute(encode_room_list_clear());assert not state['rows'] and state['clear_calls']==2
    return dict(base=hex(base),passed=True,removed=state['removed'],unknown_stale_id_removed=999999 in state['removed'],
                missing_id_is_noop=True,clear_idempotent=True,dispatcher='a0b234',delete_consumer='a09468->873094',clear_consumer='a09480->873134')

if __name__=='__main__':
    result=dict(passed=True,graphical_clients=False,method=__doc__,cases=[verify(b) for b in (0x400000,0x1400000)])
    (ROOT/'reports/wager-list-fix-20261019/native-removal.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
