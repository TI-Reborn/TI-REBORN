"""Original95e1e0 YourTurn callback; notifications/UI/timer setter isolated."""
from verify_auth_native import *

if __name__=='__main__':
    cases=[]
    for seconds in (1,40,120):
        u=emulator();handle=DATA+0x100;body=DATA+0x200;calls=[]
        put32(u,handle,body);put32(u,body,seconds)
        for n,address in enumerate((0xac5fe4,0xac5a98,0xac5cd4,0xac6264,0xac6284,0xac6008,0xac6488)):
            put32(u,address,DATA+0x1000+n*0x100)
        put32(u,DATA+0x1000,1000);put32(u,DATA+0x1100,17)
        u.mem_write(DATA+0x1500+0x19,b'\x02')
        put32(u,DATA+0x1600,DATA+0x2000);put32(u,DATA+0x2000+0x348,DATA+0x3000)
        put32(u,DATA+0x3004,0xffffffff)
        def hook(uc,a,size,user):
            if a in (0x961edc,0x9dc96c):
                calls.append({'target':hex(a),'character_id':uc.reg_read(UC_X86_REG_EAX),
                              'edx':uc.reg_read(UC_X86_REG_EDX)})
                return_from_stub(uc)
        u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,body)
        u.emu_start(0x95e1e0,STOP,count=1000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        assert get32(u,0xac4b20)==1500 and get32(u,DATA+0x1200)==17
        assert bytes(u.mem_read(DATA+0x1300,1))==b'\x01'
        assert calls[1]=={'target':'0x9dc96c','character_id':17,'edx':seconds}
        cases.append({'seconds':seconds,'turn_owner':17,'end_turn_deadline':1500,'timer_call':calls[1]})
    (ROOT/'evidence/turn_begin_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n',encoding='utf-8')
    print('Original YourTurn callback:3 duration/ownership cases PASS')
