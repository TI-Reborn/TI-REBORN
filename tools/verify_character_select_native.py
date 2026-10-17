"""Original empty10 parser and export gate; UI/record lifecycle explicitly stubbed."""
import json,struct,capstone,pefile
from verify_auth_native import emulator,put32,get32,return_from_stub,DATA,STACK,STOP,ROOT,BINARY,EXPECTED_SHA
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX,UC_X86_REG_ESP,UC_X86_REG_EBP,UC_X86_REG_EIP

def parser(panel):
    u=emulator();u.mem_write(DATA,b'\x10\0\0')
    put32(u,0xac5a40,DATA+0x1000);u.mem_write(DATA+0x1000,b'\1')
    put32(u,0xac5814,DATA+0x2000)
    calls=[];consumed=None
    noops={0x40c8cc,0xa69d68,0xa69aa0,0xa69ab0,0x9dc76c,0x8894cc,0x8a2868,0x40c9f4,0x435664,0x40c9a4,0x40b09c,0x9cfa38}
    def hook(uc,addr,size,user):
        nonlocal consumed
        if addr==0x88a3e6:consumed=get32(uc,uc.reg_read(UC_X86_REG_EBP)-0x29c)-(DATA+1)
        if addr in noops:
            calls.append(hex(addr))
            if addr==0xa69d68:uc.reg_write(UC_X86_REG_EAX,panel)
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,16);u.reg_write(UC_X86_REG_EDX,DATA+1);u.reg_write(UC_X86_REG_ECX,3)
    u.emu_start(0x88b33c,STOP,count=20000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP and consumed==2
    assert bytes(u.mem_read(DATA+0x1000,1))==b'\0' and bytes(u.mem_read(DATA+0x2000,1))==b'\1'
    assert '0x8a2868' in calls
    return {'panel_result':panel,'consumed':consumed,'flag_ac5814':1,'stubs':calls}

def gate(flag,override):
    u=emulator();u.mem_map(DATA+0x10000,0x10000);u.mem_write(DATA,b'\x10\0\0');put32(u,0xac5834,DATA+0x1000);u.mem_write(DATA+0x1000,bytes((flag,)))
    put32(u,0xac656c,DATA+0x2000);put32(u,DATA+0x2000,DATA+0x3000)
    sp=STACK+0x8000;u.mem_write(sp,struct.pack('<5I',STOP,16,DATA,3,override));u.reg_write(UC_X86_REG_ESP,sp)
    pe=pefile.PE(str(BINARY));md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
    targets={int(i.op_str,16) for i in md.disasm(pe.get_data(0x9f5548-0x400000,0x28b),0x9f5548) if i.mnemonic=='call' and i.op_str.startswith('0x')}
    reached=[]
    def hook(uc,addr,size,user):
        if addr==0x889eac:
            reached.append('character_parser');return_from_stub(uc)
        elif addr==0x9cfa38:return_from_stub(uc)
        elif addr in targets and addr!=0x88b33c:
            if addr==0x9faf74:reached.append('deferred_handler')
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x9f5548,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert reached==(['character_parser'] if not flag or override else ['deferred_handler'])
    return {'gate_flag':flag,'override':override,'reached':reached,'method':'original export gate and character dispatcher, other dispatchers/parser stubbed'}

def main():
    cases=[parser(p) for p in (0,1)]+[gate(f,o) for f in (0,1) for o in (0,1)]
    (ROOT/'evidence/native_character_select_probe.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n',encoding='utf-8')
    print('6 original-x86 character-select/gate cases passed.')
if __name__=='__main__':main()
