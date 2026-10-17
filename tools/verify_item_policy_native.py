"""Run a6516c with isolated UI/lifetime and synthetic ordinary-item metadata.

This verifies target propagation through the complete policy, not real catalog
compatibility. Original target conversion and branches execute unchanged.
"""
from verify_auth_native import *


def run(mask=None):
    u=emulator(); closure=DATA+0x1000; item=DATA+0x2000; target=DATA+0x2400
    owners=DATA+0x2800; pet=DATA+0x4000; metadata=DATA+0xb000; calls=[]
    put32(u,item+0x28,1001);put32(u,item+8,301)
    put32(u,target+0x280,mask or 0)
    put32(u,0xac618c,owners);put32(u,owners,pet);put32(u,pet+0x28,17)
    put32(u,0xac637c,DATA+0x3000);put32(u,DATA+0x3000,metadata)
    u.mem_write(metadata+0x68d,b'\x01')
    for address in (0xac62f8,0xac64a0,0xac6118):put32(u,address,DATA+0x3100)
    def hook(uc,address,size,user):
        values={0x4092ac:closure,0xa93f70:0,0xa843ac:1,0xa7b030:0,
                0xa7b6e8:0,0xa7b740:0,0xa7b254:0,0xa7bce0:0,
                0xa7b898:0,0xa7b290:0,0xa7b2bc:0,0xa7bcac:0,0xa7bdac:0}
        if address in values:
            uc.reg_write(UC_X86_REG_EAX,values[address]);return_from_stub(uc)
        elif address in (0x40cb10,0x40c9a4,0x40ec90,0x40b0fc,0xa68df4):return_from_stub(uc)
        elif address==0x40eca8:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX));return_from_stub(uc)
        elif address==0x40cc38:
            uc.mem_write(uc.reg_read(UC_X86_REG_EAX),bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EDX),0x290)))
            return_from_stub(uc)
        elif address==0x9903a4:
            sp=uc.reg_read(UC_X86_REG_ESP)
            calls.append({'pet_id':uc.reg_read(UC_X86_REG_EAX),'instance_id':uc.reg_read(UC_X86_REG_EDX),
                          'option':get32(uc,sp+4)&255})
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,sp+8)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,17);u.reg_write(UC_X86_REG_EDX,item)
    u.reg_write(UC_X86_REG_ECX,0 if mask is None else target)
    u.emu_start(0xa6516c,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    expected=[] if mask in (0x40000,0x80000,0x100000,0x200000) else [
        {'pet_id':17,'instance_id':1001,'option':255 if mask is None else {1:0,0x10:4,0x80:7}[mask]}]
    assert calls==expected,(mask,calls)
    return {'target_mask':mask,'calls':calls,'returned':True}


if __name__=='__main__':
    cases=[run(mask) for mask in (None,1,0x10,0x80,0x40000)]
    (ROOT/'evidence/item_policy_native.json').write_text(json.dumps(
        {'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n',encoding='utf-8')
    print('Original complete item policy:5 target propagation/gating cases PASS')
