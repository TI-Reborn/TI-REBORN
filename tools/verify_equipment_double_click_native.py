"""Original equipment widget DoMouseDoubleClick for backpack/equipped items.

Inherited mouse notification, custom event presence and destination policy
are isolated. This checks callback arguments, not server toggle semantics.
"""
from verify_auth_native import *

def run(equipped):
    u=emulator(); widget=DATA+0x1000; owners=DATA+0x2000; pet=DATA+0x3000;calls=[]
    assert bytes(u.mem_read(0xa2fa1e,18))==b'DoMouseDoubleClick'
    assert get32(u,0xa2fa19)==0xa4dba0
    put32(u,0xac64b4,DATA+0x2100);put32(u,0xac618c,owners);put32(u,owners,pet)
    put32(u,pet+0x28,17);put32(u,widget+0x288+0x28,1001)
    u.mem_write(widget+0x288+0x30,bytes((equipped,)))
    def hook(uc,address,size,user):
        if address in (0xa42f18,0x40b0fc):return_from_stub(uc)
        elif address==0xa54980:
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif address==0xa6516c:
            item=uc.reg_read(UC_X86_REG_EDX)
            calls.append({'pet_id':uc.reg_read(UC_X86_REG_EAX),'instance_id':get32(uc,item+0x28),
                          'equipped':bytes(uc.mem_read(item+0x30,1))[0],'target':uc.reg_read(UC_X86_REG_ECX)})
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,widget)
    u.emu_start(0xa4dba0,STOP,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert calls==[{'pet_id':17,'instance_id':1001,'equipped':equipped,'target':0}]
    return calls[0]

if __name__=='__main__':
    cases=[run(0),run(1)]
    (ROOT/'evidence/equipment_double_click_native.json').write_text(json.dumps(
        {'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n',encoding='utf-8')
    print('Original equipment double-click:backpack/equipped -> same untargeted policy PASS')
