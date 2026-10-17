"""Original08 dispatcher/parser; UI/string helpers/connect callback stubbed.
Verifies status branching and exact saved host/port/optional string/mode arguments.
"""
import json,struct
from verify_auth_native import emulator,put32,get32,return_from_stub,DATA,STOP,ROOT,EXPECTED_SHA
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX,UC_X86_REG_ESP,UC_X86_REG_EBP,UC_X86_REG_EIP
from tio.protocol.server_login import encode_server_login_result

def run(status):
    u=emulator();packet=encode_server_login_result(status);u.mem_write(DATA,packet)
    put32(u,0xac5788,DATA+0x1000);put32(u,DATA+0x1000,DATA+0x2000)
    u.mem_write(DATA+0x100c,struct.pack('<H',12345))
    put32(u,0xac5e44,DATA+0x3000);put32(u,DATA+0x3000,DATA+0x4000)
    put32(u,0xac622c,DATA+0x5000)
    calls=[];connect=[];consumed=None
    def hook(uc,addr,size,user):
        nonlocal consumed
        if addr==0x87d4b9:consumed=get32(uc,uc.reg_read(UC_X86_REG_EBP)-4)-(DATA+1)
        if addr==0x606080:
            sp=uc.reg_read(UC_X86_REG_ESP)
            connect.append([uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX),uc.reg_read(UC_X86_REG_ECX),get32(uc,sp+4)])
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,sp+8);return
        if addr==0x4244b4:put32(uc,uc.reg_read(UC_X86_REG_EDX),0)
        elif addr==0x40c1bc:put32(uc,uc.reg_read(UC_X86_REG_EAX),0)
        elif addr not in (0x6061b0,0xa40094,0x6d4190,0x6d4090,0x40b0fc):return
        calls.append(hex(addr));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,8);u.reg_write(UC_X86_REG_EDX,DATA+1);u.reg_write(UC_X86_REG_ECX,len(packet))
    u.emu_start(0x87daa4,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP and consumed==1
    assert connect==([[DATA+0x2000,12345,DATA+0x4000,1]] if status==0 else [])
    return {'packet_hex':packet.hex(),'connect_arguments':connect,'consumed':consumed,'stubs':sorted(set(calls))+(['0x606080'] if connect else [])}

def main():
    cases=[run(s) for s in (0,1,255)]
    (ROOT/'evidence/native_server_login_probe.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n',encoding='utf-8')
    print('3 original-x86 server-login result cases passed.')
if __name__=='__main__':main()
