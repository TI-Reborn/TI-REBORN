"""Actual85A0F2 Arena mode argument -> selector state -> original BA01 browse.

The genuine Arena callback argument/frame and93FE70 parameter store execute.
Managed allocation/reference sinks are isolated. The existing native verifier
then runs actual944290 empty refresh,9406DA completed show and9443D0/944434
navigation callbacks/native BA01 transport writer. No graphical process input.
"""
import inspect,json,sys
from pathlib import Path
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_legacy_lobbies_native import emulator,put,get,ret,restart,STOP,DATA
from tools import verify_arena_empty_roster_navigation_native as final
from tools import verify_arena_lobby_search_status_native as previous
from deploy.client_server_list_status import sha
FOLDER=final.FOLDER

def actual_argument(raw,base):
    u=emulator(raw,base);delta=base-0x400000;object_=DATA+0x1000;gate=DATA+0x2000;calls=[]
    put(u,0xac6218+delta,gate);u.mem_write(gate,b'\0')
    def hook(uc,address,size,_):
        va=address-delta;a,d,c=(uc.reg_read(r) for r in (UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX))
        if va==0x93fe70:calls.append(dict(mode_stack=get(uc,uc.reg_read(UC_X86_REG_ESP)+4),ecx=c))
        elif va==0x40ed04:ret(uc)
        elif va==0x4092ac:uc.reg_write(UC_X86_REG_EAX,object_);ret(uc)
        elif va==0x40eca8:put(uc,a,d);ret(uc)
        elif va==0x93fed2:uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EBX,0);restart(u);u.emu_start(0x85a0ca+delta,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==0x93fed2+delta
    mode=u.mem_read(object_+0x0d,1)[0]
    assert mode==0 and calls==[dict(mode_stack=0,ecx=0)]
    assert u.mem_read(gate,1)==b'\1'
    return dict(base=hex(base),entry='85a0ca ->85a0dc push0 ->85a0f2 ->93fe70 ->93fecf',actual_selector_mode=mode,entry_call=calls[0],actual_native_argument_and_parameter_store=True)

def main():
    candidate=(FOLDER/'silver.dll').read_bytes();old=(FOLDER.parent/'client-search-availability/silver.dll').read_bytes()
    # Run the frozen previous selector harness with the actual completed mode0,
    # preserving its original expected disabled result for this regression.
    code=inspect.getsource(previous.selector).replace('def selector(','def previous_mode0(').replace("u.mem_write(DATA+0x100d,b'\\x04')","u.mem_write(DATA+0x100d,b'\\x00')").replace("==b'\\x04'","==b'\\x00'").replace("if after_setup:expected=[0,1,1]", "if after_setup:expected=[0,0,0]")
    namespace=previous.__dict__.copy();exec(code,namespace)
    cases=[]
    for base in (0x400000,0x10400000):
        entry=actual_argument(candidate,base);mode=entry['actual_selector_mode']
        failed=namespace['previous_mode0'](old,base,0,True);assert failed['final_enabled']==[0,0,0]
        opened=final.selector(candidate,base,8,True,mode);assert opened['final_enabled']==[0,1,1]
        refreshed=final.selector(candidate,base,mode,False);assert refreshed['final_enabled']==[0,1,1]
        for category in (1,4):
            navigation=final.navigation(candidate,base,category)
            row=final.lobby(candidate,base,category,1,2 if category==1 else 4,[(4,0),(4,0)])
            assert row['colour_hex']=='ff6060ff'
            cases.append(dict(entry=entry,previous9d24_disabled_regression=failed,completed_actual_arena=opened,subsequent_empty_refresh=refreshed,original_navigation=navigation,actual_two_level4_owned_fighters=row))
    report=dict(passed=True,method=__doc__,candidate_sha256=sha(candidate),previous9d24_sha256=sha(old),cases=cases,actual_owned_gui_state_before_fix='owned-d-selector-state-before-fix.json',owned_gui_state_sha256=sha((FOLDER/'owned-d-selector-state-before-fix.json').read_bytes()),native_gui_driven=False,authentication_calls=False,hosted_modified=False)
    target=FOLDER/'actual-arena-entry-proof.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print('PASS actual Arena mode0 -> enabled tabs -> BA01 -> red owned4/4 rows, both PE bases')
if __name__=='__main__':main()
