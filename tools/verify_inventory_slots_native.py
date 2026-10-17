"""Original inventory slot normalization99082a..9908b4 plus RTTI names."""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX,UC_X86_REG_EDI

if __name__=='__main__':
    u=emulator()
    for address,name,method in ((0x6125de,b'getEquipped',0x63c770),(0x61261b,b'getSlot',0x63c7d0)):
        assert bytes(u.mem_read(address,len(name)))==name
        assert get32(u,address-5)==method
    cases=[]
    for value in (0,1,2,4,0x800,0x1000,0x2000,0x40000):
        u=emulator();slots=DATA+0x1000;pet=DATA+0x2000;item=DATA+0x3000
        put32(u,0xac618c,slots);put32(u,slots,pet);put32(u,pet+0x6c,item)
        u.reg_write(UC_X86_REG_EAX,value)
        u.reg_write(UC_X86_REG_EBX,0);u.reg_write(UC_X86_REG_EDI,0)
        u.emu_start(0x99082a,0x9908b4,count=1000)
        assert u.reg_read(UC_X86_REG_EIP)==0x9908b4
        normalized=get32(u,item+0x34)
        assert normalized==(4 if value in (0x800,0x1000,0x2000) else value)
        cases.append({'slot':value,'client_slot':normalized})
    (ROOT/'evidence/inventory_slots_native.json').write_text(json.dumps(
        {'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Inventory slot RTTI and8 native normalizations PASS')
