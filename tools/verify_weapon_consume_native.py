"""Execute native consume attribute stores; XML lookup/conversion isolated."""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX


def run(ammo,amount):
    u=emulator();frame=STACK+0x7000;closure=DATA;table=DATA+0x1000;node=DATA+0x9000
    put32(u,closure+12,0);put32(u,0xac637c,DATA+0x8000);put32(u,DATA+0x8000,table)
    put32(u,frame-0x144,node);put32(u,node+0x20,node)
    def hook(uc,address,size,user):
        if address==0x68266c:
            uc.reg_write(UC_X86_REG_EAX,node);return_from_stub(uc)
        elif address==0x680770:
            key=uc.reg_read(UC_X86_REG_EDX)
            assert key in (0xa75138,0xa75154)
            put32(uc,uc.reg_read(UC_X86_REG_ECX),amount if key==0xa75138 else ammo)
            return_from_stub(uc)
        elif address==0x424760:
            # The lookup stub represents each numeric string by its integer.
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EBP,frame);u.reg_write(UC_X86_REG_EBX,closure)
    u.emu_start(0xa72279,0xa7232f,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==0xa7232f
    word=lambda off:int.from_bytes(u.mem_read(table+off,2),'little')
    assert (word(0x12e),word(0x130),word(0x13e))==(ammo,amount,amount)
    return {'ammo_id':ammo,'bullets':amount}


if __name__=='__main__':
    cases=[run(3,1),run(3,5),run(317,1)]
    (ROOT/'evidence/weapon_consume_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,
        'bindings':'for/consume amount->metadata13e/130,id->12e; attackType a7066e ->a75d38 ->12c',
        'cases':cases},indent=2)+'\n')
    print('Native consume ammo/count stores:3 cases PASS')
