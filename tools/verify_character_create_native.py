"""Original result parser with UI/logging/localization stubs, all status branches."""
from verify_auth_native import *
from tio.protocol.character_create import encode_character_create_result

def run(status):
    u=emulator();packet=encode_character_create_result(status);u.mem_write(DATA,packet)
    calls=[];consumed=[]
    targets={0x6675e0,0x6d4190,0xa88908,0x8a2868,0x8a2538,0x6d4090,0x9dc760,0x40b0fc}
    def hook(uc,addr,size,user):
        if addr==0x88a8be:consumed.append(get32(uc,uc.reg_read(UC_X86_REG_EBP)-4)-DATA)
        if addr in targets:
            calls.append([hex(addr),uc.reg_read(UC_X86_REG_EAX)])
            if addr==0x8a2538:uc.reg_write(UC_X86_REG_EAX,0)
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA+1)
    u.emu_start(0x88a79c,STOP,count=5000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP and consumed==[2]
    logs=[a for f,a in calls if f=='0xa88908']
    assert logs==[{1:0x88a93c,2:0x88a988,3:0x88a9d4,4:0x88aa20}.get(status,0x88aa3c)]
    assert any(f=='0x8a2868' for f,a in calls)==(status not in (1,2,3,4))
    return {'status':status,'calls':calls,'consumed':2}

if __name__=='__main__':
    cases=[run(s) for s in (0,1,2,3,4,255)]
    (ROOT/'evidence/native_character_create_result.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('6 original-x86 create result cases passed.')
