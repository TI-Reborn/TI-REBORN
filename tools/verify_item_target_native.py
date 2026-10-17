"""Execute original a7a050 target-control mask to action33 option conversion."""
from verify_auth_native import *

if __name__ == '__main__':
    u = emulator()
    masks = (1,2,4,8,0x10,0x20,0x40,0x80,0x100,0x200,0x400,
             0x4000,0x8000,0x10000,0x20000,0x40000,0x80000,0x100000,0x200000)
    cases = []
    for mask in (*masks,0,3,0x800,0x1000,0x2000,0xffffffff):
        sp = STACK+0x8000
        put32(u,sp,STOP);u.reg_write(UC_X86_REG_ESP,sp)
        u.reg_write(UC_X86_REG_EAX,mask)
        u.emu_start(0xa7a050,STOP,count=100)
        assert u.reg_read(UC_X86_REG_EIP) == STOP
        option = u.reg_read(UC_X86_REG_EAX) & 255
        assert option == (masks.index(mask) if mask in masks else 255)
        cases.append({'target_mask':mask,'option':option})
    (ROOT/'evidence/item_target_native.json').write_text(json.dumps(
        {'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n',encoding='utf-8')
    print('Original target mask conversion:25 cases PASS')
