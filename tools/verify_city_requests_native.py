"""Original shop991940 and warehouse9921a8 builders; transport/UI bookkeeping isolated."""
from verify_auth_native import *


def run(entry, value, *, waiting=False):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush)
    put32(u,0xac600c,handle);put32(u,0xac5940,DATA+0x3300)
    put32(u,0xac55cc,DATA+0x3400)
    u.mem_write(DATA+0x3300, bytes((int(waiting),)))
    def hook(uc,address,size,user):
        if address==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address in (flush,0x9dc760,0x91759c):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,value);u.reg_write(UC_X86_REG_EDX,1)
    u.emu_start(entry,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert packet==(b'' if waiting and entry==0x991940 else bytes((0x73 if entry==0x991940 else 0x69,value)))
    return dict(entry=hex(entry),waiting=waiting,packet_hex=packet.hex())


if __name__=='__main__':
    cases=[run(entry,value) for entry in (0x991940,0x9921a8) for value in (0,1,3)]
    cases.extend(run(0x991940,value,waiting=True) for value in (0,1,3))
    (ROOT/'evidence/city_requests_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases),indent=2)+'\n',encoding='utf-8')
    print('Original shop/warehouse builders and blocked shop requests: 9 cases PASS')
