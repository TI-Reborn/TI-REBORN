"""Execute original81 writer with real integer writers; transport isolated."""
from verify_auth_native import *
from tio.protocol.ability_cast import AbilityCast,encode_ability_cast

def run(request):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush);put32(u,0xac600c,handle)
    def hook(uc,address,size,user):
        if address==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address==flush:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    sp=u.reg_read(UC_X86_REG_ESP);put32(u,sp+4,request.y);put32(u,sp+8,request.x)
    u.reg_write(UC_X86_REG_EAX,request.ability_id);u.reg_write(UC_X86_REG_EDX,request.actor_id);u.reg_write(UC_X86_REG_ECX,request.unknown_u32)
    u.emu_start(0x8c0730,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert packet==encode_ability_cast(request)
    return packet.hex()

if __name__=='__main__':
    cases=[run(r) for r in (AbilityCast(23,4,0,3,7),AbilityCast(26,0x12345678,0,254,1),AbilityCast(0xffffffff,7,0x87654321,0,255))]
    (ROOT/'evidence/ability_cast_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Original ability cast writer:3 cases PASS')
