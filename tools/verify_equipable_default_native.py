"""Original XML equipable access, missing-key helper branch and metadata write.

Managed strings and dictionary lookup isolated; lookup returns key absent.
The default and destination are read from actual loader instructions.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EDI

if __name__ == '__main__':
    u=emulator(); closure=DATA+0x1000; node=DATA+0x2000; table=DATA+0x3000
    put32(u,closure+0xc,0);put32(u,0xac637c,DATA+0x2800);put32(u,DATA+0x2800,table)
    assert bytes(u.mem_read(0xa756f4,18))=='equipable'.encode('utf-16le')
    calls=[]
    def hook(uc,address,size,user):
        if address==0x680860:
            calls.append({'key_va':hex(uc.reg_read(UC_X86_REG_EDX)),
                          'default':uc.reg_read(UC_X86_REG_ECX)&255})
        elif address==0x4237d0:
            put32(uc,uc.reg_read(UC_X86_REG_EDX),0);return_from_stub(uc)
        elif address==0x40b09c:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),0);return_from_stub(uc)
        elif address==0x40b0fc:return_from_stub(uc)
        elif address==0x681f48:
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif address==0x4248d8:raise AssertionError('Absent key must not parse a value')
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EBX,closure);u.reg_write(UC_X86_REG_EDI,node)
    u.emu_start(0xa7341f,0xa73443,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==0xa73443
    value=bytes(u.mem_read(table+0x68d,1))[0]
    assert calls==[{'key_va':'0xa756f4','default':1}] and value==1
    (ROOT/'evidence/equipable_default_native.json').write_text(json.dumps(
        {'sha256':EXPECTED_SHA,'method':__doc__,'calls':calls,'metadata_offset':'0x68d',
         'missing_key_value':value},indent=2)+'\n',encoding='utf-8')
    print('Original equipable missing-key default -> metadata+68d=1 PASS')
