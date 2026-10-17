"""Original hand-to-hand drag branch a6641d; stop before unrelated UI refresh.

UI controls/selected pet are synthetic; original source/destination checks
execute. Capture the native 8b72c8 swap call, whose wire writer is verified
separately by verify_weapon_swap_native.py. No live rendering claim.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_ESI,UC_X86_REG_EDI


def run(source,destination):
    u=emulator();calls=[]
    put32(u,DATA+0x10,DATA+0x1000)
    put32(u,DATA+0x1000+0x280,source)
    put32(u,DATA+0x100,DATA+0x2000)
    put32(u,DATA+0x2000+0x280,destination)
    put32(u,0xac64b4,DATA+0x3000);put32(u,DATA+0x3000,0)
    put32(u,0xac618c,DATA+0x3100);put32(u,DATA+0x3100,DATA+0x4000)
    put32(u,DATA+0x4000+0x28,17)
    def hook(uc,address,size,user):
        if address==0x8b72c8:
            calls.append(uc.reg_read(UC_X86_REG_EAX));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EDI,DATA);u.reg_write(UC_X86_REG_ESI,DATA+0x100)
    u.emu_start(0xa6641d,0xa66469,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==0xa66469
    assert calls==([17] if source in (16,128) and destination in (16,128) else [])
    return {'source':source,'destination':destination,'swap_pet_ids':calls}


if __name__=='__main__':
    cases=[run(a,b) for a,b in ((16,128),(128,16),(4,128),(16,4))]
    print(json.dumps({'sha256':EXPECTED_SHA,'cases':cases,'status':'PASS'}))
