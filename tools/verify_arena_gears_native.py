"""Original C6 dispatcher, numeric catalogue reader and city loading gate.

Unicorn executes original x86. Managed allocation/string conversion and UI
caption/row calls are stubbed explicitly; this is not a rendered-client test.
"""
from verify_auth_native import *
from tio.arena_gears import catalogue_packet
from tio.protocol.ranked import decode_gears


def main():
    u=emulator();packet=catalogue_packet();ids=decode_gears(packet)
    button=DATA+0x5000;array=DATA+0x1000
    put32(u,0xacf028,button)
    # The original image aliases ac6020 -> acf028, ac5eb8 -> ac4a9c.
    assert get32(u,0xac6020)==0xacf028 and get32(u,0xac5eb8)==0xac4a9c
    put32(u,0xac4a9c,0);put32(u,0xac5fd8,DATA+0x4000)
    calls=[];consumed=[]
    def hook(uc,a,size,user):
        if a==0x953f5f:
            consumed.append(get32(uc,uc.reg_read(UC_X86_REG_EBP)-4)-(DATA+2))
        if a==0x40d5a4:
            n=get32(uc,uc.reg_read(UC_X86_REG_ESP)+4)
            put32(uc,array-4,n);put32(uc,uc.reg_read(UC_X86_REG_EAX),array)
            return_from_stub(uc)
        elif a==0x6675e0:
            key=uc.reg_read(UC_X86_REG_EAX)
            calls.append(('localize',key))
            put32(uc,uc.reg_read(UC_X86_REG_EDX),key);return_from_stub(uc)
        elif a==0x40c05c:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX));return_from_stub(uc)
        elif a==0xa42b04:
            assert uc.reg_read(UC_X86_REG_EAX)==button
            calls.append(('caption',uc.reg_read(UC_X86_REG_EDX)));return_from_stub(uc)
        elif a==0xa458a4:
            calls.append(('loading_style',a));return_from_stub(uc)
        elif a in (0x9cfa38,0x939ce8,0x939a60,0x40b09c,0x40b0e4):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    def run(entry):
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
        u.emu_start(entry,STOP,count=30000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
    run(0x85b828)
    assert ('localize',0x85b8dc) in calls and any(x[0]=='loading_style' for x in calls)
    checks=['Empty catalogue reproduces original m1108 loading branch']
    for _ in range(2):
        calls.clear();u.mem_write(DATA,packet)
        u.reg_write(UC_X86_REG_EAX,0xc6);u.reg_write(UC_X86_REG_EDX,DATA+1)
        u.reg_write(UC_X86_REG_ECX,len(packet));run(0x9545e0)
        assert u.reg_read(UC_X86_REG_EAX)&255==1
        assert get32(u,array-4)==len(ids)
        assert tuple(get32(u,array+4*i) for i in range(len(ids)))==ids
        assert consumed[-1]==len(packet)-2
        assert ('caption',0x953f98) in calls  # native m135 = Battle / Бои
        calls.clear();run(0x85b828)
        assert not calls,'Populated catalogue still entered the loading branch'
    checks+=['C6/18 dispatched and consumed exactly; every template stored',
             'Native reader selects m135 (Бои); following city updates skip loading style',
             'Repeated catalogue delivery replaces the list safely']
    report=dict(passed=True,binary_sha256=EXPECTED_SHA,method=__doc__,templates=ids,checks=checks)
    (ROOT/'reports/arena-loading/native.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Original arena catalogue dispatcher/reader/loading gate: PASS')


if __name__=='__main__':main()
