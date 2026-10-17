"""Original8b72c8 weapon-swap writer; transport flush/UI helpers isolated."""
from verify_auth_native import *


def main():
    cases=[]
    for actor in (1,3,0x12345678):
        u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
        put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush)
        put32(u,0xac600c,handle);put32(u,0xac5940,DATA+0x3300)
        def hook(uc,address,size,user):
            if address==0x6748b0:
                uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
            elif address in (flush,0x9dc760):return_from_stub(uc)
        u.hook_add(UC_HOOK_CODE,hook)
        u.reg_write(UC_X86_REG_EAX,actor)
        u.emu_start(0x8b72c8,STOP,count=3000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
        assert packet==b'\x6d'+actor.to_bytes(4,'little')
        cases.append({'actor_id':actor,'packet_hex':packet.hex()})
    (ROOT/'evidence/weapon_swap_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Original weapon swap writer:3 cases PASS')


if __name__=='__main__':main()
