"""Original TurnFinished -> foreign TurnNow, starting with active input."""
from verify_auth_native import *
from verify_action_points_native import run as action_points


def run():
    u=emulator();calls=[]
    for n,address in enumerate((0xac5a98,0xac5cd4,0xac6264,0xac6488,0xac5834)):
        put32(u,address,DATA+0x1000+n*0x100)
    put32(u,DATA+0x1000,17);put32(u,DATA+0x1100,17);put32(u,DATA+0x1200,1)
    put32(u,DATA+0x1300,DATA+0x2000);put32(u,DATA+0x2348,DATA+0x3000);put32(u,DATA+0x3004,0xffffffff)
    def hook(uc,a,size,user):
        if a in (0x961f3c,0x43afc0,0xa88a78,0x765ed4,0xa69d68,0x435664,0x961edc,0x9dc96c):
            calls.append((a,uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX)))
            if a==0xa69d68:uc.reg_write(UC_X86_REG_EAX,0)
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(0x95e270,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP and get32(u,DATA+0x1200)==0
    body=DATA+0x5000;put32(u,body,18);u.mem_write(body+4,b'\1');put32(u,body+8,40);u.mem_write(body+12,b'\1')
    u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_EAX,body)
    u.emu_start(0x95e170,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert get32(u,DATA+0x1200)==0 and get32(u,DATA+0x1100)==18
    assert (0x9dc96c,18,40) in calls
    return dict(ap=action_points(0),input_disabled=True,foreign_timer_owner=18,seconds=40,
                limitation='Original state handlers executed; rendering, audio and timer display calls stubbed.')


if __name__=='__main__':
    result=run();(ROOT/'reports/ui-four-regressions/turn-native.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Native AP=0, finish disables active input, foreign timer ownership: PASS')
