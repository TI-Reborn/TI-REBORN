"""Original0D dispatcher/parser; logging and UI/string helpers stubbed.
Verifies one status byte consumed, success log and error UI branches.
"""
import json,struct
from verify_auth_native import emulator,put32,get32,return_from_stub,DATA,STOP,ROOT,EXPECTED_SHA
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX,UC_X86_REG_ESP,UC_X86_REG_EBP,UC_X86_REG_EIP
from tio.protocol.auth2 import encode_auth2_result

def run(status):
    u=emulator();packet=encode_auth2_result(status);u.mem_write(DATA,packet)
    put32(u,0xac622c,DATA+0x5000)
    calls=[];consumed=None;logs=[]
    def hook(uc,addr,size,user):
        nonlocal consumed
        if addr==0x87d93d:consumed=get32(uc,uc.reg_read(UC_X86_REG_EBP)-4)-(DATA+1)
        if addr==0x6061b0:logs.append(uc.reg_read(UC_X86_REG_EAX))
        if addr==0x4244b4:put32(uc,uc.reg_read(UC_X86_REG_EDX),0)
        elif addr==0x40c1bc:put32(uc,uc.reg_read(UC_X86_REG_EAX),0)
        elif addr not in (0x6061b0,0xa40094,0x6d4190,0x6d4090,0x40b0fc):return
        calls.append(hex(addr));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,13);u.reg_write(UC_X86_REG_EDX,DATA+1);u.reg_write(UC_X86_REG_ECX,len(packet))
    u.emu_start(0x87daa4,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP and consumed==1
    assert ('0xa40094' in calls)==(status!=0)
    if status==0:assert logs==[0x87d974]
    return {'packet_hex':packet.hex(),'log_addresses':[hex(p) for p in logs],'consumed':consumed,'stubs':sorted(set(calls))}

def main():
    cases=[run(s) for s in (0,1,255)]
    (ROOT/'evidence/native_auth2_probe.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n',encoding='utf-8')
    print('3 original-x86 AuthReply2 cases passed.')
if __name__=='__main__':main()
